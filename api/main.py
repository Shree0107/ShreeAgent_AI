"""FastAPI application.

Run:  python -m server            (API + WebSocket on http://localhost:8000, docs at /docs)
The React app (web/) talks to /api/* and /ws. In development Vite proxies them; in Docker nginx does.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api import ws
from api.bus import get_bus
from api.jobs import JobRunner
from api.routers import app_routes, drawings, market, research, signals
from api.routers import plans  # Intraday (phase 6)
from config.logging_setup import setup_logging
from data.stream.live import set_live

log = logging.getLogger(__name__)
STARTED = time.time()


def warm_up() -> None:
    """Background: import the heavy modules and pre-load watchlist prices, so the first page load after a
    restart is as fast as later ones (cold imports of yfinance/pandas paths cost ~1 s per first request)."""
    t0 = time.time()
    try:
        from data.service import get_data_service
        from data.watchlist import Watchlist
        from signals import service as _signals  # noqa: F401  (imports the analysis engine)

        data = get_data_service()
        for tk in Watchlist().symbols():
            from data.symbols import parse_symbol

            sym = parse_symbol(tk)
            if not sym:
                continue
            for tf in ("1h", "1d"):
                try:
                    data.get_ohlcv(sym, tf)
                except Exception as e:  # offline or bad ticker: the page will show the error itself
                    log.info("Warm-up %s %s skipped: %s", tk, tf, e)
        log.info("Warm-up done in %.1f s", time.time() - t0)
    except Exception as e:
        log.warning("Warm-up failed: %s", e)


def start_live(bus):
    """Start live prices for the watchlist (more symbols are added when a chart subscribes)."""
    from config.settings import get_settings
    from data.stream.live import LiveService

    if not get_settings().live_enabled:
        return None
    try:
        from data.watchlist import Watchlist

        svc = LiveService(bus)
        set_live(svc)
        threading.Thread(target=svc.start, args=(Watchlist().symbols(),), name="live-start", daemon=True).start()
        return svc
    except Exception as e:
        log.warning("Live prices disabled: %s", e)
        return None


def create_app(background: bool = True) -> FastAPI:
    """background=False (tests): no warm-up and no live price threads."""
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs = JobRunner()
        bus = get_bus()
        # Every finished job is announced on the bus, so the UI can refetch without polling.
        jobs.on_done.append(lambda j: bus.publish("job", j.public(with_result=False)))
        app.state.jobs = jobs
        live = None
        intraday = None
        if background:
            threading.Thread(target=warm_up, name="warm-up", daemon=True).start()
            live = start_live(bus)
            from intraday.scheduler import start as start_intraday  # Intraday (phase 6)

            intraday = start_intraday(app, bus)
        log.info("API started")
        yield
        if intraday:
            intraday.stop()
        jobs.shutdown()
        if live:
            live.stop()
            set_live(None)

    app = FastAPI(title="ShreeAgent AI", version="2.0.0", lifespan=lifespan,
                  description="Analysis only. No orders are ever placed.")
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "uptime_s": round(time.time() - STARTED, 1)}

    for r in (market.router, signals.router, research.router, app_routes.router, drawings.router, plans.router, ws.router):
        app.include_router(r)
    return app


app = create_app()
