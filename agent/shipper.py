"""
MLObs Async Shipper
--------------------
Drains the shared event queue and POSTs batches to the FastAPI backend.
Uses httpx for async HTTP with retry/backoff, runs in its own thread
with an asyncio event loop so it never blocks the training process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from collections import deque
from typing import Any, List

import httpx

from .collector import MetricsBatch
from .config import AgentConfig, DEFAULT_CONFIG
from .hooks import StepEvent

log = logging.getLogger("mlobs.shipper")


class AsyncShipper:
    """
    Consumes MetricsBatch and StepEvent objects from a shared queue and
    ships them to the backend over HTTP.

    Architecture
    ~~~~~~~~~~~~
    - One background *thread* runs an asyncio event loop.
    - That loop fires _ship_loop() every `ship_interval` seconds.
    - _ship_loop drains the queue, groups items by type, and POSTs them.
    - Failed requests are retried with exponential back-off.
    - Items that fail permanently are logged and discarded.
    """

    def __init__(self, queue: queue.Queue, run_id: str, config: AgentConfig = DEFAULT_CONFIG):
        self.queue = queue
        self.run_id = run_id
        self.cfg = config
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="mlobs-shipper")
        self._client: httpx.AsyncClient | None = None

        # Simple in-memory stats
        self.shipped_batches = 0
        self.shipped_steps = 0
        self.failed_requests = 0

    # ── Public ────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        log.info("Shipper started → %s", self.cfg.backend_url)

    def stop(self):
        self._stop.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        log.info("Shipper stopped (batches=%d steps=%d failed=%d)",
                 self.shipped_batches, self.shipped_steps, self.failed_requests)

    # ── Thread entry point ────────────────────────────────────────────────

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            self._loop.close()

    async def _async_main(self):
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["X-Api-Key"] = self.cfg.api_key

        async with httpx.AsyncClient(
            base_url=self.cfg.backend_url,
            headers=headers,
            timeout=self.cfg.http_timeout_secs,
        ) as client:
            self._client = client
            while not self._stop.is_set():
                await self._ship_loop(client)
                # Sleep in small increments so stop() is responsive
                deadline = time.monotonic() + self.cfg.ship_interval
                while time.monotonic() < deadline and not self._stop.is_set():
                    await asyncio.sleep(0.1)
            # Final flush
            await self._ship_loop(client)

    # ── Core ship logic ───────────────────────────────────────────────────

    async def _ship_loop(self, client: httpx.AsyncClient):
        items = self._drain_queue()
        if not items:
            return

        metric_batches: List[MetricsBatch] = []
        step_events: List[StepEvent] = []

        for item in items:
            if isinstance(item, MetricsBatch):
                metric_batches.append(item)
            elif isinstance(item, StepEvent):
                step_events.append(item)

        tasks = []
        if metric_batches:
            tasks.append(self._post_with_retry(
                client, "/api/v1/ingest/metrics",
                {"run_id": self.run_id, "batches": [b.to_dict() for b in metric_batches]},
                on_success=lambda: setattr(self, "shipped_batches", self.shipped_batches + len(metric_batches)),
            ))
        if step_events:
            tasks.append(self._post_with_retry(
                client, "/api/v1/ingest/steps",
                {"run_id": self.run_id, "events": [e.to_dict() for e in step_events]},
                on_success=lambda: setattr(self, "shipped_steps", self.shipped_steps + len(step_events)),
            ))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _drain_queue(self) -> List[Any]:
        items = []
        try:
            while True:
                items.append(self.queue.get_nowait())
        except Exception:
            pass
        return items

    async def _post_with_retry(self, client: httpx.AsyncClient, path: str, payload: dict, on_success=None):
        body = json.dumps(payload)
        for attempt in range(self.cfg.http_retries + 1):
            try:
                resp = await client.post(path, content=body)
                resp.raise_for_status()
                if on_success:
                    on_success()
                return
            except httpx.HTTPStatusError as e:
                log.warning("POST %s → HTTP %d (attempt %d)", path, e.response.status_code, attempt + 1)
            except httpx.RequestError as e:
                log.warning("POST %s → network error: %s (attempt %d)", path, e, attempt + 1)

            if attempt < self.cfg.http_retries:
                backoff = self.cfg.retry_backoff_factor * (2 ** attempt)
                await asyncio.sleep(backoff)

        self.failed_requests += 1
        log.error("POST %s failed after %d attempts – payload dropped", path, self.cfg.http_retries + 1)
