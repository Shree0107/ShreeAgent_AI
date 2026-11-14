"""WebSocket hub at /ws.

Client -> server:  {"op": "subscribe", "topics": ["price:EUR/USD", "plan:*"]}
                   {"op": "unsubscribe", "topics": [...]}     {"op": "ping"}
All outgoing messages go through one sender task (one writer per socket).
Server -> client:  {"topic": "...", "data": {...}}   and   {"topic": "heartbeat", "data": {"ts": ...}} every 15 s
The heartbeat lets the browser detect a dead connection quickly and reconnect.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.bus import get_bus

log = logging.getLogger(__name__)
router = APIRouter()
HEARTBEAT_S = 15


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    bus = get_bus()
    topics: set[str] = {"status", "job"}
    q = bus.subscribe(topics)

    async def sender():
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                msg = {"topic": "heartbeat", "data": {"ts": time.time()}}
            await ws.send_text(json.dumps(msg, default=str))

    send_task = asyncio.create_task(sender())
    try:
        q.put_nowait({"topic": "hello", "data": {"ts": time.time(), "heartbeat_s": HEARTBEAT_S}})
        while True:
            raw = await ws.receive_text()
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            op = m.get("op")
            new = {str(t) for t in m.get("topics") or []}
            if op == "subscribe":
                topics |= new
            elif op == "unsubscribe":
                topics -= new
            elif op == "ping":
                q.put_nowait({"topic": "pong", "data": {"ts": time.time()}})
                continue
            bus.update(q, set(topics))
            q.put_nowait({"topic": "subscribed", "data": sorted(topics)})
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        bus.unsubscribe(q)
