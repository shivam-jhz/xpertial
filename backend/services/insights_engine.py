"""
XPERTIAL – Insights Engine
----------------------------
Aggregates all backend signals into a ranked list of InsightCard objects
displayed prominently in the dashboard.  Cards are prioritised by impact.

Each card has:
  - id          : stable key for deduplication
  - category    : waste | bottleneck | stability | cost | recommendation
  - severity    : critical | warning | info | positive
  - title       : 1-line headline (shown large)
  - body        : 2-3 sentence explanation
  - action      : what the user should do
  - metric_ref  : optional numeric for callout display
  - metric_unit : e.g. "%" or "USD"
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class InsightCard:
    id: str
    category: str          # waste | bottleneck | stability | cost | positive
    severity: str          # critical | warning | info | positive
    title: str
    body: str
    action: str
    metric_ref: Optional[float] = None
    metric_unit: str = ""
    dismissed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def generate_insights(
    *,
    gpu_idle_pct: float,
    wasted_cost_usd: float,
    wasted_cost_inr: float,
    bottleneck: str,
    bottleneck_detail: str,
    loss_trend: str,
    stall_detected: bool,
    loss_plateau_steps: int,
    efficiency_score: float,
    efficiency_grade: str,
    step_time_cv: float,
    avg_gpu_util: float,
    cost_so_far_usd: float,
    projected_total_usd: Optional[float],
    burn_rate_usd_hr: float,
    current_step: int,
    total_steps: Optional[int],
    num_gpus: int,
    gpu_cost_per_hour: float,
) -> List[InsightCard]:
    cards: List[InsightCard] = []

    # ── GPU Waste ─────────────────────────────────────────────────────────
    if gpu_idle_pct >= 40:
        cards.append(InsightCard(
            id="gpu_waste_critical",
            category="waste",
            severity="critical",
            title=f"GPU idle {gpu_idle_pct:.0f}% — ₹{wasted_cost_inr:.0f} wasted",
            body=(
                f"Your GPU is sitting idle {gpu_idle_pct:.0f}% of the time, "
                f"burning ${wasted_cost_usd:.2f} (₹{wasted_cost_inr:.0f}) on compute you're not using. "
                f"This is the single biggest opportunity to cut cost."
            ),
            action="Increase batch size, add more DataLoader workers, or enable prefetch_factor.",
            metric_ref=gpu_idle_pct,
            metric_unit="%",
        ))
    elif gpu_idle_pct >= 20:
        cards.append(InsightCard(
            id="gpu_waste_warning",
            category="waste",
            severity="warning",
            title=f"GPU idle {gpu_idle_pct:.0f}% — ${wasted_cost_usd:.2f} wasted",
            body=(
                f"GPU utilisation is below optimal. "
                f"${wasted_cost_usd:.2f} spent on idle GPU time so far."
            ),
            action="Profile your data pipeline with torch.utils.benchmark.",
            metric_ref=gpu_idle_pct,
            metric_unit="%",
        ))

    # ── Bottleneck ────────────────────────────────────────────────────────
    if bottleneck == "data_pipeline":
        cards.append(InsightCard(
            id="bottleneck_data",
            category="bottleneck",
            severity="warning",
            title="Data pipeline is bottlenecking your GPU",
            body=bottleneck_detail,
            action=(
                "Set DataLoader(num_workers=8, pin_memory=True, prefetch_factor=2). "
                "If data is on network storage, copy to local NVMe."
            ),
        ))
    elif bottleneck == "cpu_bound":
        cards.append(InsightCard(
            id="bottleneck_cpu",
            category="bottleneck",
            severity="warning",
            title="CPU preprocessing is saturated",
            body=bottleneck_detail,
            action=(
                "Pre-process and cache your dataset offline. "
                "Use datasets.map(..., num_proc=N) to parallelise preprocessing."
            ),
        ))
    elif bottleneck == "io_bound":
        cards.append(InsightCard(
            id="bottleneck_io",
            category="bottleneck",
            severity="warning",
            title="Irregular step times suggest I/O stalls",
            body=bottleneck_detail,
            action="Move dataset to local SSD. Use memory-mapped formats (LMDB, WebDataset, Arrow).",
        ))

    # ── Stall detection ───────────────────────────────────────────────────
    if stall_detected:
        cards.append(InsightCard(
            id="stall",
            category="stability",
            severity="critical",
            title=f"Training stalled — loss flat for {loss_plateau_steps} steps",
            body=(
                f"Loss has not improved in {loss_plateau_steps} steps. "
                f"You are burning ${burn_rate_usd_hr:.2f}/hr without making progress. "
                "Consider stopping, reducing learning rate, or checking for data issues."
            ),
            action="Try: reduce LR by 10×, check gradient norms, or stop and adjust hyperparameters.",
            metric_ref=loss_plateau_steps,
            metric_unit="steps",
        ))
    elif loss_trend == "plateau" and loss_plateau_steps > 15:
        cards.append(InsightCard(
            id="plateau_warning",
            category="stability",
            severity="warning",
            title=f"Loss plateauing — {loss_plateau_steps} steps without improvement",
            body=(
                f"Loss improvement has slowed significantly over the last {loss_plateau_steps} steps. "
                "This may resolve naturally or indicate a learning rate schedule issue."
            ),
            action="Monitor for another 20 steps. If no improvement, apply LR warmup or restart.",
        ))

    # ── Cost projection ───────────────────────────────────────────────────
    if projected_total_usd and total_steps and current_step > 0:
        remaining = projected_total_usd - cost_so_far_usd
        pct_done = current_step / total_steps * 100
        cards.append(InsightCard(
            id="cost_projection",
            category="cost",
            severity="info",
            title=f"Projected total: ${projected_total_usd:.2f} ({pct_done:.0f}% complete)",
            body=(
                f"At current burn rate of ${burn_rate_usd_hr:.2f}/hr, "
                f"this run will cost ~${projected_total_usd:.2f} total. "
                f"${remaining:.2f} remaining for {total_steps - current_step:,} steps."
            ),
            action=(
                "To reduce cost: increase batch size (if VRAM allows), "
                "use mixed precision (bf16), or enable gradient checkpointing."
            ),
            metric_ref=projected_total_usd,
            metric_unit="USD",
        ))

    # ── Step time instability ─────────────────────────────────────────────
    if step_time_cv > 0.3:
        cards.append(InsightCard(
            id="step_instability",
            category="bottleneck",
            severity="warning",
            title=f"Irregular step times (CV={step_time_cv:.2f})",
            body=(
                f"Step duration varies {step_time_cv*100:.0f}% around the mean. "
                "This usually means occasional I/O stalls, GC pauses, or dynamic batching issues."
            ),
            action="Enable torch.backends.cudnn.benchmark = True. Use static batch shapes if possible.",
        ))

    # ── Positive feedback ─────────────────────────────────────────────────
    if efficiency_grade in ("A", "B") and loss_trend == "improving":
        cards.append(InsightCard(
            id="positive",
            category="positive",
            severity="positive",
            title=f"Training running efficiently (Grade {efficiency_grade})",
            body=(
                f"GPU utilisation is strong ({avg_gpu_util:.0f}%), "
                "loss is consistently improving, and no bottlenecks detected."
            ),
            action="Keep going — current configuration is well-optimised.",
            metric_ref=efficiency_score,
            metric_unit="%",
        ))

    # Sort: critical first, then warning, info, positive
    _order = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
    cards.sort(key=lambda c: _order.get(c.severity, 9))

    return cards
