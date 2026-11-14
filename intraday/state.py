"""Plan life cycle, driven by prices (live ticks) or bars (5M bars in the backtest). Pure, no I/O.

  waiting --(price within the 'ready' distance)--> ready ("Get ready")
  waiting/ready --(entry price reached)--> triggered --(next update)--> in_trade
  in_trade --(+BREAKEVEN_AT_R reached)--> stop moved to the entry (event "breakeven_set", state unchanged)
  in_trade --(target 1)--> tp1_hit (half closed, rest runs to target 2 with the stop at the entry)
  in_trade / tp1_hit --> tp2_hit | sl_hit | breakeven | time_stop        (closed)
  waiting/ready --> cancelled (a 15M close beyond the stop before entry, or replaced) | expired (no entry in time,
                    or the no-new-entries cut-off passed)
Rules:
  * Stop and target touched in the same bar -> counted as the stop (the cautious assumption).
  * A limit buy fills when the low reaches the entry; a stop buy fills when the high reaches it (at the bar's open
    if it gapped through). Mirror for sells.
  * Results in R (risk units), half closed at target 1: sl -1R; breakeven 0R; tp1 then stop at entry 0.5 x rr1;
    tp2 0.5 x rr1 + 0.5 x rr2; time stop = the open part marked at the exit price.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

OPEN_STATES = ("waiting", "ready")
ACTIVE_STATES = ("triggered", "in_trade", "tp1_hit")
CLOSED_STATES = ("tp2_hit", "sl_hit", "breakeven", "time_stop", "cancelled", "expired")
STATE_TEXT = {
    "waiting": "Waiting", "ready": "Get ready", "triggered": "Entry triggered", "in_trade": "In trade",
    "tp1_hit": "Target 1 hit", "tp2_hit": "Target 2 hit", "sl_hit": "Stop loss hit", "breakeven": "Closed at break-even",
    "time_stop": "Closed by the time stop", "cancelled": "Cancelled", "expired": "Expired",
    "market_closed": "Market closed", "pending": "Analysing…",
}


@dataclass
class Bar:
    t: datetime              # time of the update (bar close time for bars)
    open: float
    high: float
    low: float
    close: float
    closed_bar: bool = True  # False for a live tick (cancel rules need a completed 15M close)


@dataclass
class PlanState:
    direction: str            # long | short
    entry_type: str           # limit | stop
    entry: float
    stop: float
    tp1: float
    tp2: float
    expires_at: datetime
    flat_by: datetime
    ready_distance: float
    breakeven_at_r: float = 1.0
    state: str = "waiting"
    stop_now: float | None = None
    be_moved: bool = False
    ready_at: datetime | None = None
    triggered_at: datetime | None = None
    tp1_at: datetime | None = None
    closed_at: datetime | None = None
    fill: float | None = None
    exit: float | None = None
    r_multiple: float | None = None
    checked_at: datetime | None = None   # time of the last price update applied (for catch-up from bars)
    done: bool = False        # closed (tp1_hit is also a final outcome once the rest is closed at break-even)
    history: list = field(default_factory=list)   # [(state, iso time)]

    @property
    def sign(self) -> int:
        return 1 if self.direction == "long" else -1

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def closed(self) -> bool:
        return self.done

    def rr(self, target: float) -> float:
        return abs(target - self.entry) / self.risk if self.risk else 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


@dataclass
class Event:
    kind: str                 # get_ready | entry_triggered | breakeven_set | tp_hit | sl_hit | breakeven | time_stop | cancelled | expired
    state: str
    at: datetime
    price: float | None
    target: int | None = None
    reason: str = ""


def _set(ps: PlanState, state: str, t: datetime) -> None:
    ps.state = state
    ps.history.append((state, t.isoformat()))


def _close(ps: PlanState, state: str, t: datetime, exit_price: float, r: float) -> None:
    ps.exit, ps.r_multiple, ps.closed_at, ps.done = exit_price, round(r, 3), t, True
    _set(ps, state, t)


def advance(ps: PlanState, bar: Bar) -> list[Event]:
    """Apply one price update. Returns the events it caused (empty if nothing changed)."""
    if ps.closed:
        return []
    ps.checked_at = bar.t
    ev: list[Event] = []
    s = ps.sign
    hi, lo = bar.high, bar.low

    if ps.state in OPEN_STATES:
        if bar.t >= ps.expires_at:
            _close(ps, "expired", bar.t, bar.close, 0.0)
            return [Event("expired", "expired", bar.t, bar.close, reason="not entered in time")]
        # cancelled: a completed candle closes beyond the stop (limit) / back beyond the stop (breakout) before entry
        if ps.entry_type == "stop":
            reached = (hi >= ps.entry) if s > 0 else (lo <= ps.entry)
        else:
            reached = (lo <= ps.entry) if s > 0 else (hi >= ps.entry)
        if not reached:
            beyond = (bar.close < ps.stop) if s > 0 else (bar.close > ps.stop)
            if bar.closed_bar and beyond:
                _close(ps, "cancelled", bar.t, bar.close, 0.0)
                return [Event("cancelled", "cancelled", bar.t, bar.close, reason="price closed beyond the stop before entry")]
            dist = abs(bar.close - ps.entry)
            if ps.state == "waiting" and dist <= ps.ready_distance:
                ps.ready_at = bar.t
                _set(ps, "ready", bar.t)
                ev.append(Event("get_ready", "ready", bar.t, bar.close))
            return ev
        # entry filled (gap through a stop entry -> filled at the open)
        fill = ps.entry
        if ps.entry_type == "stop" and (bar.open - ps.entry) * s > 0:
            fill = bar.open
        ps.fill, ps.triggered_at, ps.stop_now = fill, bar.t, ps.stop
        if ps.ready_at is None:
            ps.ready_at = bar.t
        _set(ps, "triggered", bar.t)
        ev.append(Event("entry_triggered", "triggered", bar.t, fill))
        return ev + _manage(ps, bar, entry_bar=True)

    if ps.state == "triggered":
        _set(ps, "in_trade", bar.t)
    return ev + _manage(ps, bar, entry_bar=False)


def _manage(ps: PlanState, bar: Bar, entry_bar: bool) -> list[Event]:
    s = ps.sign
    ev: list[Event] = []
    stop = ps.stop_now if ps.stop_now is not None else ps.stop
    hi, lo = bar.high, bar.low
    fill = ps.fill if ps.fill is not None else ps.entry
    stop_hit = (lo <= stop) if s > 0 else (hi >= stop)
    if stop_hit:                       # checked first: same-bar stop + target counts as the stop
        if ps.state == "tp1_hit":
            _close(ps, "tp1_hit", bar.t, stop, 0.5 * ps.rr(ps.tp1))   # final outcome stays "target 1 hit"
            return [Event("breakeven", "tp1_hit", bar.t, stop, reason="rest closed at break-even after target 1")]
        if ps.be_moved:
            _close(ps, "breakeven", bar.t, stop, 0.0)
            return [Event("breakeven", "breakeven", bar.t, stop)]
        _close(ps, "sl_hit", bar.t, stop, -abs(fill - stop) / ps.risk if ps.risk else -1.0)
        return [Event("sl_hit", "sl_hit", bar.t, stop)]
    if bar.t >= ps.flat_by:
        part = 0.5 if ps.state == "tp1_hit" else 1.0
        r_open = (bar.close - fill) * s / ps.risk if ps.risk else 0.0
        r = (0.5 * ps.rr(ps.tp1) if ps.state == "tp1_hit" else 0.0) + part * r_open
        _close(ps, "time_stop", bar.t, bar.close, r)
        return [Event("time_stop", "time_stop", bar.t, bar.close, reason="end of the trading day")]
    if not ps.be_moved and ps.risk:
        be_price = fill + s * ps.breakeven_at_r * ps.risk
        if (hi >= be_price) if s > 0 else (lo <= be_price):
            ps.be_moved, ps.stop_now = True, fill
            ev.append(Event("breakeven_set", ps.state, bar.t, fill))
    if ps.state != "tp1_hit" and ((hi >= ps.tp1) if s > 0 else (lo <= ps.tp1)):
        ps.tp1_at, ps.be_moved, ps.stop_now = bar.t, True, fill
        _set(ps, "tp1_hit", bar.t)
        ev.append(Event("tp_hit", "tp1_hit", bar.t, ps.tp1, target=1))
    if ps.state == "tp1_hit" and ((hi >= ps.tp2) if s > 0 else (lo <= ps.tp2)):
        _close(ps, "tp2_hit", bar.t, ps.tp2, 0.5 * ps.rr(ps.tp1) + 0.5 * ps.rr(ps.tp2))
        ev.append(Event("tp_hit", "tp2_hit", bar.t, ps.tp2, target=2))
    return ev


def tick(ps: PlanState, t: datetime, price: float) -> list[Event]:
    """A live price (not a completed candle: the 'closes beyond the stop' cancel rule waits for the candle close)."""
    if ps.closed:
        return []
    return advance(ps, Bar(t, price, price, price, price, closed_bar=False))


_DT = ("expires_at", "flat_by", "ready_at", "triggered_at", "tp1_at", "closed_at", "checked_at")


def from_dict(d: dict) -> PlanState:
    """Rebuild a PlanState saved with as_dict()."""
    kw = {k: d[k] for k in PlanState.__dataclass_fields__ if k in d}
    for k in _DT:
        if kw.get(k):
            kw[k] = datetime.fromisoformat(kw[k])
    kw["history"] = [tuple(x) for x in kw.get("history") or []]
    return PlanState(**kw)
