"""Small SQLite cache with per-entry time-to-live (TTL).

Values are pickled. The cache is local-only and written only by this app.
"""
from __future__ import annotations

import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from config.settings import get_settings

# Default TTLs (seconds) per data type
TTL = {
    "ohlcv_1h": 15 * 60,
    "ohlcv_4h": 15 * 60,
    "ohlcv_1d": 4 * 3600,
    "ohlcv_1wk": 12 * 3600,
    "fundamentals": 24 * 3600,
    "news": 60 * 60,
    "macro": 24 * 3600,
    "calendar": 12 * 3600,
    "search": 7 * 24 * 3600,
}

_MISSING = object()


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or get_settings().cache_dir / "cache.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB, expires REAL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def get(self, key: str, default: Any = None, allow_stale: bool = False) -> Any:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT v, expires FROM kv WHERE k=?", (key,)).fetchone()
        if not row:
            return default
        if row[1] < time.time() and not allow_stale:
            return default
        try:
            return pickle.loads(row[0])
        except Exception:
            return default

    def set(self, key: str, value: Any, ttl: float) -> None:
        blob = pickle.dumps(value)
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, blob, time.time() + ttl))

    def get_or_fetch(self, key: str, ttl: float, fetch: Callable[[], Any]) -> Any:
        """Return cached value, or fetch and store it. If the fetch fails, serve stale data when present."""
        val = self.get(key, _MISSING)
        if val is not _MISSING:
            return val
        try:
            val = fetch()
        except Exception:
            stale = self.get(key, _MISSING, allow_stale=True)
            if stale is not _MISSING:
                return stale
            raise
        if val is not None:
            self.set(key, val, ttl)
        return val

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM kv")


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
