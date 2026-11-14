"""Turns trade-plan events into alerts: Telegram, browser notifications (via the WebSocket) and optionally WhatsApp.

Input: bus topic `plan_event` published by the intraday engine, e.g.
  {"type": "get_ready" | "entry_triggered" | "tp_hit" | "sl_hit" | "cancelled" | ..., "symbol": "EUR/USD",
   "setup": "...", "message": "plain words", "price": 1.0951, "plan_id": "...", ...}
Output: bus topic `alert` (the web app shows it as a desktop notification) + the configured messengers.
Duplicates (same plan id + type within ALERT_DEDUPE_MINUTES) are dropped; each event type can be switched off.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable

from config.settings import get_settings

log = logging.getLogger(__name__)

EVENT_TITLES = {
    "get_ready": "🔔 Get ready",
    "entry_triggered": "🚀 Entry triggered",
    "tp_hit": "✅ Target hit",
    "tp1_hit": "✅ Target 1 hit",
    "tp2_hit": "✅ Target 2 hit",
    "sl_hit": "❌ Stop loss hit",
    "breakeven": "➖ Closed at break-even",
    "time_stop": "⏱ Time stop: close the trade",
    "cancelled": "🚫 Setup cancelled",
    "expired": "⌛ Setup expired",
}
DISCLAIMER = "Analysis only, not financial advice. Always use a stop loss."


def format_alert(ev: dict) -> tuple[str, str]:
    """(title, body) in plain words. Numbers are taken from the event as-is."""
    kind = str(ev.get("type", ""))
    title = f"{EVENT_TITLES.get(kind, '🔔 Update')}: {ev.get('symbol', '')}"
    lines = [ev.get("message") or kind.replace("_", " ").capitalize()]
    for k, label in (("entry", "Entry"), ("stop", "Stop loss"), ("target1", "Target 1"), ("target2", "Target 2")):
        if ev.get(k) is not None:
            lines.append(f"{label}: {ev[k]}")
    return title, "\n".join(lines)


class AlertDispatcher:
    def __init__(self, bus, senders: list | None = None, clock: Callable[[], float] = time.time):
        s = get_settings()
        self.bus = bus
        self.clock = clock
        self.enabled = {x.strip() for x in s.alert_events.split(",") if x.strip()}
        self.dedupe_s = s.alert_dedupe_minutes * 60
        self._seen: dict[tuple, float] = {}
        self._lock = threading.Lock()
        if senders is None:
            senders = []
            from alerts.telegram import TelegramNotifier

            tg = TelegramNotifier()
            if tg.configured:
                senders.append(tg)
            if s.alerts_whatsapp and s.whatsapp_backend != "none":
                from alerts.whatsapp import get_notifier

                senders.append(get_notifier())
        self.senders = senders
        self._task: asyncio.Task | None = None

    def wants(self, kind: str) -> bool:
        base = "tp_hit" if kind in ("tp1_hit", "tp2_hit") else kind
        return "all" in self.enabled or kind in self.enabled or base in self.enabled

    def handle(self, ev: dict) -> bool:
        """Returns True if the alert was dispatched (not filtered or a duplicate)."""
        kind = str(ev.get("type", ""))
        if not self.wants(kind):
            return False
        key = (ev.get("plan_id") or ev.get("symbol"), kind, ev.get("setup"))
        now = self.clock()
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < self.dedupe_s:
                return False
            self._seen[key] = now
            if len(self._seen) > 2000:
                self._seen = {k: v for k, v in self._seen.items() if now - v < self.dedupe_s}
        title, body = format_alert(ev)
        self.bus.publish("alert", {"title": title, "body": body, "type": kind, "symbol": ev.get("symbol"), "ts": now})
        text = f"{title}\n{body}\n\n{DISCLAIMER}"
        for s in self.senders:
            try:
                s.send(text)
            except Exception as e:  # one broken channel must not stop the others
                log.warning("Alert via %s failed: %s", getattr(s, "name", s), e)
        return True

    # ---------- run inside the API's event loop ----------
    async def run(self) -> None:
        q = self.bus.subscribe({"plan_event"})
        try:
            while True:
                msg = await q.get()
                ev = msg.get("data") or {}
                # Sending is blocking network I/O: keep the event loop free.
                await asyncio.get_running_loop().run_in_executor(None, self.handle, ev)
        finally:
            self.bus.unsubscribe(q)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self.run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
