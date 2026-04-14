"""
MLObs – /api/v1/runs routes
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Alert, GpuMetric, Run, RunStatus, StepMetric, SystemMetric
from ..routers.ingest import register_run_in_cache
from ..schemas import (
    AlertOut,
    GpuTimeSeriesPoint,
    RunCreate,
    RunOut,
    RunUpdate,
    StepTimeSeriesPoint,
)

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post("", response_model=RunOut, status_code=201)
async def create_run(body: RunCreate, db: AsyncSession = Depends(get_db)):
    started = datetime.fromtimestamp(body.started_at, tz=timezone.utc)
    run = Run(
        run_id=body.run_id,
        name=body.name,
        tags=body.tags,
        gpu_cost_per_hour=body.gpu_cost_per_hour,
        cpu_cost_per_hour=body.cpu_cost_per_hour,
        started_at=started,
        status=RunStatus.running,
    )
    db.add(run)
    await db.flush()
    register_run_in_cache(body.run_id, body.started_at, body.gpu_cost_per_hour, body.cpu_cost_per_hour)
    return RunOut.model_validate(run)


@router.get("", response_model=List[RunOut])
async def list_runs(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Run).order_by(desc(Run.started_at)).limit(limit).offset(offset)
    if status:
        q = q.where(Run.status == status)
    result = await db.execute(q)
    return [RunOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _require_run(run_id, db)
    return RunOut.model_validate(run)


@router.patch("/{run_id}", response_model=RunOut)
async def update_run(run_id: str, body: RunUpdate, db: AsyncSession = Depends(get_db)):
    run = await _require_run(run_id, db)
    if body.status:
        run.status = RunStatus(body.status)
    if body.ended_at:
        run.ended_at = datetime.fromtimestamp(body.ended_at, tz=timezone.utc)
        # Compute final cost
        elapsed = body.ended_at - run.started_at.timestamp()
        from ..services.cost_engine import compute_cost
        cost = compute_cost(
            elapsed_secs=elapsed,
            gpu_cost_per_hour=run.gpu_cost_per_hour,
            cpu_cost_per_hour=run.cpu_cost_per_hour,
            num_gpus=1,
        )
        run.total_cost_usd = cost.cost_so_far_usd

    # Final loss / step count
    last_step = await db.execute(
        select(StepMetric).where(StepMetric.run_id == run_id).order_by(desc(StepMetric.step)).limit(1)
    )
    last_step_row = last_step.scalar_one_or_none()
    if last_step_row:
        run.final_loss = last_step_row.loss
        run.total_steps = last_step_row.step

    await db.flush()
    return RunOut.model_validate(run)


# ── Time-series queries ────────────────────────────────────────────────────────

@router.get("/{run_id}/gpu_metrics", response_model=List[GpuTimeSeriesPoint])
async def get_gpu_timeseries(
    run_id: str,
    device_index: int = 0,
    limit: int = Query(500, le=2000),
    db: AsyncSession = Depends(get_db),
):
    await _require_run(run_id, db)
    q = (
        select(GpuMetric)
        .where(GpuMetric.run_id == run_id, GpuMetric.device_index == device_index)
        .order_by(GpuMetric.time)
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        GpuTimeSeriesPoint(
            time=r.time,
            utilization_pct=r.utilization_pct,
            memory_pct=r.memory_pct,
            temperature_c=r.temperature_c,
            power_draw_w=r.power_draw_w,
        )
        for r in rows
    ]


@router.get("/{run_id}/step_metrics", response_model=List[StepTimeSeriesPoint])
async def get_step_timeseries(
    run_id: str,
    limit: int = Query(500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    await _require_run(run_id, db)
    q = (
        select(StepMetric)
        .where(StepMetric.run_id == run_id)
        .order_by(StepMetric.step)
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        StepTimeSeriesPoint(
            time=r.time,
            step=r.step,
            loss=r.loss,
            step_time_ms=r.step_time_ms,
            tokens_per_sec=r.tokens_per_sec,
        )
        for r in rows
    ]


@router.get("/{run_id}/alerts", response_model=List[AlertOut])
async def get_alerts(run_id: str, db: AsyncSession = Depends(get_db)):
    await _require_run(run_id, db)
    q = select(Alert).where(Alert.run_id == run_id).order_by(desc(Alert.created_at)).limit(100)
    rows = (await db.execute(q)).scalars().all()
    return [AlertOut.model_validate(r) for r in rows]


@router.patch("/{run_id}/alerts/{alert_id}/ack")
async def ack_alert(run_id: str, alert_id: int, db: AsyncSession = Depends(get_db)):
    q = select(Alert).where(Alert.id == alert_id, Alert.run_id == run_id)
    alert = (await db.execute(q)).scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = True
    await db.flush()
    return {"ok": True}


# ── Helper ────────────────────────────────────────────────────────────────────

async def _require_run(run_id: str, db: AsyncSession) -> Run:
    result = await db.execute(select(Run).where(Run.run_id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return run
