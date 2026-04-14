"""
MLObs WebSocket Manager
------------------------
Manages a registry of active WebSocket connections per run_id and
broadcasts LiveUpdate messages to all subscribed clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket

log = logging.getLogger("mlobs.ws")


class ConnectionManager:
    def __init__(self):
        # run_id → set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, run_id: str):
        await websocket.accept()
        async with self._lock:
            self._connections[run_id].add(websocket)
        log.info("WS client connected to run=%s (total=%d)", run_id, self.count(run_id))

    async def disconnect(self, websocket: WebSocket, run_id: str):
        async with self._lock:
            self._connections[run_id].discard(websocket)
            if not self._connections[run_id]:
                del self._connections[run_id]
        log.info("WS client disconnected from run=%s", run_id)

    def count(self, run_id: str) -> int:
        return len(self._connections.get(run_id, set()))

    async def broadcast(self, run_id: str, payload: dict):
        """Send JSON payload to all clients subscribed to run_id."""
        connections = list(self._connections.get(run_id, set()))
        if not connections:
            return

        dead = []
        text = json.dumps(payload)
        for ws in connections:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[run_id].discard(ws)

    async def broadcast_all(self, payload: dict):
        """Broadcast to all connected clients (e.g. for global alerts)."""
        all_run_ids = list(self._connections.keys())
        await asyncio.gather(*[self.broadcast(rid, payload) for rid in all_run_ids])


# Singleton used by routers
manager = ConnectionManager()
