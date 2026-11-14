"""FastAPI application.

Run:  python -m server            (API + WebSocket on http://localhost:8000, docs at /docs)
The React app (web/) talks to /api/* and /ws. In development Vite proxies them; in Docker nginx does.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api import ws
from api.bus import get_bus
from api.jobs import JobRunner
from api.routers import app_routes, market, research, signals
from config.logging_setup import setup_logging

log = logging.getLogger(__name__)
STARTED = time.time()


def create_app() -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs = JobRunner()
        bus = get_bus()
        # Every finished job is announced on the bus, so the UI can refetch without polling.
        jobs.on_done.append(lambda j: bus.publish("job", j.public(with_result=False)))
        app.state.jobs = jobs
        log.info("API started")
        yield
        jobs.shutdown()

    app = FastAPI(title="ShreeAgent AI", version="2.0.0", lifespan=lifespan,
                  description="Analysis only. No orders are ever placed.")
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "uptime_s": round(time.time() - STARTED, 1)}

    for r in (market.router, signals.router, research.router, app_routes.router, ws.router):
        app.include_router(r)
    return app


app = create_app()
