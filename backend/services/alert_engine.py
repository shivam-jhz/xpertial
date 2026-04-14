"""
MLObs Alert Engine
-------------------
Evaluates incoming metrics against configured thresholds and produces
Alert records. Designed to be called synchronously inside the ingest
route so alerts are stored alongside their triggering data.

Alert deduplication: we don't re-fire the same alert type within a
cooldown window to avoid alert storms.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import AlertLevel, AlertType


@dataclass
class AlertEvent:
    level: AlertLevel
    alert_type: AlertType
    message: str
    details: Optional[dict] = None


# Per-run cooldown tracker (in-process; survives restarts via DB in prod)
# Structure: run_id → alert_type → last_fired_epoch
_cooldown: Dict[str, Dict[str, float]] = defaultdict(dict)
COOLDOWN_SECS = 120.0   # minimum seconds between identical alerts per run


def _cooled_down(run_id: str, alert_type: AlertType) -> bool:
    last = _cooldown[run_id].get(alert_type.value, 0.0)
    return (time.time() - last) >= COOLDOWN_SECS


def _mark_fired(run_id: str, alert_type: AlertType):
    _cooldown[run_id][alert_type.value] = time.time()


# ── Public entrypoint ─────────────────────────────────────────────────────────

@dataclass
class AlertThresholds:
    gpu_util_warn: float = 30.0
    gpu_util_crit: float = 10.0
    gpu_temp_warn: float = 80.0
    gpu_temp_crit: float = 90.0
    vram_warn: float = 90.0
    vram_crit: float = 98.0
    stall_warn_secs: float = 60.0
    stall_crit_secs: float = 180.0


def evaluate_gpu_metrics(
    run_id: str,
    gpu_snapshots: list,
    thresholds: AlertThresholds = AlertThresholds(),
) -> List[AlertEvent]:
    alerts: List[AlertEvent] = []

    for gpu in gpu_snapshots:
        idx = gpu.get("device_index", 0)
        name = gpu.get("name", f"GPU:{idx}")

        util = gpu.get("utilization_pct", 100.0)
        temp = gpu.get("temperature_c", 0.0)
        vram_pct = gpu.get("memory_pct", 0.0)

        # ── GPU utilisation ──────────────────────────────────────────────
        if util < thresholds.gpu_util_crit:
            at = AlertType.gpu_util_low
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.critical,
                    alert_type=at,
                    message=f"{name} utilisation critically low: {util:.1f}%",
                    details={"device_index": idx, "utilization_pct": util},
                ))
                _mark_fired(run_id, at)
        elif util < thresholds.gpu_util_warn:
            at = AlertType.gpu_util_low
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.warning,
                    alert_type=at,
                    message=f"{name} utilisation low: {util:.1f}%",
                    details={"device_index": idx, "utilization_pct": util},
                ))
                _mark_fired(run_id, at)

        # ── Temperature ──────────────────────────────────────────────────
        if temp >= thresholds.gpu_temp_crit:
            at = AlertType.gpu_temp_high
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.critical,
                    alert_type=at,
                    message=f"{name} temperature critical: {temp:.0f}°C",
                    details={"device_index": idx, "temperature_c": temp},
                ))
                _mark_fired(run_id, at)
        elif temp >= thresholds.gpu_temp_warn:
            at = AlertType.gpu_temp_high
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.warning,
                    alert_type=at,
                    message=f"{name} temperature high: {temp:.0f}°C",
                    details={"device_index": idx, "temperature_c": temp},
                ))
                _mark_fired(run_id, at)

        # ── VRAM ─────────────────────────────────────────────────────────
        if vram_pct >= thresholds.vram_crit:
            at = AlertType.vram_high
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.critical,
                    alert_type=at,
                    message=f"{name} VRAM critical: {vram_pct:.1f}% used",
                    details={"device_index": idx, "memory_pct": vram_pct},
                ))
                _mark_fired(run_id, at)

            # OOM risk heuristic: >98% is near-OOM territory
            if vram_pct >= 98.0:
                at2 = AlertType.oom
                if _cooled_down(run_id, at2):
                    alerts.append(AlertEvent(
                        level=AlertLevel.critical,
                        alert_type=at2,
                        message=f"{name} near out-of-memory: {vram_pct:.1f}% VRAM used",
                        details={"device_index": idx, "memory_pct": vram_pct},
                    ))
                    _mark_fired(run_id, at2)

        elif vram_pct >= thresholds.vram_warn:
            at = AlertType.vram_high
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.warning,
                    alert_type=at,
                    message=f"{name} VRAM high: {vram_pct:.1f}% used",
                    details={"device_index": idx, "memory_pct": vram_pct},
                ))
                _mark_fired(run_id, at)

    return alerts


def evaluate_step_events(
    run_id: str,
    step_events: list,
) -> List[AlertEvent]:
    alerts: List[AlertEvent] = []

    for event in step_events:
        if event.get("has_nan"):
            at = AlertType.nan_loss
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.critical,
                    alert_type=at,
                    message=f"NaN loss detected at step {event.get('step')}",
                    details={"step": event.get("step")},
                ))
                _mark_fired(run_id, at)

        if event.get("has_inf"):
            at = AlertType.inf_loss
            if _cooled_down(run_id, at):
                alerts.append(AlertEvent(
                    level=AlertLevel.critical,
                    alert_type=at,
                    message=f"Inf loss detected at step {event.get('step')}",
                    details={"step": event.get("step")},
                ))
                _mark_fired(run_id, at)

    return alerts


def evaluate_stall(
    run_id: str,
    last_step_time: Optional[float],
    thresholds: AlertThresholds = AlertThresholds(),
) -> List[AlertEvent]:
    if last_step_time is None:
        return []

    elapsed = time.time() - last_step_time
    alerts: List[AlertEvent] = []

    if elapsed >= thresholds.stall_crit_secs:
        at = AlertType.stall
        if _cooled_down(run_id, at):
            alerts.append(AlertEvent(
                level=AlertLevel.critical,
                alert_type=at,
                message=f"Training stalled – no step for {elapsed:.0f}s",
                details={"elapsed_since_last_step_secs": elapsed},
            ))
            _mark_fired(run_id, at)
    elif elapsed >= thresholds.stall_warn_secs:
        at = AlertType.stall
        if _cooled_down(run_id, at):
            alerts.append(AlertEvent(
                level=AlertLevel.warning,
                alert_type=at,
                message=f"Training may be stalled – no step for {elapsed:.0f}s",
                details={"elapsed_since_last_step_secs": elapsed},
            ))
            _mark_fired(run_id, at)

    return alerts
