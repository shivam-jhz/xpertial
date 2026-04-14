"""
MLObs Agent Configuration
--------------------------
All tuneable knobs for the local collector agent.
Values can be overridden by environment variables or passed directly
to TrainingRun at init time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentConfig:
    # ── Backend ────────────────────────────────────────────────────────────
    backend_url: str = os.getenv("MLOBS_BACKEND_URL", "http://localhost:8000")
    api_key: Optional[str] = os.getenv("MLOBS_API_KEY", None)

    # ── Collection intervals (seconds) ─────────────────────────────────────
    gpu_poll_interval: float = float(os.getenv("MLOBS_GPU_POLL_INTERVAL", "2.0"))
    system_poll_interval: float = float(os.getenv("MLOBS_SYS_POLL_INTERVAL", "5.0"))
    ship_interval: float = float(os.getenv("MLOBS_SHIP_INTERVAL", "3.0"))

    # ── Cost engine ────────────────────────────────────────────────────────
    # GPU SKU name → $/hr  (user can override at runtime)
    gpu_cost_per_hour: float = float(os.getenv("MLOBS_GPU_COST_HR", "3.50"))
    cpu_cost_per_hour: float = float(os.getenv("MLOBS_CPU_COST_HR", "0.10"))

    # ── Alert thresholds ───────────────────────────────────────────────────
    gpu_util_warn_pct: float = 30.0       # warn if GPU util < this
    gpu_util_crit_pct: float = 10.0       # critical if GPU util < this
    gpu_temp_warn_c: float = 80.0
    gpu_temp_crit_c: float = 90.0
    vram_warn_pct: float = 90.0
    vram_crit_pct: float = 98.0
    stall_warn_secs: float = 60.0         # no step for this long → warn
    stall_crit_secs: float = 180.0        # no step for this long → critical

    # ── Reliability ────────────────────────────────────────────────────────
    max_queue_size: int = 2_000           # in-memory buffer before dropping
    http_timeout_secs: float = 5.0
    http_retries: int = 3
    retry_backoff_factor: float = 0.5

    # ── Logging ────────────────────────────────────────────────────────────
    log_level: str = os.getenv("MLOBS_LOG_LEVEL", "INFO")


# Singleton used by default across the package
DEFAULT_CONFIG = AgentConfig()
