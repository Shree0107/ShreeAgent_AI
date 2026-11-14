"""Event bus: publish/subscribe of JSON messages between the streamer, the worker and WebSocket clients.

`MemoryBus` (default, no extra software) works inside one process: `python -m server`.
A Redis-backed bus with the same interface is used when the API and worker run as separate
containers (added with the live-data phase).

Topics look like "price:EUR/USD", "candle:EUR/USD:15m", "plan:EUR/USD", "status", "job".
Subscribers match exact topics or prefixes ending in "*" (e.g. "price:*").
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


class MemoryBus:
    def __init__(self, maxsize: int = 1000):
        self._subs: list[tuple[set[str], asyncio.Queue, asyncio.AbstractEventLoop]] = []
        self._lock = threading.Lock()
        self._maxsize = maxsize

    @staticmethod
    def matches(patterns: set[str], topic: str) -> bool:
        return any(p == topic or (p.endswith("*") and topic.startswith(p[:-1])) for p in patterns)

    def subscribe(self, patterns: set[str]) -> asyncio.Queue:
        """Register a queue on the current event loop. Call unsubscribe() when done."""
        q: asyncio.Queue = asyncio.Queue(self._maxsize)
        with self._lock:
            self._subs.append((patterns, q, asyncio.get_running_loop()))
        return q

    def update(self, q: asyncio.Queue, patterns: set[str]) -> None:
        with self._lock:
            self._subs = [(patterns if qq is q else p, qq, lp) for p, qq, lp in self._subs]

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s[1] is not q]

    def publish(self, topic: str, data: Any) -> int:
        """Thread-safe: callable from worker threads as well as the event loop. Returns subscriber count."""
        msg = {"topic": topic, "data": data}
        with self._lock:
            targets = [(q, lp) for p, q, lp in self._subs if self.matches(p, topic)]
        for q, lp in targets:
            def put(q=q):
                if q.full():  # slow client: drop its oldest message rather than block everyone
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(msg)
            try:
                lp.call_soon_threadsafe(put)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)
        return len(targets)


_bus: MemoryBus | None = None


def get_bus() -> MemoryBus:
    global _bus
    if _bus is None:
        _bus = MemoryBus()
    return _bus
