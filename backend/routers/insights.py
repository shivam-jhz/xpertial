"""
XPERTIAL – /api/v1/insights and /api/v1/compare routes
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    EfficiencySnapshot, Insight, Run, RunEnvironment,
    StepMetric, GpuMetric,
)
from ..services.comparator import RunSummary, compare_runs
from ..services.insights_engine import generate_insights, InsightCard

router = APIRouter(prefix="/api/v1", tags=["insights"])


# ── Insights for a run ────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/insights")
async def get_insights(
    run_id: str,
    include_dismissed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Return latest insight cards for a run."""
    q = select(Insight).where(Insight.run_id == run_id)
    if not include_dismissed:
        q = q.where(Insight.dismissed == False)
    q = q.order_by(desc(Insight.created_at)).limit(20)
    rows = (await db.execute(q)).scalars().all()

    # Deduplicate by insight_id – keep most recent per id
    seen = {}
    for r in rows:
        if r.insight_id not in seen:
            seen[r.insight_id] = r

    return [_insight_out(r) for r in seen.values()]


@router.patch("/runs/{run_id}/insights/{insight_id}/dismiss")
async def dismiss_insight(run_id: str, insight_id: str, db: AsyncSession = Depends(get_db)):
    q = select(Insight).where(Insight.run_id == run_id, Insight.insight_id == insight_id)
    row = (await db.execute(q)).scalars().first()
    if not row:
        raise HTTPException(404, "Insight not found")
    row.dismissed = True
    await db.flush()
    return {"ok": True}


# ── Efficiency snapshots ──────────────────────────────────────────────────────

@router.get("/runs/{run_id}/efficiency")
async def get_efficiency_history(
    run_id: str,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(EfficiencySnapshot)
        .where(EfficiencySnapshot.run_id == run_id)
        .order_by(EfficiencySnapshot.step)
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [_eff_out(r) for r in rows]


@router.get("/runs/{run_id}/efficiency/latest")
async def get_latest_efficiency(run_id: str, db: AsyncSession = Depends(get_db)):
    q = (
        select(EfficiencySnapshot)
        .where(EfficiencySnapshot.run_id == run_id)
        .order_by(desc(EfficiencySnapshot.step))
        .limit(1)
    )
    row = (await db.execute(q)).scalars().first()
    if not row:
        raise HTTPException(404, "No efficiency data yet")
    return _eff_out(row)


# ── Run comparison ────────────────────────────────────────────────────────────

@router.post("/compare")
async def compare_run_ids(
    body: dict,  # {"run_ids": ["...", "..."]}
    db: AsyncSession = Depends(get_db),
):
    run_ids: List[str] = body.get("run_ids", [])
    if len(run_ids) < 2 or len(run_ids) > 8:
        raise HTTPException(400, "Provide 2–8 run IDs")

    summaries = []
    for rid in run_ids:
        run = (await db.execute(select(Run).where(Run.run_id == rid))).scalar_one_or_none()
        if not run:
            raise HTTPException(404, f"Run {rid} not found")

        # Latest efficiency snapshot
        eff = (await db.execute(
            select(EfficiencySnapshot)
            .where(EfficiencySnapshot.run_id == rid)
            .order_by(desc(EfficiencySnapshot.step))
            .limit(1)
        )).scalars().first()

        # Avg GPU util
        avg_util_row = (await db.execute(
            select(func.avg(GpuMetric.utilization_pct))
            .where(GpuMetric.run_id == rid)
        )).scalar()

        # Duration
        duration_hrs = 0.0
        if run.started_at and run.ended_at:
            duration_hrs = (run.ended_at - run.started_at).total_seconds() / 3600
        elif run.started_at:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            duration_hrs = (now - run.started_at).total_seconds() / 3600

        summaries.append(RunSummary(
            run_id=run.run_id,
            name=run.name,
            total_cost_usd=run.total_cost_usd or 0.0,
            total_steps=run.total_steps or 0,
            final_loss=run.final_loss,
            avg_gpu_util=float(avg_util_row or 0),
            avg_gpu_idle=eff.gpu_idle_pct if eff else 0.0,
            avg_step_time_ms=eff.avg_step_time_ms if eff else 0.0,
            efficiency_score=run.efficiency_score or 0.0,
            efficiency_grade=run.efficiency_grade or "?",
            wasted_cost_usd=eff.wasted_cost_usd if eff else 0.0,
            duration_hrs=duration_hrs,
            bottleneck=eff.bottleneck if eff else "unknown",
        ))

    result = compare_runs(summaries)
    return result.to_dict()


# ── Environment info ──────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/environment")
async def get_environment(run_id: str, db: AsyncSession = Depends(get_db)):
    env = (await db.execute(
        select(RunEnvironment).where(RunEnvironment.run_id == run_id)
    )).scalar_one_or_none()
    if not env:
        raise HTTPException(404, "No environment data for this run")
    return {
        "framework": env.framework,
        "framework_version": env.framework_version,
        "cloud_provider": env.cloud_provider,
        "instance_type": env.instance_type,
        "num_gpus": env.num_gpus,
        "gpu_names": env.gpu_names,
        "python_version": env.python_version,
        "cuda_version": env.cuda_version,
        "distributed": env.distributed,
        "world_size": env.world_size,
        "hostname": env.hostname,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insight_out(r: Insight) -> dict:
    return {
        "id": r.insight_id,
        "db_id": r.id,
        "category": r.category,
        "severity": r.severity,
        "title": r.title,
        "body": r.body,
        "action": r.action,
        "metric_ref": r.metric_ref,
        "metric_unit": r.metric_unit,
        "dismissed": r.dismissed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _eff_out(r: EfficiencySnapshot) -> dict:
    return {
        "step": r.step,
        "time": r.time.isoformat() if r.time else None,
        "gpu_idle_pct": r.gpu_idle_pct,
        "wasted_cost_usd": r.wasted_cost_usd,
        "wasted_cost_inr": r.wasted_cost_inr,
        "bottleneck": r.bottleneck,
        "bottleneck_detail": r.bottleneck_detail,
        "avg_step_time_ms": r.avg_step_time_ms,
        "step_time_cv": r.step_time_cv,
        "loss_trend": r.loss_trend,
        "stall_detected": r.stall_detected,
        "efficiency_score": r.efficiency_score,
        "efficiency_grade": r.efficiency_grade,
        "loss_plateau_steps": r.loss_plateau_steps,
    }
