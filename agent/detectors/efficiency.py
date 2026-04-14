"""
XPERTIAL – Efficiency Analyzer
---------------------------------
Runs on the agent side, computing lightweight signals from raw metrics
before they're shipped.  Produces EfficiencySnapshot every N steps.

Signals computed:
  - gpu_idle_pct         : rolling average of (100 - utilisation)
  - wasted_cost_usd      : idle fraction × gpu_cost_per_hour × elapsed
  - bottleneck_hint      : data_pipeline | cpu_bound | gpu_bound | io_bound | normal
  - step_time_cv         : coefficient of variation of step times (instability proxy)
  - loss_plateau_steps   : how many consecutive steps without improvement
  - stall_detected       : bool – loss stuck beyond threshold
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Deque, List, Optional


@dataclass
class EfficiencySnapshot:
    # GPU waste
    gpu_idle_pct: float            # 0-100
    wasted_cost_usd: float         # money lost to idle GPUs so far
    wasted_cost_inr: float         # INR equivalent (1 USD = 83 INR approx)

    # Bottleneck
    bottleneck: str                # data_pipeline | cpu_bound | memory_bound | normal
    bottleneck_detail: str         # human-readable explanation

    # Throughput
    avg_step_time_ms: float
    step_time_cv: float            # coefficient of variation (0 = stable)
    avg_tokens_per_sec: float

    # Loss stability
    loss_plateau_steps: int        # consecutive non-improving steps
    loss_trend: str                # improving | plateau | diverging
    stall_detected: bool

    # Derived
    efficiency_score: float        # 0–100 composite score
    efficiency_grade: str          # A B C D F

    def to_dict(self) -> dict:
        return asdict(self)


INR_PER_USD = 83.0
_PLATEAU_THRESHOLD = 0.001          # relative improvement < 0.1% = plateau


class EfficiencyAnalyzer:
    """
    Maintains rolling windows over the last N steps and emits
    EfficiencySnapshot objects on demand.
    """

    def __init__(self, window: int = 50, gpu_cost_per_hour: float = 3.50):
        self.window = window
        self.gpu_cost_per_hour = gpu_cost_per_hour

        self._gpu_utils: Deque[float] = deque(maxlen=window)
        self._step_times: Deque[float] = deque(maxlen=window)
        self._cpu_utils: Deque[float] = deque(maxlen=window)
        self._loss_history: Deque[float] = deque(maxlen=window * 4)
        self._tps_history: Deque[float] = deque(maxlen=window)

        self._total_elapsed_hrs: float = 0.0
        self._plateau_steps: int = 0
        self._best_loss: Optional[float] = None

    # ── Feed methods ─────────────────────────────────────────────────────

    def push_gpu(self, util_pct: float):
        self._gpu_utils.append(util_pct)

    def push_step(self, step_time_ms: float, cpu_util: float, tokens_per_sec: Optional[float]):
        self._step_times.append(step_time_ms)
        self._cpu_utils.append(cpu_util)
        if tokens_per_sec is not None:
            self._tps_history.append(tokens_per_sec)

    def push_loss(self, loss: float):
        if math.isnan(loss) or math.isinf(loss):
            return
        self._loss_history.append(loss)
        if self._best_loss is None or loss < self._best_loss * (1 - _PLATEAU_THRESHOLD):
            self._best_loss = loss
            self._plateau_steps = 0
        else:
            self._plateau_steps += 1

    def advance_time(self, delta_hrs: float):
        self._total_elapsed_hrs += delta_hrs

    # ── Snapshot ─────────────────────────────────────────────────────────

    def snapshot(self) -> EfficiencySnapshot:
        gpu_idle = self._gpu_idle_pct()
        wasted_usd = self._wasted_cost(gpu_idle)
        bottleneck, detail = self._detect_bottleneck()
        avg_step = statistics.mean(self._step_times) if self._step_times else 0.0
        cv = self._step_time_cv()
        avg_tps = statistics.mean(self._tps_history) if self._tps_history else 0.0
        loss_trend = self._loss_trend()
        stall = self._plateau_steps >= 30 and len(self._loss_history) >= 30
        score = self._efficiency_score(gpu_idle, cv, stall, bottleneck)
        grade = _score_to_grade(score)

        return EfficiencySnapshot(
            gpu_idle_pct=round(gpu_idle, 2),
            wasted_cost_usd=round(wasted_usd, 4),
            wasted_cost_inr=round(wasted_usd * INR_PER_USD, 2),
            bottleneck=bottleneck,
            bottleneck_detail=detail,
            avg_step_time_ms=round(avg_step, 2),
            step_time_cv=round(cv, 4),
            avg_tokens_per_sec=round(avg_tps, 1),
            loss_plateau_steps=self._plateau_steps,
            loss_trend=loss_trend,
            stall_detected=stall,
            efficiency_score=round(score, 1),
            efficiency_grade=grade,
        )

    # ── Private computation ───────────────────────────────────────────────

    def _gpu_idle_pct(self) -> float:
        if not self._gpu_utils:
            return 0.0
        return max(0.0, 100.0 - statistics.mean(self._gpu_utils))

    def _wasted_cost(self, idle_pct: float) -> float:
        idle_fraction = idle_pct / 100.0
        return idle_fraction * self.gpu_cost_per_hour * self._total_elapsed_hrs

    def _detect_bottleneck(self) -> tuple[str, str]:
        gpu_idle = self._gpu_idle_pct()
        avg_cpu = statistics.mean(self._cpu_utils) if self._cpu_utils else 0.0
        cv = self._step_time_cv()

        # Data pipeline: GPU waiting for data → high idle, variable step time
        if gpu_idle > 40 and cv > 0.25:
            return (
                "data_pipeline",
                f"GPU idle {gpu_idle:.0f}% with high step-time variance ({cv:.2f} CV). "
                "Data loading is likely the bottleneck — increase num_workers or prefetch.",
            )
        # CPU saturation: CPU pegged while GPU waits
        if avg_cpu > 85 and gpu_idle > 25:
            return (
                "cpu_bound",
                f"CPU at {avg_cpu:.0f}% while GPU is idle {gpu_idle:.0f}%. "
                "CPU preprocessing is blocking GPU. Use pin_memory=True and more workers.",
            )
        # IO bound: high step time variance but normal CPU/GPU
        if cv > 0.35:
            return (
                "io_bound",
                f"Step time is highly irregular (CV={cv:.2f}). "
                "Likely slow disk I/O or network storage. Move dataset to local NVMe.",
            )
        # GPU underutilised but no clear cause
        if gpu_idle > 30:
            return (
                "gpu_underutilized",
                f"GPU idle {gpu_idle:.0f}% of the time. "
                "Increase batch size or check for synchronization bottlenecks.",
            )
        return ("normal", "GPU is well-utilized. No major bottleneck detected.")

    def _step_time_cv(self) -> float:
        if len(self._step_times) < 4:
            return 0.0
        try:
            mu = statistics.mean(self._step_times)
            sigma = statistics.stdev(self._step_times)
            return sigma / mu if mu > 0 else 0.0
        except statistics.StatisticsError:
            return 0.0

    def _loss_trend(self) -> str:
        if len(self._loss_history) < 10:
            return "unknown"
        recent = list(self._loss_history)[-10:]
        older = list(self._loss_history)[-20:-10] if len(self._loss_history) >= 20 else recent
        avg_recent = statistics.mean(recent)
        avg_older = statistics.mean(older)
        delta = (avg_older - avg_recent) / (avg_older + 1e-9)
        if self._plateau_steps >= 20:
            return "plateau"
        if delta < -0.02:
            return "diverging"
        if delta > 0.005:
            return "improving"
        return "plateau"

    def _efficiency_score(self, gpu_idle: float, cv: float, stall: bool, bottleneck: str) -> float:
        score = 100.0
        score -= gpu_idle * 0.7          # penalise idle GPU heavily
        score -= min(cv * 40, 20)        # penalise step-time instability
        if stall:
            score -= 20
        if bottleneck != "normal":
            score -= 10
        return max(0.0, min(100.0, score))


def _score_to_grade(score: float) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"
