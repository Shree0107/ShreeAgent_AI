"""Background jobs for slow work (signal refresh, forecasts, backtests, scans).

Requests never wait on TimesFM or FinBERT: they start a job (deduplicated by key) and poll
GET /api/jobs/{id}, or read the cached result. Phase 1 uses a thread pool in the API process; the
worker process takes this over later (same interface).
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from api.serialize import clean

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    key: str
    kind: str
    status: str = "queued"          # queued | running | done | error
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    result: Any = None

    def public(self, with_result: bool = True) -> dict:
        d = asdict(self)
        if not with_result:
            d.pop("result", None)
        return clean(d)


class JobRunner:
    def __init__(self, workers: int = 2, keep: int = 200):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()
        self._keep = keep
        self.on_done: list[Callable[[Job], None]] = []

    def submit(self, kind: str, key: str, fn: Callable[[], Any]) -> Job:
        """Start fn in the background unless a job with the same key is already queued/running."""
        with self._lock:
            jid = self._by_key.get(key)
            if jid and self._jobs[jid].status in ("queued", "running"):
                return self._jobs[jid]
            job = Job(uuid.uuid4().hex[:12], key, kind)
            self._jobs[job.id] = job
            self._by_key[key] = job.id
            self._trim()
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[], Any]) -> None:
        job.status, job.started = "running", time.time()
        try:
            job.result = clean(fn())
            job.status = "done"
        except Exception as e:  # reported to the client, never crashes the API
            log.warning("Job %s (%s) failed: %s", job.kind, job.key, e)
            log.debug(traceback.format_exc())
            job.status, job.error = "error", f"{type(e).__name__}: {e}"
        finally:
            job.finished = time.time()
            for cb in list(self.on_done):
                try:
                    cb(job)
                except Exception:
                    log.exception("job callback failed")

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest(self, key: str) -> Job | None:
        jid = self._by_key.get(key)
        return self._jobs.get(jid) if jid else None

    def _trim(self) -> None:
        if len(self._jobs) <= self._keep:
            return
        done = sorted((j for j in self._jobs.values() if j.status in ("done", "error")), key=lambda j: j.created)
        for j in done[: len(self._jobs) - self._keep]:
            self._jobs.pop(j.id, None)
            if self._by_key.get(j.key) == j.id:
                self._by_key.pop(j.key, None)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
