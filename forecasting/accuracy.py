"""Live forecast accuracy: every forecast the Forecast tab makes is saved, then scored once its horizon has passed.

A forecast for `horizon` candles made after the candle at `last_bar_time` is scored against the next `horizon`
completed candles (by position, so weekend gaps in forex data don't matter). Scores per forecast:
  - dir_correct: did the end of the forecast (median) move the same way as the actual close? (None if flat)
  - mae / naive_mae: mean absolute error of the path, model vs "price stays the same" (price units)
  - in50 / in80: share of steps where the actual close was inside the 25-75% / 10-90% range
  - end_in50 / end_in80: whether the final close was inside those ranges
Storage: SQLite in the user data dir (forecasts.sqlite).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import get_settings

_COLS = ("id", "symbol", "tf", "horizon", "made_at", "last_close", "last_bar_time", "dates", "median", "quantiles",
         "model", "variates", "baselines", "prob_up", "scored_at", "actual", "dir_correct", "mae", "naive_mae",
         "in50", "in80", "end_in50", "end_in80")
_JSON = {"dates", "median", "quantiles", "variates", "baselines", "actual"}


def bands(quantiles) -> dict[str, np.ndarray]:
    """q10, q25, q75, q90 from the 9 stored quantile columns (q25/q75 interpolated, as in ForecastPath)."""
    q = np.asarray(quantiles, dtype=float)
    return {"q10": q[:, 0], "q25": (q[:, 1] + q[:, 2]) / 2, "q75": (q[:, 6] + q[:, 7]) / 2, "q90": q[:, -1]}


def score_forecast(rec: dict, actual) -> dict:
    """Score one forecast against the actual closes of the `horizon` candles that followed it."""
    a = np.asarray(actual, dtype=float)
    med = np.asarray(rec["median"], dtype=float)
    h = min(len(a), len(med))
    a, med = a[:h], med[:h]
    b = {k: v[:h] for k, v in bands(rec["quantiles"]).items()}
    last = float(rec["last_close"])
    da, dp = np.sign(a[-1] - last), np.sign(med[-1] - last)
    in50 = (a >= b["q25"]) & (a <= b["q75"])
    in80 = (a >= b["q10"]) & (a <= b["q90"])
    return {
        "actual": [round(float(x), 6) for x in a],
        "dir_correct": None if da == 0 or dp == 0 else bool(da == dp),
        "mae": float(np.mean(np.abs(a - med))),
        "naive_mae": float(np.mean(np.abs(a - last))),
        "in50": float(np.mean(in50)), "in80": float(np.mean(in80)),
        "end_in50": bool(in50[-1]), "end_in80": bool(in80[-1]),
    }


def actual_after(df: pd.DataFrame, last_bar_time: str, horizon: int) -> list[float] | None:
    """Closes of the `horizon` completed candles after `last_bar_time`, or None if not all have closed yet."""
    t = pd.Timestamp(last_bar_time)
    idx = df.index
    if t.tzinfo is None and idx.tz is not None:
        t = t.tz_localize(idx.tz)
    elif t.tzinfo is not None and idx.tz is None:
        t = t.tz_convert(None)
    after = df["close"][idx > t]
    if len(after) < horizon:
        return None
    return [float(x) for x in after.iloc[:horizon]]


def summarize(rows: list[dict], pip: float | None) -> dict:
    """Summary of scored forecasts. Errors are in pips (pip given) or % of price (stocks)."""
    rows = [r for r in rows if r.get("scored_at")]
    if not rows:
        return {"n": 0, "units": "pips" if pip else "%"}

    def unit(x: float, last: float) -> float:
        return x / pip if pip else x / last * 100

    dirs = [r["dir_correct"] for r in rows if r.get("dir_correct") is not None]
    mae = float(np.mean([unit(r["mae"], r["last_close"]) for r in rows]))
    naive = float(np.mean([unit(r["naive_mae"], r["last_close"]) for r in rows]))
    return {
        "n": len(rows), "units": "pips" if pip else "%",
        "direction_n": len(dirs), "direction_hits": int(sum(dirs)),
        "direction_pct": round(float(np.mean(dirs)) * 100, 1) if dirs else None,
        "mae": round(mae, 2 if pip else 3), "naive_mae": round(naive, 2 if pip else 3),
        "in50_pct": round(float(np.mean([r["in50"] for r in rows])) * 100, 1),
        "in80_pct": round(float(np.mean([r["in80"] for r in rows])) * 100, 1),
    }


class ForecastStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or get_settings().user_data_dir / "forecasts.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, tf TEXT, horizon INTEGER, made_at TEXT,
                last_close REAL, last_bar_time TEXT, dates TEXT, median TEXT, quantiles TEXT, model TEXT,
                variates TEXT, baselines TEXT, prob_up REAL, scored_at TEXT, actual TEXT, dir_correct INTEGER,
                mae REAL, naive_mae REAL, in50 REAL, in80 REAL, end_in50 INTEGER, end_in80 INTEGER,
                UNIQUE(symbol, tf, horizon, last_bar_time))""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_fc ON forecasts(symbol, tf, horizon, last_bar_time)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _row(r) -> dict:
        d = dict(zip(_COLS, r))
        for k in _JSON:
            d[k] = json.loads(d[k]) if d[k] else None
        for k in ("dir_correct", "end_in50", "end_in80"):
            d[k] = None if d[k] is None else bool(d[k])
        return d

    def save(self, rec: dict) -> None:
        """Insert, or replace the forecast for the same symbol/timeframe/horizon/candle (re-run with other inputs)."""
        vals = {k: rec.get(k) for k in _COLS if k != "id"}
        for k in _JSON:
            if vals.get(k) is not None:
                vals[k] = json.dumps(vals[k])
        keys = list(vals)
        with self._lock, self._conn() as c:
            c.execute(f"INSERT OR REPLACE INTO forecasts ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                      [vals[k] for k in keys])

    def _query(self, sql: str, args: tuple) -> list[dict]:
        with self._lock, self._conn() as c:
            return [self._row(r) for r in c.execute(f"SELECT {','.join(_COLS)} FROM forecasts {sql}", args)]

    def latest(self, symbol: str, tf: str, horizon: int) -> dict | None:
        rows = self._query("WHERE symbol=? AND tf=? AND horizon=? ORDER BY last_bar_time DESC, id DESC LIMIT 1",
                           (symbol, tf, horizon))
        return rows[0] if rows else None

    def pending(self, symbol: str, tf: str) -> list[dict]:
        return self._query("WHERE symbol=? AND tf=? AND scored_at IS NULL ORDER BY last_bar_time", (symbol, tf))

    def recent_scored(self, symbol: str, tf: str, horizon: int | None = None, limit: int = 50) -> list[dict]:
        if horizon is None:
            return self._query("WHERE symbol=? AND tf=? AND scored_at IS NOT NULL ORDER BY last_bar_time DESC LIMIT ?",
                               (symbol, tf, limit))
        return self._query("WHERE symbol=? AND tf=? AND horizon=? AND scored_at IS NOT NULL "
                           "ORDER BY last_bar_time DESC LIMIT ?", (symbol, tf, horizon, limit))

    def set_score(self, rec_id: int, score: dict, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock, self._conn() as c:
            c.execute("""UPDATE forecasts SET scored_at=?, actual=?, dir_correct=?, mae=?, naive_mae=?, in50=?, in80=?,
                         end_in50=?, end_in80=? WHERE id=?""",
                      (now.isoformat(timespec="seconds"), json.dumps(score["actual"]),
                       None if score["dir_correct"] is None else int(score["dir_correct"]), score["mae"],
                       score["naive_mae"], score["in50"], score["in80"], int(score["end_in50"]),
                       int(score["end_in80"]), rec_id))

    def score_pending(self, symbol: str, tf: str, df: pd.DataFrame, now: datetime | None = None) -> int:
        """Score every saved forecast whose candles have all closed. `df` holds completed candles only."""
        n = 0
        for rec in self.pending(symbol, tf):
            actual = actual_after(df, rec["last_bar_time"], rec["horizon"])
            if actual is None:
                continue
            self.set_score(rec["id"], score_forecast(rec, actual), now)
            n += 1
        return n


_store: ForecastStore | None = None


def get_store() -> ForecastStore:
    global _store
    if _store is None:
        _store = ForecastStore()
    return _store
