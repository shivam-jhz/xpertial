"""
MLObs – WebSocket route
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ws_manager import manager

router = APIRouter(tags=["websocket"])
log = logging.getLogger("mlobs.ws_router")


@router.websocket("/ws/{run_id}")
async def websocket_run(websocket: WebSocket, run_id: str):
    """
    Real-time stream for a specific run.

    Clients subscribe by connecting; they receive LiveUpdate JSON objects
    pushed by the ingest routes. No client→server messages expected yet.
    """
    await manager.connect(websocket, run_id)
    try:
        while True:
            # Keep connection alive; ignore any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket, run_id)
    except Exception as e:
        log.warning("WS error for run %s: %s", run_id, e)
        await manager.disconnect(websocket, run_id)
