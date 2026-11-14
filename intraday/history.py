"""Intraday plans and their outcomes in SQLite ({user_data_dir}/intraday_plans.sqlite).

Tables
  plans   one row per BUY/SELL plan: symbol, setup_type, direction, entry_type, entry, entry_low, entry_high, stop,
          tp1, tp2, created_at, ready_at, triggered_at, closed_at, outcome, pips, r_multiple, session,
          spread_at_entry, state, state_json (intraday.state.PlanState), card (JSON), updated_at
          outcome: tp1_hit | tp2_hit | sl_hit | breakeven | time_stop | cancelled | expired (NULL while open)
  latest  the newest card per symbol (any action), for instant page loads
  events  status-change events (get_ready, entry_triggered, tp_hit, sl_hit, breakeven, time_stop, cancelled, expired)
Phase 7's Performance tab reads `plans` to compare live results with the backtest.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from intraday.state import ACTIVE_STATES, OPEN_STATES, PlanState

COLS = ("symbol", "setup_type", "direction", "entry_type", "entry", "entry_low", "entry_high", "stop", "tp1", "tp2",
        "created_at", "ready_at", "triggered_at", "closed_at", "outcome", "pips", "r_multiple", "session",
        "spread_at_entry", "state")


def _iso(x):
    return x.isoformat() if isinstance(x, datetime) else x


class PlanStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            from config.settings import get_settings

            path = get_settings().user_data_dir / "intraday_plans.sqlite"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, setup_type TEXT, direction TEXT, entry_type TEXT,
                entry REAL, entry_low REAL, entry_high REAL, stop REAL, tp1 REAL, tp2 REAL, created_at TEXT,
                ready_at TEXT, triggered_at TEXT, closed_at TEXT, outcome TEXT, pips REAL, r_multiple REAL,
                session TEXT, spread_at_entry REAL, state TEXT, state_json TEXT, card TEXT, updated_at TEXT)""")
            c.execute("CREATE INDEX IF NOT EXISTS plans_symbol ON plans(symbol, closed_at)")
            c.execute("CREATE TABLE IF NOT EXISTS latest (symbol TEXT PRIMARY KEY, generated_at TEXT, payload TEXT)")
            c.execute("""CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER,
                symbol TEXT, kind TEXT, at TEXT, payload TEXT)""")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ---------- latest card ----------
    def save_latest(self, card: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO latest VALUES (?,?,?)",
                      (card["symbol"], card["generated_at"], json.dumps(card, default=str)))

    def latest(self, symbol: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT payload FROM latest WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row["payload"]) if row else None

    # ---------- plans ----------
    def create(self, card: dict, ps: PlanState, spread: float | None) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO plans (symbol, setup_type, direction, entry_type, entry, entry_low, entry_high, stop, tp1, "
                "tp2, created_at, ready_at, session, spread_at_entry, state, state_json, card, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (card["symbol"], card["setup"], card["direction"], card["entry_type"], card["entry"], card["entry_low"],
                 card["entry_high"], card["stop"], card["target1"], card["target2"], card["generated_at"],
                 _iso(ps.ready_at), card.get("session"), spread, ps.state, json.dumps(ps.as_dict()),
                 json.dumps(card, default=str), card["generated_at"]))
            return int(cur.lastrowid)

    def update(self, plan_id: int, ps: PlanState, pip: float | None, card: dict | None = None,
               spread_at_entry: float | None = None, outcome: str | None = None) -> None:
        pips = None
        if ps.exit is not None and ps.fill is not None:
            raw = (ps.exit - ps.fill) * ps.sign
            pips = round(raw / pip, 1) if pip else round(raw / ps.fill * 100, 3)   # stocks: % move
        if outcome is None and ps.closed:
            outcome = ps.state
        sets = {"state": ps.state, "state_json": json.dumps(ps.as_dict()), "ready_at": _iso(ps.ready_at),
                "triggered_at": _iso(ps.triggered_at), "closed_at": _iso(ps.closed_at), "outcome": outcome,
                "pips": pips, "r_multiple": ps.r_multiple, "updated_at": datetime.now().astimezone().isoformat()}
        if spread_at_entry is not None:
            sets["spread_at_entry"] = spread_at_entry
        if card is not None:
            sets["card"] = json.dumps(card, default=str)
        q = ", ".join(f"{k}=?" for k in sets)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE plans SET {q} WHERE id=?", (*sets.values(), plan_id))

    def open_plan(self, symbol: str) -> dict | None:
        """The newest plan for this symbol that is not closed yet (waiting, ready, in a trade or past target 1)."""
        states = OPEN_STATES + ACTIVE_STATES
        with self._lock, self._conn() as c:
            row = c.execute(f"SELECT * FROM plans WHERE symbol=? AND closed_at IS NULL AND state IN ({','.join('?' * len(states))}) "
                            "ORDER BY id DESC LIMIT 1", (symbol, *states)).fetchone()
        return self._row(row)

    def open_plans(self) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM plans WHERE closed_at IS NULL ORDER BY id").fetchall()
        return [self._row(r) for r in rows]

    def get(self, plan_id: int) -> dict | None:
        with self._lock, self._conn() as c:
            return self._row(c.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())

    @staticmethod
    def _row(row) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["state_json"] = json.loads(d["state_json"]) if d.get("state_json") else None
        d["card"] = json.loads(d["card"]) if d.get("card") else None
        return d

    def history(self, symbol: str | None = None, limit: int = 200) -> list[dict]:
        q = f"SELECT id, {', '.join(COLS)} FROM plans"
        args: list = []
        if symbol:
            q += " WHERE symbol=?"
            args.append(symbol)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def losses_today(self, now: datetime, tz: str = "Europe/Berlin") -> int:
        day = now.astimezone(ZoneInfo(tz)).date()
        n = 0
        with self._lock, self._conn() as c:
            for r in c.execute("SELECT closed_at FROM plans WHERE outcome='sl_hit' AND closed_at IS NOT NULL").fetchall():
                try:
                    if datetime.fromisoformat(r["closed_at"]).astimezone(ZoneInfo(tz)).date() == day:
                        n += 1
                except ValueError:
                    continue
        return n

    # ---------- events ----------
    def add_event(self, plan_id: int | None, symbol: str, kind: str, at: str, payload: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO events (plan_id, symbol, kind, at, payload) VALUES (?,?,?,?,?)",
                      (plan_id, symbol, kind, at, json.dumps(payload, default=str)))

    def events(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        q = "SELECT * FROM events"
        args: list = []
        if symbol:
            q += " WHERE symbol=?"
            args.append(symbol)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._conn() as c:
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in c.execute(q, args).fetchall()]

    def stats(self) -> dict:
        out: dict[str, dict] = {}
        for r in self.history(limit=100_000):
            if not r["outcome"]:
                continue
            d = out.setdefault(r["setup_type"] or "?", {"wins": 0, "losses": 0, "other": 0, "r_total": 0.0})
            if r["outcome"] in ("tp1_hit", "tp2_hit"):
                d["wins"] += 1
            elif r["outcome"] == "sl_hit":
                d["losses"] += 1
            else:
                d["other"] += 1
            d["r_total"] = round(d["r_total"] + (r["r_multiple"] or 0), 3)
        for d in out.values():
            n = d["wins"] + d["losses"]
            d["win_rate"] = round(d["wins"] / n, 3) if n else None
        return out
