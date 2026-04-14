"""
MLObs Cost Engine
-----------------
Computes live burn rate, cost-so-far, and projected total cost
given GPU/system metrics and run metadata.

Design notes
~~~~~~~~~~~~
- Cost = GPU cost + CPU cost (simplified; extend with storage/network)
- GPU cost is based on the configured $/hr * number of GPUs active
- Projected total requires an estimated total_steps (can be None)
- All calculations are stateless and fast – suitable for hot path in WS handler
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CostEstimate:
    elapsed_secs: float
    burn_rate_per_hour: float      # $/hr at current utilisation
    cost_so_far_usd: float
    projected_total_usd: Optional[float]
    num_gpus: int


def compute_cost(
    elapsed_secs: float,
    gpu_cost_per_hour: float,
    cpu_cost_per_hour: float,
    num_gpus: int,
    current_step: Optional[int] = None,
    total_steps: Optional[int] = None,
    gpu_utils: Optional[List[float]] = None,
) -> CostEstimate:
    """
    Parameters
    ----------
    elapsed_secs:
        Seconds since run started.
    gpu_cost_per_hour:
        $/GPU/hr as configured for the run.
    cpu_cost_per_hour:
        $/hr for the CPU instance.
    num_gpus:
        Number of GPUs seen in the latest metrics batch.
    current_step / total_steps:
        Used for projected total (None → no projection).
    gpu_utils:
        List of GPU utilisation % values (0-100) for each device.
        Used to weight the burn rate – idle GPUs still cost money
        but at a fraction (we model 10% of price when util < 5%).
    """
    elapsed_hrs = elapsed_secs / 3600.0

    # Effective GPU cost: utilisation-weighted (you still pay, but track waste)
    if gpu_utils:
        avg_util = sum(gpu_utils) / len(gpu_utils)
        # Cost is always the full rate – idle GPUs still cost money.
        # We just surface the "wasted" portion in insights.
        effective_gpu_rate = gpu_cost_per_hour * num_gpus
    else:
        effective_gpu_rate = gpu_cost_per_hour * num_gpus

    burn_rate = effective_gpu_rate + cpu_cost_per_hour
    cost_so_far = burn_rate * elapsed_hrs

    projected = None
    if current_step and total_steps and current_step > 0 and total_steps > current_step:
        cost_per_step = cost_so_far / current_step
        projected = cost_per_step * total_steps

    return CostEstimate(
        elapsed_secs=elapsed_secs,
        burn_rate_per_hour=round(burn_rate, 4),
        cost_so_far_usd=round(cost_so_far, 4),
        projected_total_usd=round(projected, 4) if projected else None,
        num_gpus=num_gpus,
    )
