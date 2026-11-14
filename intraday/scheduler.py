"""Intraday scheduler inside the API process (started from the API lifespan only when background=True).

Every second it:
  * feeds new live prices (LiveService state: the same data published on the bus as price:{SYM}) into the
    state machine of each open plan, so Get ready / Entry triggered / TP / SL are detected in real time
  * re-runs the analysis for all watchlist symbols at every 15M candle close + INTRADAY_REFRESH_DELAY_S
    (lets the data arrive), and for one symbol after a big move (> 1 x the 15M candle range since its last run)
Heavy work goes through app.state.jobs (deduplicated by key), never in this loop.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

log = logging.getLogger(__name__)
BAR_S = 900


def next_run_after(ts: float, delay_s: int) -> float:
    """Next 15M close + delay strictly after `ts` (unix seconds)."""
    base = (ts - delay_s) // BAR_S * BAR_S + BAR_S
    return base + delay_s


class IntradayScheduler:
    def __init__(self, service, jobs, symbols_fn, live_fn, clock=None):
        self.service = service
        self.jobs = jobs
        self.symbols_fn = symbols_fn
        self.live_fn = live_fn
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._seen: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.next_run = next_run_after(self.clock(), service.cfg.refresh_delay_s)

    def submit(self, symbols: list[str], why: str):
        return self.jobs.submit("plans", f"plans:{','.join(symbols)}",
                                lambda: self.service.refresh(symbols))

    def step(self) -> None:
        now = self.clock()
        live = self.live_fn()
        syms = list(self.symbols_fn())
        if live is not None:
            for t in syms:
                st = live.states.get(t) or live.ensure(t)
                if st is None or st.mid is None or st.ts is None or st.status not in ("live", "delayed"):
                    continue
                if self._seen.get(t) == st.ts:
                    continue
                self._seen[t] = st.ts
                try:
                    self.service.on_price(t, datetime.fromtimestamp(st.ts, timezone.utc), float(st.mid))
                except Exception:
                    log.exception("plan tick failed for %s", t)
                if self.service.big_move(t, float(st.mid)):
                    self.service.last_run.pop(t, None)     # one refresh per big move
                    self.submit([t], "big move")
        if now >= self.next_run:
            self.next_run = next_run_after(now, self.service.cfg.refresh_delay_s)
            if syms:
                self.submit(syms, "candle close")

    def run(self) -> None:
        try:
            syms = list(self.symbols_fn())
            if syms:
                self.submit(syms, "start")
        except Exception:
            log.exception("initial plan refresh failed")
        while not self._stop.wait(1.0):
            try:
                self.step()
            except Exception:
                log.exception("intraday scheduler step failed")

    def start(self) -> "IntradayScheduler":
        self._thread = threading.Thread(target=self.run, name="intraday", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


def start(app, bus) -> IntradayScheduler | None:
    """Called from api/main.py lifespan (background=True only)."""
    try:
        from api.routers.plans import get_plan_service
        from data.stream.live import get_live
        from data.watchlist import Watchlist

        svc = get_plan_service()
        svc.bus = bus
        return IntradayScheduler(svc, app.state.jobs, lambda: Watchlist().symbols(), get_live).start()
    except Exception as e:
        log.warning("Intraday scheduler disabled: %s", e)
        return None
