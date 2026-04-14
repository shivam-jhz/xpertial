"""
XPERTIAL – Run Comparator
---------------------------
Compares two or more completed (or live) runs across:
  - Cost efficiency   : cost per unit of loss reduction
  - Time efficiency   : steps to reach a target loss
  - GPU efficiency    : average GPU utilisation
  - Convergence speed : loss drop rate

Produces human-readable comparison sentences like:
  "Run B achieved similar loss with 22% lower cost ($18.20 vs $23.10)"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RunSummary:
    run_id: str
    name: str
    total_cost_usd: float
    total_steps: int
    final_loss: Optional[float]
    avg_gpu_util: float
    avg_gpu_idle: float
    avg_step_time_ms: float
    efficiency_score: float
    efficiency_grade: str
    wasted_cost_usd: float
    duration_hrs: float
    bottleneck: str


@dataclass
class ComparisonResult:
    runs: List[RunSummary]
    winner_id: str                # run_id of the most efficient run
    winner_name: str
    insights: List[str]           # human-readable sentences
    cost_diff_pct: float          # % cost difference between best and worst
    loss_diff_pct: float
    grade_comparison: str         # e.g. "A vs C"

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "runs": [asdict(r) for r in self.runs],
        }


def compare_runs(summaries: List[RunSummary]) -> ComparisonResult:
    """
    Given a list of RunSummary objects, produce a structured comparison.
    Works with 2–8 runs.
    """
    if len(summaries) < 2:
        raise ValueError("Need at least 2 runs to compare")

    valid = [r for r in summaries if r.total_cost_usd > 0]
    if not valid:
        valid = summaries

    # Pick winner: highest efficiency score, tie-break by lowest cost
    winner = min(valid, key=lambda r: (-r.efficiency_score, r.total_cost_usd))
    loser  = max(valid, key=lambda r: (-r.efficiency_score, r.total_cost_usd))

    insights: List[str] = []

    # 1. Cost comparison
    costs = [r.total_cost_usd for r in valid if r.total_cost_usd > 0]
    if len(costs) >= 2:
        min_cost = min(costs)
        max_cost = max(costs)
        diff_pct = (max_cost - min_cost) / max_cost * 100
        if diff_pct > 5:
            cheap = next(r for r in valid if r.total_cost_usd == min_cost)
            expensive = next(r for r in valid if r.total_cost_usd == max_cost)
            insights.append(
                f"'{cheap.name}' cost {_fmt_usd(min_cost)} vs '{expensive.name}' at "
                f"{_fmt_usd(max_cost)} — {diff_pct:.0f}% cheaper for similar training."
            )
    else:
        diff_pct = 0.0

    # 2. Loss comparison
    loss_vals = [(r.name, r.final_loss) for r in valid if r.final_loss is not None]
    loss_diff_pct = 0.0
    if len(loss_vals) >= 2:
        best_loss_name, best_loss = min(loss_vals, key=lambda x: x[1])
        worst_loss_name, worst_loss = max(loss_vals, key=lambda x: x[1])
        if worst_loss > 0:
            loss_diff_pct = (worst_loss - best_loss) / worst_loss * 100
        if loss_diff_pct > 2:
            insights.append(
                f"'{best_loss_name}' converged to lower loss ({best_loss:.4f}) "
                f"vs '{worst_loss_name}' ({worst_loss:.4f}) — {loss_diff_pct:.1f}% better."
            )

    # 3. GPU efficiency
    for run in valid:
        if run.avg_gpu_idle > 35:
            insights.append(
                f"'{run.name}' had GPU idle {run.avg_gpu_idle:.0f}% of the time "
                f"(wasting {_fmt_usd(run.wasted_cost_usd)}). Review data pipeline."
            )

    # 4. Bottleneck comparison
    bottleneck_runs = [r for r in valid if r.bottleneck not in ("normal", "")]
    for run in bottleneck_runs:
        insights.append(
            f"'{run.name}' bottleneck: {run.bottleneck.replace('_', ' ')}."
        )

    # 5. Speed comparison
    if all(r.total_steps > 0 for r in valid):
        fastest = min(valid, key=lambda r: r.avg_step_time_ms)
        slowest = max(valid, key=lambda r: r.avg_step_time_ms)
        if slowest.avg_step_time_ms > fastest.avg_step_time_ms * 1.15:
            ratio = slowest.avg_step_time_ms / fastest.avg_step_time_ms
            insights.append(
                f"'{fastest.name}' steps {ratio:.1f}× faster than '{slowest.name}' "
                f"({fastest.avg_step_time_ms:.0f}ms vs {slowest.avg_step_time_ms:.0f}ms per step)."
            )

    # 6. Summary recommendation
    insights.append(
        f"Recommendation: '{winner.name}' is the most efficient run "
        f"(efficiency grade {winner.efficiency_grade}, {_fmt_usd(winner.total_cost_usd)} total cost)."
    )

    grades = " vs ".join(r.efficiency_grade for r in valid)

    return ComparisonResult(
        runs=valid,
        winner_id=winner.run_id,
        winner_name=winner.name,
        insights=insights,
        cost_diff_pct=round(diff_pct, 1),
        loss_diff_pct=round(loss_diff_pct, 1),
        grade_comparison=grades,
    )


def _fmt_usd(usd: float) -> str:
    if usd < 0.01:
        return f"${usd:.4f}"
    if usd < 10:
        return f"${usd:.2f}"
    return f"${usd:.1f}"
