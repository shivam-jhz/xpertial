#!/usr/bin/env python3
"""
XPERTIAL CLI
------------
Usage:
    xpertial init           -- verify setup, detect environment, print summary
    xpertial doctor         -- deeper diagnostics
    xpertial runs           -- list recent runs
    xpertial status RUN_ID  -- show live run status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def _banner():
    print("\n  ╔═══════════════════════════════════╗")
    print("  ║   XPERTIAL — Training Intelligence ║")
    print("  ╚═══════════════════════════════════╝\n")


def cmd_init(args):
    """Verify environment and print a configuration summary."""
    _banner()
    print("  Detecting environment…\n")

    from .detectors.environment import detect_environment
    env = detect_environment()

    # GPU summary
    if env.gpus:
        print(f"  ✓ GPUs detected: {len(env.gpus)}")
        for g in env.gpus:
            print(f"      GPU:{g.index}  {g.name}  {g.vram_mb/1024:.1f} GB  ~${g.cost_per_hour:.2f}/hr")
    else:
        print("  ⚠  No NVIDIA GPUs found (CPU-only mode)")

    # Framework
    if env.framework != "unknown":
        print(f"  ✓ Framework: {env.framework} {env.framework_version}")
    else:
        print("  ⚠  No ML framework detected (PyTorch/TF/JAX not installed)")

    # Cloud
    print(f"  ✓ Environment: {env.cloud_provider}  {env.instance_type or '(local)'}")
    print(f"  ✓ Python: {env.python_version}")
    if env.cuda_available:
        print(f"  ✓ CUDA: {env.cuda_version}")
    if env.distributed:
        print(f"  ✓ Distributed: world_size={env.world_size}  backend={env.distributed_backend}")

    print(f"\n  Estimated cost: ${env.estimated_cost_per_hour:.2f}/hr total\n")

    # Check backend reachability
    backend = os.getenv("XPERTIAL_BACKEND_URL", "https://api.xpertial.dev")
    api_key = os.getenv("XPERTIAL_API_KEY", "")
    print(f"  Backend: {backend}")
    try:
        import httpx
        r = httpx.get(f"{backend}/health", timeout=3.0)
        if r.status_code == 200:
            print("  ✓ Backend reachable")
        else:
            print(f"  ✗ Backend returned {r.status_code}")
    except Exception as e:
        print(f"  ✗ Cannot reach backend: {e}")
        print("     → Set XPERTIAL_BACKEND_URL or start backend with: docker-compose up -d")

    print("\n  Quick-start:\n")
    print("    from xpertial import monitor")
    print(f"    monitor.start(api_key='{api_key or 'YOUR_API_KEY'}')\n")


def cmd_doctor(args):
    """Deep diagnostics – checks all dependencies."""
    _banner()
    print("  Running diagnostics…\n")
    checks = [
        ("pynvml",    "GPU monitoring (NVML)"),
        ("psutil",    "System metrics"),
        ("httpx",     "HTTP client"),
        ("torch",     "PyTorch"),
        ("numpy",     "NumPy"),
    ]
    for mod, desc in checks:
        try:
            __import__(mod)
            print(f"  ✓ {mod:<12} {desc}")
        except ImportError:
            print(f"  ✗ {mod:<12} {desc}  →  pip install {mod}")

    print()
    # NVML init test
    try:
        import pynvml
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        print(f"  ✓ NVML init OK  ({n} device(s))")
    except Exception as e:
        print(f"  ✗ NVML init failed: {e}")

    print()


def cmd_runs(args):
    """List recent runs from backend."""
    backend = os.getenv("XPERTIAL_BACKEND_URL", "https://api.xpertial.dev")
    api_key = os.getenv("XPERTIAL_API_KEY", "")
    try:
        import httpx
        r = httpx.get(
            f"{backend}/api/v1/runs?limit=10",
            headers={"X-Api-Key": api_key} if api_key else {},
            timeout=5.0,
        )
        runs = r.json()
        if not runs:
            print("No runs found.")
            return
        print(f"\n{'NAME':<30} {'STATUS':<12} {'COST':>10} {'GRADE':>6}")
        print("─" * 62)
        for run in runs:
            cost = f"${run['total_cost_usd']:.2f}" if run.get("total_cost_usd") else "live"
            grade = run.get("efficiency_grade", "?")
            print(f"{run['name']:<30} {run['status']:<12} {cost:>10} {grade:>6}")
        print()
    except Exception as e:
        print(f"Error: {e}")


def cmd_status(args):
    backend = os.getenv("XPERTIAL_BACKEND_URL", "https://api.xpertial.dev")
    api_key = os.getenv("XPERTIAL_API_KEY", "")
    run_id = args.run_id
    try:
        import httpx
        r = httpx.get(
            f"{backend}/api/v1/runs/{run_id}",
            headers={"X-Api-Key": api_key} if api_key else {},
            timeout=5.0,
        )
        run = r.json()
        print(json.dumps(run, indent=2, default=str))
    except Exception as e:
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(prog="xpertial", description="XPERTIAL CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Verify setup and environment")
    sub.add_parser("doctor", help="Deep dependency diagnostics")
    sub.add_parser("runs", help="List recent runs")
    status_p = sub.add_parser("status", help="Show run status")
    status_p.add_argument("run_id")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "runs":
        cmd_runs(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
