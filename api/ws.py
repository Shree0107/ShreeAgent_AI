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


def _ensure_live(topics: set[str]) -> None:
    """A chart subscribing to price:/candle: topics starts live updates for that symbol (in the background)."""
    from data.stream.live import get_live

    live = get_live()
    if not live:
        return
    for t in topics:
        kind, _, rest = t.partition(":")
        if kind in ("price", "candle", "resync") and rest and "*" not in rest:
            sym = rest.rsplit(":", 1)[0] if kind == "candle" else rest
            asyncio.get_running_loop().run_in_executor(None, live.ensure, sym)


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
        # Status is only broadcast on change, so a newly connected client gets the current snapshot now.
        from data.stream.live import get_live

        live = get_live()
        if live:
            q.put_nowait({"topic": "status", "data": live.status()})
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
                _ensure_live(new)
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
