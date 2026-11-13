"""Signal history (SQLite) and result tracking: did each BUY/SELL hit its target, its stop, or expire?

Outcome rules (replayed from price bars after the signal time, so re-running gives the same answer):
  * Not entered yet:
      - the price closes beyond the stop        -> "cancelled" (idea became invalid before entry)
      - the price reaches target 1 first        -> "missed"    (it ran without you)
      - the price trades inside the entry zone  -> entered ("active")
      - expiry passes                           -> "expired"
  * Entered:
      - stop touched                            -> "hit_stop"   (loss)
      - target 1 touched                        -> "hit_target1" (win), then tracking continues for target 2
      - target 2 touched                        -> "hit_target2" (win)
      - stop and target in the same bar         -> counted as the stop (the cautious assumption)
      - still open after MAX_TRADE_DAYS         -> "expired" (closed by time, not counted)
Win rate = target hits / (target hits + stop hits). Expired, missed, cancelled and replaced aren't counted.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

MAX_TRADE_DAYS = 30
OPEN = ("waiting_entry", "active", "hit_target1")      # still being tracked
WINS = ("hit_target1", "hit_target2")
LOSSES = ("hit_stop",)
STATUS_TEXT = {
    "waiting_entry": "Waiting for entry", "active": "In the trade", "hit_target1": "Hit target 1 ✅",
    "hit_target2": "Hit target 2 ✅✅", "hit_stop": "Hit stop loss ❌", "expired": "Expired", "missed": "Missed (ran without entry)",
    "cancelled": "Cancelled before entry", "replaced": "Replaced by a newer signal",
}


@dataclass
class Outcome:
    status: str
    entered_at: str | None = None
    resolved_at: str | None = None
    final: bool = False


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def evaluate(sig: dict, bars: pd.DataFrame, now: datetime | None = None) -> Outcome:
    """Replay bars (open/high/low/close, UTC index) after sig['generated_at'] and return the outcome."""
    now = _ts(now or datetime.now(timezone.utc))
    long = sig["action"] == "BUY"
    lo, hi = sorted((sig["entry_low"], sig["entry_high"]))
    stop, t1, t2 = sig["stop"], sig["target1"], sig["target2"]
    gen, exp = _ts(sig["generated_at"]), _ts(sig["expires_at"])
    b = bars[bars.index > gen] if len(bars) else bars

    hit_stop = (lambda r: r.low <= stop) if long else (lambda r: r.high >= stop)
    closed_beyond_stop = (lambda r: r.close < stop) if long else (lambda r: r.close > stop)
    hit = (lambda r, t: r.high >= t) if long else (lambda r, t: r.low <= t)

    entered_at = None
    got_t1 = None
    for ts, r in b.iterrows():
        iso = ts.isoformat()
        if entered_at is None:
            if ts > exp:
                return Outcome("expired", None, exp.isoformat(), True)
            touches = r.low <= hi and r.high >= lo
            if not touches:
                if closed_beyond_stop(r):
                    return Outcome("cancelled", None, iso, True)
                if hit(r, t1):
                    return Outcome("missed", None, iso, True)
                continue
            entered_at = iso
        # in the trade (possibly from this very bar)
        if hit_stop(r):
            return Outcome("hit_target1", entered_at, iso, True) if got_t1 else Outcome("hit_stop", entered_at, iso, True)
        if got_t1 is None and hit(r, t1):
            got_t1 = iso
        if got_t1 and hit(r, t2):
            return Outcome("hit_target2", entered_at, iso, True)
        if ts > _ts(entered_at) + timedelta(days=MAX_TRADE_DAYS):
            return Outcome("hit_target1", entered_at, iso, True) if got_t1 else Outcome("expired", entered_at, iso, True)

    if entered_at is None:
        return Outcome("expired", None, exp.isoformat(), True) if now > exp else Outcome("waiting_entry")
    return Outcome("hit_target1", entered_at, got_t1) if got_t1 else Outcome("active", entered_at)


class SignalHistory:
    def __init__(self, path: Path | None = None):
        if path is None:
            from config.settings import get_settings

            path = get_settings().user_data_dir / "signals.sqlite"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, generated_at TEXT, expires_at TEXT, action TEXT,
                entry_low REAL, entry_high REAL, stop REAL, target1 REAL, target2 REAL, confidence TEXT, score REAL,
                status TEXT, entered_at TEXT, resolved_at TEXT, payload TEXT)""")
            c.execute("CREATE TABLE IF NOT EXISTS latest (symbol TEXT PRIMARY KEY, generated_at TEXT, payload TEXT)")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ---------- latest card per symbol (any action, for instant page loads) ----------
    def save_latest(self, card: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO latest VALUES (?,?,?)",
                      (card["symbol"], card["generated_at"], json.dumps(card, default=str)))

    def latest(self, symbol: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT payload FROM latest WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row["payload"]) if row else None

    # ---------- BUY/SELL history ----------
    def record(self, card: dict) -> int | None:
        """Store a BUY/SELL signal unless the same idea is already being tracked. Returns the row id or None."""
        if card.get("action") not in ("BUY", "SELL"):
            return None
        lv = card["levels"]
        tol = abs(lv["entry_mid"]) * 0.0005  # ~5 pips on EUR/USD: same idea if levels moved less than this
        with self._lock, self._conn() as c:
            rows = c.execute(f"SELECT * FROM signals WHERE symbol=? AND resolved_at IS NULL AND status IN ({','.join('?' * len(OPEN))})",
                             (card["symbol"], *OPEN)).fetchall()
            for r in rows:
                same_action = r["action"] == card["action"]
                same_levels = all(abs(r[k] - lv[k]) <= tol for k in ("stop", "target1"))
                if same_action and (r["status"] != "waiting_entry" or same_levels):
                    return None  # already in this trade, or the same pending idea
                if r["status"] == "waiting_entry":
                    c.execute("UPDATE signals SET status='replaced', resolved_at=? WHERE id=?", (card["generated_at"], r["id"]))
            cur = c.execute(
                "INSERT INTO signals (symbol, generated_at, expires_at, action, entry_low, entry_high, stop, target1, "
                "target2, confidence, score, status, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (card["symbol"], card["generated_at"], card["expires_at"], card["action"], lv["entry_low"], lv["entry_high"],
                 lv["stop"], lv["target1"], lv["target2"], card["confidence"], card["score"], "waiting_entry",
                 json.dumps(card, default=str)))
            return cur.lastrowid

    def open_signals(self, symbol: str | None = None) -> list[dict]:
        q = f"SELECT * FROM signals WHERE resolved_at IS NULL AND status IN ({','.join('?' * len(OPEN))})"
        args: list = list(OPEN)
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def update_outcomes(self, bars_for, now: datetime | None = None) -> int:
        """bars_for(symbol) -> OHLC DataFrame (hourly preferred). Returns how many signals changed."""
        changed = 0
        cache: dict[str, pd.DataFrame | None] = {}
        for s in self.open_signals():
            if s["symbol"] not in cache:
                try:
                    cache[s["symbol"]] = bars_for(s["symbol"])
                except Exception:
                    cache[s["symbol"]] = None
            bars = cache[s["symbol"]]
            if bars is None:
                continue
            o = evaluate(s, bars, now)
            if (o.status, o.entered_at, o.resolved_at if o.final else None) != (s["status"], s["entered_at"], s["resolved_at"]):
                with self._lock, self._conn() as c:
                    c.execute("UPDATE signals SET status=?, entered_at=?, resolved_at=? WHERE id=?",
                              (o.status, o.entered_at, o.resolved_at if o.final else None, s["id"]))
                changed += 1
        return changed

    def history(self, symbol: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT id, symbol, generated_at, expires_at, action, entry_low, entry_high, stop, target1, target2, " \
            "confidence, score, status, entered_at, resolved_at FROM signals"
        args: list = []
        if symbol:
            q += " WHERE symbol=?"
            args.append(symbol)
        q += " ORDER BY generated_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def win_rates(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.history(limit=100_000):
            d = out.setdefault(r["symbol"], {"wins": 0, "losses": 0, "expired": 0, "open": 0, "other": 0})
            st = r["status"]
            # hit_target1 counts as a win as soon as target 1 is reached, even while target 2 is still tracked
            if st in WINS:
                d["wins"] += 1
            elif st in LOSSES:
                d["losses"] += 1
            elif st == "expired":
                d["expired"] += 1
            elif st in OPEN:
                d["open"] += 1
            else:
                d["other"] += 1
        for d in out.values():
            n = d["wins"] + d["losses"]
            d["win_rate"] = round(100 * d["wins"] / n, 1) if n else None
        return out


def as_dict(o: Outcome) -> dict:
    return asdict(o)
