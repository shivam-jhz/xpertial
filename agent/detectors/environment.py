"""
XPERTIAL – Environment Auto-Detector
--------------------------------------
Fingerprints the training environment on startup so users never need
to configure anything.  Detects:
  - GPU vendor / VRAM / count via NVML
  - ML framework (PyTorch, TF, JAX) and whether DDP/FSDP is active
  - Cloud provider (AWS, GCP, Azure, Colab, Kaggle, RunPod, Lambda)
  - Python / CUDA / driver versions
  - Estimated instance type + $/hr from a static lookup table

All detection is best-effort: missing capabilities degrade gracefully.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


# ── GPU cost lookup ($/GPU/hr, approximate on-demand) ──────────────────────
_GPU_COST_TABLE: Dict[str, float] = {
    "A100-SXM4-80GB": 3.50,
    "A100-SXM4-40GB": 2.50,
    "A100-PCIE-40GB": 2.21,
    "H100-SXM5-80GB": 8.00,
    "H100-PCIE-80GB": 6.50,
    "V100-SXM2-16GB": 3.06,
    "V100-PCIE-16GB": 2.48,
    "A10G":           1.00,
    "A10":            0.75,
    "T4":             0.35,
    "L4":             0.72,
    "RTX 4090":       0.74,
    "RTX 3090":       0.44,
    "RTX 3080":       0.30,
}

def _gpu_cost_lookup(name: str) -> float:
    for key, cost in _GPU_COST_TABLE.items():
        if key.upper() in name.upper():
            return cost
    return 2.00  # conservative default


@dataclass
class GpuInfo:
    index: int
    name: str
    vram_mb: float
    cost_per_hour: float
    driver_version: str = ""
    cuda_version: str = ""


@dataclass
class EnvironmentInfo:
    # Hardware
    gpus: List[GpuInfo] = field(default_factory=list)
    cpu_count: int = 0
    total_ram_mb: float = 0.0

    # Framework
    framework: str = "unknown"          # pytorch / tensorflow / jax
    framework_version: str = ""
    distributed: bool = False
    distributed_backend: str = ""       # nccl / gloo / mpi
    world_size: int = 1
    local_rank: int = 0

    # Cloud / environment
    cloud_provider: str = "unknown"     # aws / gcp / azure / colab / local / …
    instance_type: str = ""
    hostname: str = ""

    # Python stack
    python_version: str = ""
    cuda_available: bool = False
    cuda_version: str = ""

    # Derived
    estimated_cost_per_hour: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gpus"] = [asdict(g) for g in self.gpus]
        return d


# ── Detection helpers ──────────────────────────────────────────────────────

def _detect_gpus() -> List[GpuInfo]:
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        gpus = []
        driver = ""
        try:
            driver = pynvml.nvmlSystemGetDriverVersion().decode()
        except Exception:
            pass
        cuda_ver = ""
        try:
            v = pynvml.nvmlSystemGetCudaDriverVersion()
            cuda_ver = f"{v // 1000}.{(v % 1000) // 10}"
        except Exception:
            pass
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode()
            except Exception:
                name = f"GPU:{i}"
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                vram_mb = mem.total / 1024 ** 2
            except Exception:
                vram_mb = 0.0
            gpus.append(GpuInfo(
                index=i, name=name, vram_mb=vram_mb,
                cost_per_hour=_gpu_cost_lookup(name),
                driver_version=driver, cuda_version=cuda_ver,
            ))
        return gpus
    except Exception:
        return []


def _detect_framework() -> tuple[str, str, bool, str, int, int]:
    """Returns (framework, version, distributed, backend, world_size, local_rank)."""
    # PyTorch
    try:
        import torch
        version = torch.__version__
        dist = False
        backend = ""
        world_size = 1
        local_rank = 0
        try:
            import torch.distributed as tdist
            if tdist.is_available() and tdist.is_initialized():
                dist = True
                backend = tdist.get_backend()
                world_size = tdist.get_world_size()
                local_rank = tdist.get_rank()
        except Exception:
            pass
        # Also check env vars (torchrun / deepspeed)
        if not dist:
            ws = os.getenv("WORLD_SIZE") or os.getenv("OMPI_COMM_WORLD_SIZE")
            if ws and int(ws) > 1:
                dist = True
                world_size = int(ws)
                local_rank = int(os.getenv("LOCAL_RANK", "0"))
        return "pytorch", version, dist, backend, world_size, local_rank
    except ImportError:
        pass
    # TensorFlow
    try:
        import tensorflow as tf
        return "tensorflow", tf.__version__, False, "", 1, 0
    except ImportError:
        pass
    # JAX
    try:
        import jax
        return "jax", jax.__version__, False, "", 1, 0
    except ImportError:
        pass
    return "unknown", "", False, "", 1, 0


def _detect_cloud() -> tuple[str, str]:
    """Returns (provider, instance_type)."""
    # Google Colab
    if "COLAB_GPU" in os.environ or os.path.exists("/content"):
        return "colab", "colab-runtime"
    # Kaggle
    if "KAGGLE_KERNEL_RUN_TYPE" in os.environ:
        return "kaggle", "kaggle-kernel"
    # RunPod
    if "RUNPOD_POD_ID" in os.environ:
        return "runpod", os.getenv("RUNPOD_GPU_COUNT", "unknown")
    # Lambda Labs
    if "LAMBDA_TASK_ROOT" in os.environ or os.path.exists("/etc/lambda"):
        return "lambda", "lambda-gpu"
    # AWS EC2 — try metadata endpoint with short timeout
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-type",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "5"},
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            itype = r.read().decode()
        return "aws", itype
    except Exception:
        pass
    # GCP
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/machine-type",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            mt = r.read().decode().split("/")[-1]
        return "gcp", mt
    except Exception:
        pass
    # Azure
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://169.254.169.254/metadata/instance?api-version=2021-02-01",
            headers={"Metadata": "true"},
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            import json
            data = json.loads(r.read())
            vm = data.get("compute", {}).get("vmSize", "unknown")
        return "azure", vm
    except Exception:
        pass
    return "local", "unknown"


def _detect_system() -> tuple[int, float]:
    try:
        import psutil
        return psutil.cpu_count(logical=True), psutil.virtual_memory().total / 1024 ** 2
    except ImportError:
        return os.cpu_count() or 1, 0.0


def detect_environment() -> EnvironmentInfo:
    """Run all detectors and return a populated EnvironmentInfo."""
    gpus = _detect_gpus()
    fw, fv, dist, backend, ws, lr = _detect_framework()
    cloud, itype = _detect_cloud()
    cpus, ram = _detect_system()

    cuda_available = False
    cuda_version = ""
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            cuda_version = torch.version.cuda or ""
    except ImportError:
        if gpus:
            cuda_available = True
            cuda_version = gpus[0].cuda_version if gpus else ""

    total_cost = sum(g.cost_per_hour for g in gpus) or 0.10

    return EnvironmentInfo(
        gpus=gpus,
        cpu_count=cpus,
        total_ram_mb=ram,
        framework=fw,
        framework_version=fv,
        distributed=dist,
        distributed_backend=backend,
        world_size=ws,
        local_rank=lr,
        cloud_provider=cloud,
        instance_type=itype,
        hostname=socket.gethostname(),
        python_version=sys.version.split()[0],
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        estimated_cost_per_hour=total_cost,
    )
