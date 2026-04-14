"""
XPERTIAL – SQLAlchemy ORM models (v2)
New tables: efficiency_snapshots, insights, run_environments
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Index, Integer, JSON, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    stopped = "stopped"


class AlertLevel(str, enum.Enum):
    warning = "warning"
    critical = "critical"


class AlertType(str, enum.Enum):
    gpu_util_low = "gpu_util_low"
    gpu_temp_high = "gpu_temp_high"
    vram_high = "vram_high"
    stall = "stall"
    nan_loss = "nan_loss"
    inf_loss = "inf_loss"
    oom = "oom"
    other = "other"


# ── Runs ──────────────────────────────────────────────────────────────────────

class Run(Base):
    __tablename__ = "runs"

    run_id = Column(String(36), primary_key=True)
    name = Column(String(256), nullable=False)
    status = Column(Enum(RunStatus), nullable=False, default=RunStatus.running)
    tags = Column(JSON, nullable=True)
    gpu_cost_per_hour = Column(Float, nullable=False, default=3.50)
    cpu_cost_per_hour = Column(Float, nullable=False, default=0.10)
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    total_cost_usd = Column(Float, nullable=True)
    total_steps = Column(Integer, nullable=True)
    final_loss = Column(Float, nullable=True)

    # New v2 fields
    total_steps_planned = Column(Integer, nullable=True)   # for projection
    batch_size = Column(Integer, nullable=True)
    seq_len = Column(Integer, nullable=True)
    efficiency_grade = Column(String(2), nullable=True)    # A B C D F
    efficiency_score = Column(Float, nullable=True)
    avg_gpu_util = Column(Float, nullable=True)
    wasted_cost_usd = Column(Float, nullable=True)
    last_checkpoint_step = Column(Integer, nullable=True)
    last_checkpoint_path = Column(String(512), nullable=True)
    bottleneck = Column(String(32), nullable=True)

    # Relationships
    gpu_metrics = relationship("GpuMetric", back_populates="run", cascade="all, delete-orphan")
    system_metrics = relationship("SystemMetric", back_populates="run", cascade="all, delete-orphan")
    step_metrics = relationship("StepMetric", back_populates="run", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="run", cascade="all, delete-orphan")
    efficiency_snapshots = relationship("EfficiencySnapshot", back_populates="run", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="run", cascade="all, delete-orphan")
    environment = relationship("RunEnvironment", back_populates="run", uselist=False, cascade="all, delete-orphan")


# ── Time-series (unchanged from v1) ───────────────────────────────────────────

class GpuMetric(Base):
    __tablename__ = "gpu_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    time = Column(DateTime(timezone=True), nullable=False)
    device_index = Column(Integer, nullable=False, default=0)
    device_name = Column(String(128), nullable=True)
    utilization_pct = Column(Float, nullable=True)
    memory_used_mb = Column(Float, nullable=True)
    memory_total_mb = Column(Float, nullable=True)
    memory_pct = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)
    power_draw_w = Column(Float, nullable=True)
    power_limit_w = Column(Float, nullable=True)
    fan_speed_pct = Column(Float, nullable=True)
    sm_clock_mhz = Column(Integer, nullable=True)
    mem_clock_mhz = Column(Integer, nullable=True)
    run = relationship("Run", back_populates="gpu_metrics")
    __table_args__ = (Index("ix_gpu_metrics_run_time", "run_id", "time"),)


class SystemMetric(Base):
    __tablename__ = "system_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    time = Column(DateTime(timezone=True), nullable=False)
    cpu_util_pct = Column(Float, nullable=True)
    ram_used_mb = Column(Float, nullable=True)
    ram_total_mb = Column(Float, nullable=True)
    ram_pct = Column(Float, nullable=True)
    swap_used_mb = Column(Float, nullable=True)
    disk_read_mb_s = Column(Float, nullable=True)
    disk_write_mb_s = Column(Float, nullable=True)
    net_sent_mb_s = Column(Float, nullable=True)
    net_recv_mb_s = Column(Float, nullable=True)
    load_avg_1m = Column(Float, nullable=True)
    run = relationship("Run", back_populates="system_metrics")
    __table_args__ = (Index("ix_system_metrics_run_time", "run_id", "time"),)


class StepMetric(Base):
    __tablename__ = "step_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    time = Column(DateTime(timezone=True), nullable=False)
    step = Column(Integer, nullable=False)
    epoch = Column(Integer, nullable=True)
    loss = Column(Float, nullable=True)
    step_time_ms = Column(Float, nullable=True)
    samples_per_sec = Column(Float, nullable=True)
    tokens_per_sec = Column(Float, nullable=True)
    grad_norm = Column(Float, nullable=True)
    learning_rate = Column(Float, nullable=True)
    has_nan = Column(Boolean, nullable=False, default=False)
    has_inf = Column(Boolean, nullable=False, default=False)
    run = relationship("Run", back_populates="step_metrics")
    __table_args__ = (
        Index("ix_step_metrics_run_step", "run_id", "step"),
        Index("ix_step_metrics_run_time", "run_id", "time"),
    )


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    level = Column(Enum(AlertLevel), nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    acknowledged = Column(Boolean, nullable=False, default=False)
    run = relationship("Run", back_populates="alerts")
    __table_args__ = (Index("ix_alerts_run_created", "run_id", "created_at"),)


# ── NEW v2 tables ─────────────────────────────────────────────────────────────

class EfficiencySnapshot(Base):
    """One row every N steps capturing derived efficiency metrics."""
    __tablename__ = "efficiency_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    time = Column(DateTime(timezone=True), nullable=False, default=func.now())
    step = Column(Integer, nullable=False)

    gpu_idle_pct = Column(Float, nullable=True)
    wasted_cost_usd = Column(Float, nullable=True)
    wasted_cost_inr = Column(Float, nullable=True)
    bottleneck = Column(String(32), nullable=True)
    bottleneck_detail = Column(Text, nullable=True)
    avg_step_time_ms = Column(Float, nullable=True)
    step_time_cv = Column(Float, nullable=True)
    avg_tokens_per_sec = Column(Float, nullable=True)
    loss_plateau_steps = Column(Integer, nullable=True)
    loss_trend = Column(String(16), nullable=True)
    stall_detected = Column(Boolean, nullable=True, default=False)
    efficiency_score = Column(Float, nullable=True)
    efficiency_grade = Column(String(2), nullable=True)

    # Checkpoint at this moment
    last_checkpoint_step = Column(Integer, nullable=True)
    checkpoint_save_failed = Column(Boolean, nullable=True, default=False)

    run = relationship("Run", back_populates="efficiency_snapshots")
    __table_args__ = (Index("ix_eff_run_step", "run_id", "step"),)


class Insight(Base):
    """Persistent insight cards — regenerated on each efficiency snapshot."""
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    insight_id = Column(String(64), nullable=False)   # stable dedup key
    category = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    metric_ref = Column(Float, nullable=True)
    metric_unit = Column(String(16), nullable=True)
    dismissed = Column(Boolean, nullable=False, default=False)

    run = relationship("Run", back_populates="insights")
    __table_args__ = (
        Index("ix_insights_run_created", "run_id", "created_at"),
        Index("ix_insights_run_iid", "run_id", "insight_id"),
    )


class RunEnvironment(Base):
    """Stores the auto-detected environment snapshot at run start."""
    __tablename__ = "run_environments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False, unique=True)
    framework = Column(String(32), nullable=True)
    framework_version = Column(String(32), nullable=True)
    cloud_provider = Column(String(32), nullable=True)
    instance_type = Column(String(64), nullable=True)
    num_gpus = Column(Integer, nullable=True)
    gpu_names = Column(JSON, nullable=True)       # list of strings
    python_version = Column(String(16), nullable=True)
    cuda_version = Column(String(16), nullable=True)
    distributed = Column(Boolean, nullable=True)
    world_size = Column(Integer, nullable=True)
    hostname = Column(String(128), nullable=True)
    raw_json = Column(JSON, nullable=True)         # full env dict

    run = relationship("Run", back_populates="environment")
