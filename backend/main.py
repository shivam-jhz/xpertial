"""
XPERTIAL – FastAPI Application v2
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import create_tables
from .routers import ingest, ws
from .routers.insights import router as insights_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
log = logging.getLogger("xpertial.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("XPERTIAL backend starting")
    await create_tables()
    log.info("Database tables ready")
    yield
    log.info("XPERTIAL backend stopping")


app = FastAPI(
    title="XPERTIAL – Training Intelligence API",
    version="0.2.0",
    description="GPU observability, cost intelligence, and bottleneck detection for ML training.",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ── Runs (reuse base, import separately) ─────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .models import Run, RunEnvironment, RunStatus, StepMetric
from .routers.ingest import register_run_in_cache
import time
from datetime import datetime, timezone

runs_router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

@runs_router.post("", status_code=201)
async def create_run(body: dict, db: AsyncSession = Depends(get_db)):
    started = datetime.fromtimestamp(body["started_at"], tz=timezone.utc)
    run = Run(
        run_id=body["run_id"], name=body["name"], tags=body.get("tags"),
        gpu_cost_per_hour=body.get("gpu_cost_per_hour", 3.50),
        cpu_cost_per_hour=body.get("cpu_cost_per_hour", 0.10),
        started_at=started, status=RunStatus.running,
        total_steps_planned=body.get("total_steps"),
        batch_size=body.get("batch_size"), seq_len=body.get("seq_len"),
    )
    db.add(run)

    # Store environment snapshot
    env = body.get("environment", {})
    if env:
        gpus = env.get("gpus", [])
        db.add(RunEnvironment(
            run_id=body["run_id"],
            framework=env.get("framework"),
            framework_version=env.get("framework_version"),
            cloud_provider=env.get("cloud_provider"),
            instance_type=env.get("instance_type"),
            num_gpus=len(gpus),
            gpu_names=[g.get("name") for g in gpus],
            python_version=env.get("python_version"),
            cuda_version=env.get("cuda_version"),
            distributed=env.get("distributed"),
            world_size=env.get("world_size"),
            hostname=env.get("hostname"),
            raw_json=env,
        ))

    await db.flush()
    register_run_in_cache(body["run_id"], body["started_at"],
                          body.get("gpu_cost_per_hour", 3.50),
                          body.get("cpu_cost_per_hour", 0.10))
    return {"run_id": run.run_id, "status": "created"}


@runs_router.get("")
async def list_runs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    q = select(Run).order_by(desc(Run.started_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_run_out(r) for r in rows]


@runs_router.get("/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    r = await _req_run(run_id, db)
    return _run_out(r)


@runs_router.patch("/{run_id}")
async def update_run(run_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    run = await _req_run(run_id, db)
    if body.get("status"):
        run.status = RunStatus(body["status"])
    if body.get("ended_at"):
        run.ended_at = datetime.fromtimestamp(body["ended_at"], tz=timezone.utc)
        from .services.cost_engine import compute_cost
        elapsed = body["ended_at"] - run.started_at.timestamp()
        cost = compute_cost(elapsed, run.gpu_cost_per_hour, run.cpu_cost_per_hour, 1)
        run.total_cost_usd = cost.cost_so_far_usd
    last = (await db.execute(
        select(StepMetric).where(StepMetric.run_id == run_id).order_by(desc(StepMetric.step)).limit(1)
    )).scalar_one_or_none()
    if last:
        run.final_loss = last.loss
        run.total_steps = last.step
    await db.flush()
    return _run_out(run)


@runs_router.get("/{run_id}/gpu_metrics")
async def gpu_metrics(run_id: str, device_index: int = 0, limit: int = 300, db: AsyncSession = Depends(get_db)):
    from .models import GpuMetric
    q = select(GpuMetric).where(GpuMetric.run_id == run_id, GpuMetric.device_index == device_index).order_by(GpuMetric.time).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [{"time": r.time.isoformat(), "utilization_pct": r.utilization_pct, "memory_pct": r.memory_pct, "temperature_c": r.temperature_c, "power_draw_w": r.power_draw_w} for r in rows]


@runs_router.get("/{run_id}/step_metrics")
async def step_metrics(run_id: str, limit: int = 500, db: AsyncSession = Depends(get_db)):
    q = select(StepMetric).where(StepMetric.run_id == run_id).order_by(StepMetric.step).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [{"time": r.time.isoformat(), "step": r.step, "loss": r.loss, "step_time_ms": r.step_time_ms, "tokens_per_sec": r.tokens_per_sec} for r in rows]


@runs_router.get("/{run_id}/alerts")
async def get_alerts(run_id: str, db: AsyncSession = Depends(get_db)):
    from .models import Alert
    from sqlalchemy import desc as sdesc
    q = select(Alert).where(Alert.run_id == run_id).order_by(sdesc(Alert.created_at)).limit(50)
    rows = (await db.execute(q)).scalars().all()
    return [{"id": r.id, "level": r.level.value, "alert_type": r.alert_type.value, "message": r.message, "acknowledged": r.acknowledged, "created_at": r.created_at.isoformat()} for r in rows]


@runs_router.patch("/{run_id}/alerts/{alert_id}/ack")
async def ack_alert(run_id: str, alert_id: int, db: AsyncSession = Depends(get_db)):
    from .models import Alert
    a = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
    if a: a.acknowledged = True; await db.flush()
    return {"ok": True}


def _run_out(r: Run) -> dict:
    return {
        "run_id": r.run_id, "name": r.name, "status": r.status.value,
        "tags": r.tags, "gpu_cost_per_hour": r.gpu_cost_per_hour,
        "started_at": r.started_at.isoformat(), "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "total_cost_usd": r.total_cost_usd, "total_steps": r.total_steps, "final_loss": r.final_loss,
        "efficiency_grade": r.efficiency_grade, "efficiency_score": r.efficiency_score,
        "avg_gpu_util": r.avg_gpu_util, "wasted_cost_usd": r.wasted_cost_usd,
        "last_checkpoint_step": r.last_checkpoint_step, "bottleneck": r.bottleneck,
    }


async def _req_run(run_id: str, db: AsyncSession) -> Run:
    r = (await db.execute(select(Run).where(Run.run_id == run_id))).scalar_one_or_none()
    if not r: raise HTTPException(404)
    return r


app.include_router(runs_router)
app.include_router(ingest.router)
app.include_router(ws.router)
app.include_router(insights_router)

@app.post("/api/v1/runs/{run_id}/checkpoint", status_code=204)
async def checkpoint(run_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(Run).where(Run.run_id == run_id))).scalar_one_or_none()
    if r and body.get("success", True):
        r.last_checkpoint_step = body.get("step")
        r.last_checkpoint_path = body.get("path")
        await db.flush()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0", "product": "xpertial"}
