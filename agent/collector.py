"""
MLObs Metrics Collector
------------------------
Polls GPU metrics (via pynvml / NVML) and system metrics (via psutil)
on configurable intervals. Results are placed onto a thread-safe queue
for the shipper to consume.

Gracefully degrades when no NVIDIA GPU is present (CPU-only mode).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import psutil

try:
    import pynvml

    pynvml.nvmlInit()
    _NVML_AVAILABLE = True
except Exception:
    _NVML_AVAILABLE = False

from .config import AgentConfig, DEFAULT_CONFIG

log = logging.getLogger("mlobs.collector")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GpuSnapshot:
    device_index: int
    name: str
    utilization_pct: float          # 0-100
    memory_used_mb: float
    memory_total_mb: float
    memory_pct: float               # derived
    temperature_c: float
    power_draw_w: float
    power_limit_w: float
    fan_speed_pct: Optional[float]  # not available on all GPUs
    sm_clock_mhz: Optional[int]
    mem_clock_mhz: Optional[int]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SystemSnapshot:
    cpu_util_pct: float
    ram_used_mb: float
    ram_total_mb: float
    ram_pct: float
    swap_used_mb: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    net_sent_mb_s: float
    net_recv_mb_s: float
    load_avg_1m: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetricsBatch:
    run_id: str
    gpus: List[GpuSnapshot]
    system: SystemSnapshot
    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "collected_at": self.collected_at,
            "gpus": [g.to_dict() for g in self.gpus],
            "system": self.system.to_dict(),
        }


# ── NVML helpers ──────────────────────────────────────────────────────────────

def _safe_nvml(fn, default=0.0):
    """Call an NVML function and return default on failure."""
    try:
        return fn()
    except pynvml.NVMLError:
        return default


def _collect_gpu(handle, index: int) -> GpuSnapshot:
    name = _safe_nvml(lambda: pynvml.nvmlDeviceGetName(handle).decode(), "Unknown GPU")
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    temp = _safe_nvml(lambda: pynvml.nvmlDeviceGetTemperature(
        handle, pynvml.NVML_TEMPERATURE_GPU
    ))
    power = _safe_nvml(lambda: pynvml.nvmlDeviceGetPowerUsage(handle) / 1_000.0)  # mW→W
    power_limit = _safe_nvml(lambda: pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1_000.0)
    fan = _safe_nvml(lambda: float(pynvml.nvmlDeviceGetFanSpeed(handle)), None)
    sm_clk = _safe_nvml(lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM), None)
    mem_clk = _safe_nvml(lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM), None)

    used_mb = mem_info.used / 1024 ** 2
    total_mb = mem_info.total / 1024 ** 2

    return GpuSnapshot(
        device_index=index,
        name=name,
        utilization_pct=float(util.gpu),
        memory_used_mb=used_mb,
        memory_total_mb=total_mb,
        memory_pct=round(used_mb / total_mb * 100, 2) if total_mb > 0 else 0.0,
        temperature_c=float(temp),
        power_draw_w=float(power),
        power_limit_w=float(power_limit),
        fan_speed_pct=float(fan) if fan is not None else None,
        sm_clock_mhz=int(sm_clk) if sm_clk is not None else None,
        mem_clock_mhz=int(mem_clk) if mem_clk is not None else None,
    )


# ── System helpers ─────────────────────────────────────────────────────────────

class _DeltaCounter:
    """Tracks per-call deltas for cumulative psutil counters."""

    def __init__(self):
        self._last = {}
        self._last_ts = {}

    def delta_per_sec(self, key: str, value: float) -> float:
        now = time.monotonic()
        last_val = self._last.get(key, value)
        last_ts = self._last_ts.get(key, now)
        dt = now - last_ts or 1e-6
        self._last[key] = value
        self._last_ts[key] = now
        return max(0.0, (value - last_val) / dt)


_delta = _DeltaCounter()


def _collect_system() -> SystemSnapshot:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    io = psutil.disk_io_counters()
    net = psutil.net_io_counters()
    load = psutil.getloadavg()

    disk_r = _delta.delta_per_sec("disk_r", io.read_bytes if io else 0) / 1024 ** 2
    disk_w = _delta.delta_per_sec("disk_w", io.write_bytes if io else 0) / 1024 ** 2
    net_s = _delta.delta_per_sec("net_s", net.bytes_sent if net else 0) / 1024 ** 2
    net_r = _delta.delta_per_sec("net_r", net.bytes_recv if net else 0) / 1024 ** 2

    return SystemSnapshot(
        cpu_util_pct=psutil.cpu_percent(interval=None),
        ram_used_mb=vm.used / 1024 ** 2,
        ram_total_mb=vm.total / 1024 ** 2,
        ram_pct=vm.percent,
        swap_used_mb=sw.used / 1024 ** 2,
        disk_read_mb_s=round(disk_r, 3),
        disk_write_mb_s=round(disk_w, 3),
        net_sent_mb_s=round(net_s, 3),
        net_recv_mb_s=round(net_r, 3),
        load_avg_1m=load[0],
    )


# ── Collector thread ──────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Background thread that polls GPU + system metrics and pushes
    MetricsBatch objects onto `queue`.
    """

    def __init__(self, run_id: str, queue, config: AgentConfig = DEFAULT_CONFIG):
        self.run_id = run_id
        self.queue = queue
        self.cfg = config
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mlobs-collector")

        if _NVML_AVAILABLE:
            self._num_gpus = pynvml.nvmlDeviceGetCount()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(self._num_gpus)]
            log.info("NVML initialised – found %d GPU(s)", self._num_gpus)
        else:
            self._num_gpus = 0
            self._handles = []
            log.warning("pynvml unavailable – running in CPU-only mode")

    # ── Public API ────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        log.info("Metrics collector started (run=%s)", self.run_id)

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)
        log.info("Metrics collector stopped")

    # ── Internal ──────────────────────────────────────────────────────────

    def _loop(self):
        # Prime the psutil delta counters
        _collect_system()
        next_sys = time.monotonic()

        while not self._stop.is_set():
            try:
                gpus = self._read_gpus()
                sys_snap = _collect_system() if time.monotonic() >= next_sys else None

                if sys_snap is None:
                    # Need a system snapshot – reuse last or build minimal
                    sys_snap = _collect_system()
                    next_sys = time.monotonic() + self.cfg.system_poll_interval

                batch = MetricsBatch(run_id=self.run_id, gpus=gpus, system=sys_snap)

                if self.queue.qsize() < self.cfg.max_queue_size:
                    self.queue.put_nowait(batch)
                else:
                    log.warning("Collector queue full – dropping batch")

            except Exception:
                log.exception("Collector loop error")

            time.sleep(self.cfg.gpu_poll_interval)

    def _read_gpus(self) -> List[GpuSnapshot]:
        if not _NVML_AVAILABLE:
            return []
        snapshots = []
        for i, handle in enumerate(self._handles):
            try:
                snapshots.append(_collect_gpu(handle, i))
            except Exception:
                log.exception("Failed reading GPU %d", i)
        return snapshots
