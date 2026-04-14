"""
XPERTIAL – /api/v1/ingest routes (v2)
Adds: efficiency snapshot persistence, insight generation, environment storage.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    Alert, EfficiencySnapshot, GpuMetric, Insight,
    Run, RunEnvironment, RunStatus, StepMetric, SystemMetric,
)
from ..services.alert_engine import AlertThresholds, evaluate_gpu_metrics, evaluate_step_events
from ..services.cost_engine import compute_cost
from ..services.insights_engine import generate_insights
from ..ws_manager import manager

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

_run_cache: Dict[str, Dict[str, Any]] = {}
_thresholds = AlertThresholds()


def _ts(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


# ── GPU + System metrics ──────────────────────────────────────────────────────

@router.post("/metrics", status_code=204)
async def ingest_metrics(req: dict, db: AsyncSession = Depends(get_db)):
    run_id = req.get("run_id")
    run = await _get_run(run_id, db)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    gpu_rows, sys_rows = [], []
    all_gpu_snaps = []

    for batch in req.get("batches", []):
        for gpu in batch.get("gpus", []):
            all_gpu_snaps.append(gpu)
            gpu_rows.append(GpuMetric(
                run_id=run_id, time=_ts(gpu["timestamp"]),
                device_index=gpu.get("device_index", 0),
                device_name=gpu.get("name"),
                utilization_pct=gpu.get("utilization_pct"),
                memory_used_mb=gpu.get("memory_used_mb"),
                memory_total_mb=gpu.get("memory_total_mb"),
                memory_pct=gpu.get("memory_pct"),
                temperature_c=gpu.get("temperature_c"),
                power_draw_w=gpu.get("power_draw_w"),
                power_limit_w=gpu.get("power_limit_w"),
                fan_speed_pct=gpu.get("fan_speed_pct"),
                sm_clock_mhz=gpu.get("sm_clock_mhz"),
                mem_clock_mhz=gpu.get("mem_clock_mhz"),
            ))

        sys = batch.get("system", {})
        if sys:
            sys_rows.append(SystemMetric(
                run_id=run_id, time=_ts(sys.get("timestamp", time.time())),
                cpu_util_pct=sys.get("cpu_util_pct"),
                ram_used_mb=sys.get("ram_used_mb"),
                ram_total_mb=sys.get("ram_total_mb"),
                ram_pct=sys.get("ram_pct"),
                swap_used_mb=sys.get("swap_used_mb"),
                disk_read_mb_s=sys.get("disk_read_mb_s"),
                disk_write_mb_s=sys.get("disk_write_mb_s"),
                net_sent_mb_s=sys.get("net_sent_mb_s"),
                net_recv_mb_s=sys.get("net_recv_mb_s"),
                load_avg_1m=sys.get("load_avg_1m"),
            ))

    db.add_all(gpu_rows + sys_rows)

    # Alerts
    alert_events = evaluate_gpu_metrics(run_id, all_gpu_snaps, _thresholds)
    alert_rows = [Alert(run_id=run_id, level=ae.level, alert_type=ae.alert_type,
                        message=ae.message, details=ae.details) for ae in alert_events]
    db.add_all(alert_rows)

    await db.flush()

    # Cost + WS push
    cache = _run_cache.get(run_id, {})
    elapsed = time.time() - cache.get("started_at", time.time())
    num_gpus = len(set(g.get("device_index", 0) for g in all_gpu_snaps))
    gpu_utils = [g.get("utilization_pct", 0) for g in all_gpu_snaps]
    cost = compute_cost(
        elapsed_secs=elapsed,
        gpu_cost_per_hour=run.gpu_cost_per_hour,
        cpu_cost_per_hour=run.cpu_cost_per_hour,
        num_gpus=max(num_gpus, 1),
        current_step=cache.get("last_step"),
        gpu_utils=gpu_utils,
    )
    if run_id in _run_cache:
        _run_cache[run_id]["num_gpus"] = num_gpus

    await manager.broadcast(run_id, {
        "type": "metrics",
        "run_id": run_id,
        "ts": time.time(),
        "gpus": all_gpu_snaps[-len(req.get("batches", [{}])[-1].get("gpus", [])):] if req.get("batches") else [],
        "system": req.get("batches", [{}])[-1].get("system"),
        "cost": {
            "elapsed_secs": cost.elapsed_secs,
            "burn_rate_per_hour": cost.burn_rate_per_hour,
            "cost_so_far_usd": cost.cost_so_far_usd,
            "projected_total_usd": cost.projected_total_usd,
            "num_gpus": cost.num_gpus,
        },
        "alerts": [{"level": a.level.value, "message": a.message} for a in alert_rows],
    })
    return


# ── Step events ───────────────────────────────────────────────────────────────

@router.post("/steps", status_code=204)
async def ingest_steps(req: dict, db: AsyncSession = Depends(get_db)):
    run_id = req.get("run_id")
    run = await _get_run(run_id, db)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    events = req.get("events", [])
    step_rows = [StepMetric(
        run_id=run_id, time=_ts(ev.get("timestamp", time.time())),
        step=ev.get("step", 0), epoch=ev.get("epoch"),
        loss=ev.get("loss"), step_time_ms=ev.get("step_time_ms"),
        samples_per_sec=ev.get("samples_per_sec"),
        tokens_per_sec=ev.get("tokens_per_sec"),
        grad_norm=ev.get("grad_norm"),
        learning_rate=ev.get("learning_rate"),
        has_nan=ev.get("has_nan", False),
        has_inf=ev.get("has_inf", False),
    ) for ev in events]
    db.add_all(step_rows)

    alert_events = evaluate_step_events(run_id, events)
    alert_rows = [Alert(run_id=run_id, level=ae.level, alert_type=ae.alert_type,
                        message=ae.message, details=ae.details) for ae in alert_events]
    db.add_all(alert_rows)

    if events:
        latest = max(events, key=lambda e: e.get("step", 0))
        _run_cache.setdefault(run_id, {}).update({
            "last_step": latest.get("step"),
            "last_step_time": latest.get("timestamp"),
        })

    await db.flush()
    if events:
        latest = max(events, key=lambda e: e.get("step", 0))
        await manager.broadcast(run_id, {
            "type": "step",
            "run_id": run_id,
            "ts": time.time(),
            "step": {
                "step": latest.get("step"),
                "loss": latest.get("loss"),
                "step_time_ms": latest.get("step_time_ms"),
                "tokens_per_sec": latest.get("tokens_per_sec"),
                "learning_rate": latest.get("learning_rate"),
            },
            "alerts": [{"level": a.level.value, "message": a.message} for a in alert_rows],
        })
    return


# ── Efficiency snapshot ───────────────────────────────────────────────────────

@router.post("/efficiency", status_code=204)
async def ingest_efficiency(req: dict, db: AsyncSession = Depends(get_db)):
    """
    Receives an EfficiencyEvent from the agent, persists it,
    regenerates insight cards, and broadcasts them.
    """
    run_id = req.get("run_id")
    run = await _get_run(run_id, db)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    eff = req.get("efficiency", {})
    ckpt = req.get("checkpoint", {})
    step = req.get("step", 0)

    snap = EfficiencySnapshot(
        run_id=run_id,
        step=step,
        gpu_idle_pct=eff.get("gpu_idle_pct"),
        wasted_cost_usd=eff.get("wasted_cost_usd"),
        wasted_cost_inr=eff.get("wasted_cost_inr"),
        bottleneck=eff.get("bottleneck"),
        bottleneck_detail=eff.get("bottleneck_detail"),
        avg_step_time_ms=eff.get("avg_step_time_ms"),
        step_time_cv=eff.get("step_time_cv"),
        avg_tokens_per_sec=eff.get("avg_tokens_per_sec"),
        loss_plateau_steps=eff.get("loss_plateau_steps"),
        loss_trend=eff.get("loss_trend"),
        stall_detected=eff.get("stall_detected", False),
        efficiency_score=eff.get("efficiency_score"),
        efficiency_grade=eff.get("efficiency_grade"),
        last_checkpoint_step=ckpt.get("last_step") if ckpt else None,
        checkpoint_save_failed=ckpt.get("save_failed", False) if ckpt else False,
    )
    db.add(snap)

    # Update run summary fields
    run.efficiency_score = eff.get("efficiency_score")
    run.efficiency_grade = eff.get("efficiency_grade")
    run.wasted_cost_usd = eff.get("wasted_cost_usd")
    run.bottleneck = eff.get("bottleneck")
    if ckpt and ckpt.get("last_step"):
        run.last_checkpoint_step = ckpt["last_step"]
        run.last_checkpoint_path = ckpt.get("last_path")

    # Generate insight cards
    cache = _run_cache.get(run_id, {})
    elapsed = time.time() - cache.get("started_at", time.time())
    burn_rate = run.gpu_cost_per_hour * max(cache.get("num_gpus", 1), 1)
    cost_so_far = burn_rate * elapsed / 3600

    total_steps = run.total_steps_planned
    projected = None
    if total_steps and step > 0 and cost_so_far > 0:
        projected = cost_so_far / step * total_steps

    cards = generate_insights(
        gpu_idle_pct=eff.get("gpu_idle_pct", 0),
        wasted_cost_usd=eff.get("wasted_cost_usd", 0),
        wasted_cost_inr=eff.get("wasted_cost_inr", 0),
        bottleneck=eff.get("bottleneck", "normal"),
        bottleneck_detail=eff.get("bottleneck_detail", ""),
        loss_trend=eff.get("loss_trend", "unknown"),
        stall_detected=eff.get("stall_detected", False),
        loss_plateau_steps=eff.get("loss_plateau_steps", 0),
        efficiency_score=eff.get("efficiency_score", 0),
        efficiency_grade=eff.get("efficiency_grade", "?"),
        step_time_cv=eff.get("step_time_cv", 0),
        avg_gpu_util=100 - eff.get("gpu_idle_pct", 0),
        cost_so_far_usd=cost_so_far,
        projected_total_usd=projected,
        burn_rate_usd_hr=burn_rate,
        current_step=step,
        total_steps=total_steps,
        num_gpus=cache.get("num_gpus", 1),
        gpu_cost_per_hour=run.gpu_cost_per_hour,
    )

    # Upsert insights (replace same insight_id for this run)
    for card in cards:
        existing = (await db.execute(
            select(Insight).where(
                Insight.run_id == run_id,
                Insight.insight_id == card.id,
            )
        )).scalar_one_or_none()

        if existing:
            existing.title = card.title
            existing.body = card.body
            existing.action = card.action
            existing.severity = card.severity
            existing.metric_ref = card.metric_ref
        else:
            db.add(Insight(
                run_id=run_id,
                insight_id=card.id,
                category=card.category,
                severity=card.severity,
                title=card.title,
                body=card.body,
                action=card.action,
                metric_ref=card.metric_ref,
                metric_unit=card.metric_unit,
            ))

    await db.flush()

    # Broadcast insights to WS clients
    await manager.broadcast(run_id, {
        "type": "insights",
        "run_id": run_id,
        "ts": time.time(),
        "efficiency": eff,
        "insights": [c.to_dict() for c in cards],
    })
    return


# ── Checkpoint notification ───────────────────────────────────────────────────

@router.post("/runs/{run_id}/checkpoint", status_code=204)
async def ingest_checkpoint(run_id: str, req: dict, db: AsyncSession = Depends(get_db)):
    run = await _get_run(run_id, db)
    if not run:
        raise HTTPException(404)
    if req.get("success", True):
        run.last_checkpoint_step = req.get("step")
        run.last_checkpoint_path = req.get("path")
    await db.flush()
    return


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_run(run_id: str, db: AsyncSession):
    r = await db.execute(select(Run).where(Run.run_id == run_id))
    return r.scalar_one_or_none()


def register_run_in_cache(run_id, started_at, gpu_cost_hr, cpu_cost_hr):
    _run_cache[run_id] = {
        "started_at": started_at,
        "gpu_cost_hr": gpu_cost_hr,
        "cpu_cost_hr": cpu_cost_hr,
        "last_step": None,
        "last_step_time": None,
        "num_gpus": 1,
    }
