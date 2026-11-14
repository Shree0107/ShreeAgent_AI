"""The user's own chart drawings, saved per symbol (user_data/drawings.sqlite)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/drawings", tags=["drawings"])
KINDS = ("trendline", "hline", "rect", "fib", "channel", "text")


class Point(BaseModel):
    time: float
    price: float


class Drawing(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: str = Field(pattern="^(" + "|".join(KINDS) + ")$")
    points: list[Point] = Field(min_length=1, max_length=3)
    text: str | None = Field(None, max_length=500)
    color: str | None = Field(None, max_length=32)


class DrawingStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            from config.settings import get_settings

            path = get_settings().user_data_dir / "drawings.sqlite"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS drawings (symbol TEXT PRIMARY KEY, json TEXT, updated REAL)")

    def get(self, symbol: str) -> list[dict]:
        with self._lock, sqlite3.connect(self.path) as c:
            row = c.execute("SELECT json FROM drawings WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row[0]) if row else []

    def put(self, symbol: str, drawings: list[dict]) -> None:
        with self._lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO drawings VALUES (?,?,?)", (symbol, json.dumps(drawings), time.time()))


def get_store() -> DrawingStore:
    return DrawingStore()


@router.get("")
def list_drawings(symbol: str, store=Depends(get_store)):
    return store.get(symbol)


@router.put("")
def save_drawings(symbol: str, drawings: list[Drawing], store=Depends(get_store)):
    """Replace all drawings for a symbol (the chart always sends its full list)."""
    data = [d.model_dump() for d in drawings][:500]
    store.put(symbol, data)
    return data
