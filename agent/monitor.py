"""
XPERTIAL – Monitor
--------------------
The entire public API is two lines:

    from xpertial import monitor
    monitor.start(api_key='YOUR_KEY')

Everything else is auto-detected.  Advanced usage:

    monitor.start(
        api_key='YOUR_KEY',
        run_name='gpt2-v3',
        tags={'dataset': 'c4'},
        checkpoint_dir='./checkpoints',
        total_steps=10_000,
    )

    # Inside your training loop:
    with monitor.step(step) as ctx:
        loss = model(batch)
        ctx.loss = loss.item()

    # OR the simpler log API:
    monitor.log(step=step, loss=loss.item(), lr=lr)

    # Explicit checkpoint notification:
    monitor.checkpoint(step=step, path='./checkpoints/step_500')
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import math
import os
import queue
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from .detectors import (
    EfficiencyAnalyzer,
    CheckpointTracker,
    detect_environment,
)
from .collector import MetricsCollector
from .shipper import AsyncShipper

log = logging.getLogger("xpertial.monitor")
logging.basicConfig(
    level=os.getenv("XPERTIAL_LOG_LEVEL", "WARNING"),
    format="%(asctime)s [xpertial] %(levelname)s %(message)s",
)


class _StepContext:
    __slots__ = ("loss", "grad_norm", "lr", "num_tokens", "num_samples")

    def __init__(self):
        self.loss: Optional[float] = None
        self.grad_norm: Optional[float] = None
        self.lr: Optional[float] = None
        self.num_tokens: Optional[int] = None
        self.num_samples: Optional[int] = None


class Monitor:
    """Singleton-style monitor.  Call .start() once at script startup."""

    def __init__(self):
        self._started = False
        self._run_id: Optional[str] = None
        self._api_key: Optional[str] = None
        self._backend_url: str = "https://api.xpertial.dev"
        self._queue: Optional[queue.Queue] = None
        self._collector: Optional[MetricsCollector] = None
        self._shipper: Optional[AsyncShipper] = None
        self._efficiency: Optional[EfficiencyAnalyzer] = None
        self._checkpoint: Optional[CheckpointTracker] = None
        self._started_at: float = 0.0
        self._last_step_time: float = 0.0
        self._current_step: int = 0
        self._step_start: Optional[float] = None
        self._total_steps: Optional[int] = None

    # ── Public API ────────────────────────────────────────────────────────

    def start(
        self,
        api_key: str,
        run_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        backend_url: Optional[str] = None,
        checkpoint_dir: Optional[str] = None,
        total_steps: Optional[int] = None,
        gpu_cost_per_hour: Optional[float] = None,
        batch_size: Optional[int] = None,
        seq_len: Optional[int] = None,
    ) -> "Monitor":
        if self._started:
            log.warning("monitor.start() called twice – ignoring second call")
            return self

        self._api_key = api_key
        self._backend_url = backend_url or os.getenv("XPERTIAL_BACKEND_URL", "https://api.xpertial.dev")
        self._run_id = str(uuid.uuid4())
        self._started_at = time.time()
        self._total_steps = total_steps

        # Auto-detect environment
        env = detect_environment()
        effective_cost = gpu_cost_per_hour or env.estimated_cost_per_hour

        # Internal subsystems
        self._queue = queue.Queue(maxsize=5_000)
        self._efficiency = EfficiencyAnalyzer(
            window=50,
            gpu_cost_per_hour=effective_cost * max(len(env.gpus), 1),
        )
        self._checkpoint = CheckpointTracker(watch_dir=checkpoint_dir)

        from .config import AgentConfig
        cfg = AgentConfig(
            backend_url=self._backend_url,
            api_key=api_key,
            gpu_cost_per_hour=effective_cost,
        )

        self._collector = MetricsCollector(self._run_id, self._queue, cfg)
        self._shipper = AsyncShipper(self._queue, self._run_id, cfg)

        # Register with backend
        name = run_name or f"run-{self._run_id[:8]}"
        self._register(name, tags or {}, env, effective_cost, batch_size, seq_len)

        self._shipper.start()
        self._collector.start()
        self._started = True

        atexit.register(self._on_exit)
        log.info("XPERTIAL monitor started (run_id=%s)", self._run_id)
        print(
            f"[xpertial] Monitoring started → {self._backend_url}\n"
            f"           Run: {name}  ({len(env.gpus)} GPU{'s' if len(env.gpus) != 1 else ''},"
            f" {env.framework} {env.framework_version})"
        )
        return self

    def log(
        self,
        step: int,
        loss: Optional[float] = None,
        lr: Optional[float] = None,
        grad_norm: Optional[float] = None,
        num_tokens: Optional[int] = None,
        num_samples: Optional[int] = None,
        **extra,
    ):
        """Lightweight log – call once per step instead of using step_context."""
        now = time.perf_counter()
        step_ms = (now - self._step_start) * 1000 if self._step_start else 0.0
        self._step_start = now
        self._last_step_time = time.time()
        self._current_step = step

        self._push_step_event(
            step=step, loss=loss, lr=lr, grad_norm=grad_norm,
            step_ms=step_ms, num_tokens=num_tokens, num_samples=num_samples,
        )

        # Feed efficiency analyzer
        if loss is not None and not math.isnan(loss) and not math.isinf(loss):
            self._efficiency.push_loss(loss)
        self._efficiency.push_step(step_ms, 0, None)  # CPU util fed from collector

    @contextlib.contextmanager
    def step(self, step: int, epoch: Optional[int] = None):
        ctx = _StepContext()
        self._step_start = time.perf_counter()
        self._current_step = step
        try:
            yield ctx
        finally:
            now = time.perf_counter()
            step_ms = (now - self._step_start) * 1000 if self._step_start else 0.0
            self._last_step_time = time.time()
            self._push_step_event(
                step=step, loss=ctx.loss, lr=ctx.lr, grad_norm=ctx.grad_norm,
                step_ms=step_ms, num_tokens=ctx.num_tokens, num_samples=ctx.num_samples,
                epoch=epoch,
            )
            if ctx.loss is not None and not math.isnan(ctx.loss):
                self._efficiency.push_loss(ctx.loss)
            self._efficiency.push_step(step_ms, 0, None)

    def checkpoint(self, step: int, path: Optional[str] = None):
        """Call after saving a checkpoint."""
        self._checkpoint.on_save(step, path)
        self._push_checkpoint_event(step, path, success=True)

    def checkpoint_failed(self, step: int, reason: str = ""):
        self._checkpoint.on_save_failed(step, reason)
        self._push_checkpoint_event(step, None, success=False, reason=reason)

    def stop(self, status: str = "completed"):
        if not self._started:
            return
        self._collector.stop()
        self._shipper.stop()
        self._finish(status)
        self._started = False

    # ── HuggingFace Trainer callback ─────────────────────────────────────

    def hf_callback(self):
        """Returns a HuggingFace TrainerCallback for automatic integration."""
        monitor_ref = self
        try:
            from transformers import TrainerCallback

            class _XpertialCallback(TrainerCallback):
                def on_step_begin(self, args, state, control, **kw):
                    monitor_ref._step_start = time.perf_counter()

                def on_log(self, args, state, control, logs=None, **kw):
                    logs = logs or {}
                    monitor_ref.log(
                        step=state.global_step,
                        loss=logs.get("loss"),
                        lr=logs.get("learning_rate"),
                    )

                def on_save(self, args, state, control, **kw):
                    monitor_ref.checkpoint(state.global_step)

            return _XpertialCallback()
        except ImportError:
            return None

    # ── Private helpers ───────────────────────────────────────────────────

    def _push_step_event(self, step, loss, lr, grad_norm, step_ms,
                         num_tokens, num_samples, epoch=None):
        from .hooks import StepEvent
        has_nan = bool(loss is not None and math.isnan(loss))
        has_inf = bool(loss is not None and math.isinf(loss))

        efficiency = self._efficiency.snapshot() if self._efficiency else None
        event = StepEvent(
            run_id=self._run_id,
            step=step,
            loss=loss if not (has_nan or has_inf) else None,
            step_time_ms=round(step_ms, 2),
            tokens_per_sec=(num_tokens / (step_ms / 1000)) if (num_tokens and step_ms > 0) else None,
            samples_per_sec=(num_samples / (step_ms / 1000)) if (num_samples and step_ms > 0) else None,
            grad_norm=grad_norm,
            learning_rate=lr,
            epoch=epoch,
            has_nan=has_nan,
            has_inf=has_inf,
        )
        if self._queue:
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass

        # Ship efficiency snapshot periodically (every 25 steps)
        if efficiency and step % 25 == 0:
            self._push_efficiency(efficiency, step)

    def _push_efficiency(self, eff, step: int):
        from .hooks import EfficiencyEvent
        event = EfficiencyEvent(
            run_id=self._run_id,
            step=step,
            efficiency=eff,
            checkpoint=self._checkpoint.status if self._checkpoint else None,
        )
        if self._queue:
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass

    def _push_checkpoint_event(self, step, path, success, reason=""):
        # Inform backend via direct HTTP (small payload, low frequency)
        if not self._api_key:
            return
        try:
            httpx.post(
                f"{self._backend_url}/api/v1/runs/{self._run_id}/checkpoint",
                json={"step": step, "path": path, "success": success, "reason": reason},
                headers={"X-Api-Key": self._api_key},
                timeout=3.0,
            )
        except Exception:
            pass

    def _register(self, name, tags, env, cost, batch_size, seq_len):
        payload = {
            "run_id": self._run_id,
            "name": name,
            "tags": tags,
            "gpu_cost_per_hour": cost,
            "cpu_cost_per_hour": 0.10,
            "started_at": self._started_at,
            "environment": env.to_dict(),
            "total_steps": self._total_steps,
            "batch_size": batch_size,
            "seq_len": seq_len,
        }
        try:
            r = httpx.post(
                f"{self._backend_url}/api/v1/runs",
                json=payload,
                headers={"X-Api-Key": self._api_key} if self._api_key else {},
                timeout=5.0,
            )
            r.raise_for_status()
        except Exception as e:
            log.warning("Could not register run: %s (continuing offline)", e)

    def _finish(self, status: str):
        try:
            httpx.patch(
                f"{self._backend_url}/api/v1/runs/{self._run_id}",
                json={"status": status, "ended_at": time.time()},
                headers={"X-Api-Key": self._api_key} if self._api_key else {},
                timeout=5.0,
            )
        except Exception:
            pass

    def _on_exit(self):
        if self._started:
            self.stop(status="stopped")


# ── Module-level singleton ────────────────────────────────────────────────
monitor = Monitor()
