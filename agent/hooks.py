"""
XPERTIAL hooks – data classes shipped from agent to backend.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class StepEvent:
    run_id: str
    step: int
    loss: Optional[float]
    step_time_ms: float
    tokens_per_sec: Optional[float]
    samples_per_sec: Optional[float]
    grad_norm: Optional[float]
    learning_rate: Optional[float]
    epoch: Optional[int]
    has_nan: bool = False
    has_inf: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EfficiencyEvent:
    """Sent every N steps to record efficiency snapshot + checkpoint status."""
    run_id: str
    step: int
    efficiency: Any   # EfficiencySnapshot
    checkpoint: Any   # CheckpointStatus | None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "step": self.step,
            "timestamp": self.timestamp,
            "efficiency": self.efficiency.to_dict() if self.efficiency else None,
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint else None,
        }
