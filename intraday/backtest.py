"""Event-driven intraday backtest: replays the live engine bar by bar on 5-minute bars. Never places orders.

Two passes, so the slow part runs once and the "tuning" choices can be compared cheaply:

1. decisions()  At every 15-minute close T: the context is built from COMPLETED bars only
   (intraday.context.build_context with now=T, after cutting each timeframe with a fast searchsorted slice), then
   intraday.plan.build_card -- the very same code the Trade Plan tab runs. Backtest results are switched off while
   doing this (probability.ignore_results) so they can't feed themselves. Outside the entry hours (weekend, quiet
   session, after NO_NEW_ENTRIES_AFTER) the engine would WAIT anyway, so no card is built there (speed).
   Each card's candidates (setup, entry, stop, targets, confirmations, gates) are kept as a Decision.

2. simulate()   Steps through the 5-minute bars. The open plan is driven by intraday.state.advance (the live plan
   state machine: same-bar stop + target = stop, break-even at +BREAKEVEN_AT_R, time stop at FLAT_BY,
   cancel/expiry); new plans come from the Decision at each 15-minute close and follow PlanService.reconcile
   (one plan per symbol; a waiting plan is kept when the same idea comes back, else cancelled/replaced; a trade in
   progress is never replaced). A plan made at T can only fill on bars that START at or after T.
   Gates applied here (they depend on the simulated trades): the daily loss limit.

Fills and costs
  * Buys fill on the ask, sells on the bid; exits the other way round. With bid/ask bars (OANDA) the spread of each
    5-minute bar is used, else mid +- half of TYPICAL_SPREAD_PIPS. This is done by shifting the plan's levels into
    mid-price terms for each bar (identical to checking bid/ask bars when the spread is constant over the bar).
  * On the bar where the entry fills, stop and targets are checked again on the exit side (the cautious way).
  * BACKTEST_SLIPPAGE_PIPS on stop-type fills (stop entries, stop losses, time stops); target (limit) exits none.
  * BACKTEST_COMMISSION_PIPS per round trip.
  * Results: half the position is closed at target 1, the rest at target 2 / break-even / stop / time stop.

Tuning choices (Params): minimum confirmations and minimum reward/risk. The cards are built once with the
loosest choice; a stricter choice keeps only candidates that also pass it (exact for confirmations, a filter on
the engine's own target 1 for reward/risk).
"""
from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from data.providers.base import TF_SECONDS
from data.symbols import Symbol
from intraday import probability
from intraday.config import IntradayConfig
from intraday.context import TFS, WINDOW, Spread, build_context
from intraday.plan import build_card
from intraday.service import plan_state_from_card
from intraday.sessions import entries_allowed, entry_cutoff, flat_time, session_key
from intraday.state import OPEN_STATES, Bar, PlanState, advance
from signals.market import pip_size

log = logging.getLogger(__name__)
FIVE = pd.Timedelta(minutes=5)
TRADE_OUTCOMES = ("tp2_hit", "tp1_hit", "sl_hit", "breakeven", "time_stop")


# ---------------------------------------------------------------- inputs
@dataclass
class Costs:
    commission_pips: float = 0.0
    slippage_pips: float = 0.2

    @classmethod
    def from_settings(cls, s=None) -> Costs:
        if s is None:
            from config.settings import get_settings

            s = get_settings()
        return cls(s.backtest_commission_pips, s.backtest_slippage_pips)


@dataclass(frozen=True)
class Params:
    min_confirmations: int
    min_rr: float

    def label(self) -> str:
        return f"{self.min_confirmations} checks, reward/risk {self.min_rr:g}"


@dataclass
class Idea:
    setup: str
    direction: str
    entry_type: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    rr1: float
    confirmations: int
    score: float
    gates: tuple[str, ...]

    def passes(self, p: Params) -> bool:
        return not self.gates and self.confirmations >= p.min_confirmations and self.rr1 >= p.min_rr - 1e-9


@dataclass
class Decision:
    t: datetime                       # the 15-minute close the decision was made at
    ideas: list[Idea] = field(default_factory=list)
    atr: float = 0.0
    spread_pips: float | None = None
    session: str = "off"
    market: str = "sideways"
    action: str = "WAIT"              # what the card said with the loosest choice
    used_until: datetime | None = None   # latest close time of any bar inside the context (look-ahead check)
    skipped: str = ""                 # why no card was built (market_closed | after_cutoff | quiet_session)

    def best(self, p: Params) -> Idea | None:
        return next((i for i in self.ideas if i.passes(p)), None)


@dataclass
class Trade:
    symbol: str
    setup: str
    direction: str
    entry_type: str
    session: str
    market: str
    created_at: datetime
    triggered_at: datetime
    closed_at: datetime
    outcome: str                      # tp2_hit | tp1_hit | sl_hit | breakeven | time_stop
    entry: float
    stop: float
    tp1: float
    tp2: float
    fill: float                       # real fill price incl. spread and slippage
    exit: float                       # real exit price of the last part
    tp1_hit: bool
    minutes_to_tp1: float | None
    pips: float                       # net result in pips after all costs (half closed at target 1)
    r: float                          # pips / planned risk in pips
    risk_pips: float
    spread_pips: float

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("created_at", "triggered_at", "closed_at"):
            d[k] = d[k].isoformat()
        return d


def base_config(cfg: IntradayConfig, grid: list[Params], setups: tuple[str, ...] | None = None) -> IntradayConfig:
    """The card config for pass 1: the loosest choice of the grid, only the setups being tested."""
    c = copy.deepcopy(cfg)
    if grid:
        c.min_confirmations = min(p.min_confirmations for p in grid)
        c.min_rr = min(p.min_rr for p in grid)
    if setups:
        c.setups_enabled = tuple(setups)
    return c


# ---------------------------------------------------------------- fast "completed bars as of now" slices
class Frames:
    """Each timeframe with its bar close times (int64 ns) for O(log n) cuts: at(now) == frames cut at `now`."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames: dict[str, pd.DataFrame] = {}
        self.ends: dict[str, np.ndarray] = {}
        for tf, df in frames.items():
            if tf not in TF_SECONDS or df is None or df.empty:
                continue
            d = df if df.index.tz is not None else df.tz_localize("UTC")
            d = d[~d.index.duplicated(keep="last")].sort_index()
            self.frames[tf] = d
            self.ends[tf] = (d.index + pd.Timedelta(seconds=TF_SECONDS[tf])).as_unit("ns").asi8

    def at(self, now: datetime) -> dict[str, pd.DataFrame]:
        ns = pd.Timestamp(now).as_unit("ns").value
        out = {}
        for tf, d in self.frames.items():
            k = int(np.searchsorted(self.ends[tf], ns, side="right"))
            out[tf] = d.iloc[max(0, k - WINDOW.get(tf, 400) - 2):k]
        return out


def _spread_at(m5: pd.DataFrame | None, ends: np.ndarray | None, now: datetime, pip: float | None) -> float | None:
    """Spread in pips of the last completed 5M bar with bid/ask, else None."""
    if m5 is None or ends is None or not pip or "ask_close" not in m5.columns:
        return None
    k = int(np.searchsorted(ends, pd.Timestamp(now).as_unit("ns").value, side="right")) - 1
    if k < 0:
        return None
    v = (m5["ask_close"].iloc[k] - m5["bid_close"].iloc[k]) / pip
    return float(v) if np.isfinite(v) and v >= 0 else None


# ---------------------------------------------------------------- pass 1: decisions
def decision_times(frames: Frames, start: datetime, end: datetime) -> list[datetime]:
    """15-minute closes in [start, end] for which 5-minute bars exist."""
    src = frames.frames.get("5m")
    if src is None:
        return []
    ends = src.index + FIVE
    ends = ends[(ends >= pd.Timestamp(start)) & (ends <= pd.Timestamp(end)) & (ends.minute % 15 == 0)]
    return [t.to_pydatetime() for t in ends.unique()]


def decide(symbol: Symbol, frames: Frames, now: datetime, cfg: IntradayConfig, news=None) -> Decision:
    """The engine's decision at `now` (a 15-minute close), from completed bars only."""
    allowed, code, _ = entries_allowed(now, symbol, cfg)
    sk = session_key(now)
    if not allowed:
        return Decision(now, session=sk, skipped=code or "")
    pip = pip_size(symbol)
    m5 = frames.frames.get("5m")
    measured = _spread_at(m5, frames.ends.get("5m"), now, pip)
    if measured is not None:
        sp = Spread(measured, True, "bid/ask of the 5-minute bar")
    elif pip:
        sp = Spread(cfg.typical_spread_for(symbol.ticker), False, "typical spread")
    else:
        sp = Spread(None, False, "")
    ctx = build_context(symbol, frames.at(now), now, cfg, sp, news.events(now) if news is not None else [])
    with probability.ignore_results():
        card = build_card(ctx, losses_today=0)
    used = [d.index[-1] + pd.Timedelta(seconds=TF_SECONDS[tf]) for tf, d in ctx.frames.items() if len(d)]
    det = card.get("details") or {}
    ideas = [Idea(c["setup"], c["direction"], c["entry_type"], float(c["entry"]), float(c["stop"]), float(c["tp1"]),
                  float(c["tp2"]), float(c["rr1"]), int(c["confirmations"]), float(c["score"]), tuple(c["gates"]))
             for c in det.get("candidates") or []]
    return Decision(now, ideas, float(det.get("atr15") or 0.0), sp.pips, sk, card.get("market") or "sideways",
                    card.get("action", "WAIT"), max(used).to_pydatetime() if used else None)


def decisions(symbol: Symbol, frames: dict[str, pd.DataFrame] | Frames, cfg: IntradayConfig, start: datetime,
              end: datetime, news=None, progress=None) -> list[Decision]:
    fr = frames if isinstance(frames, Frames) else Frames(frames)
    times = decision_times(fr, start, end)
    out = []
    for i, t in enumerate(times):
        try:
            out.append(decide(symbol, fr, t, cfg, news))
        except Exception as e:  # one bad moment must not stop a long replay
            log.debug("Decision at %s failed: %s", t, e)
            out.append(Decision(t, skipped="error"))
        if progress and (i % 50 == 0 or i == len(times) - 1):
            progress(i + 1, len(times))
    return out


# ---------------------------------------------------------------- pass 2: simulation
@dataclass
class _Open:
    ps: PlanState
    idea: Idea
    dec: Decision
    fill_eff: float | None = None     # entry price before slippage (ask for buys / bid for sells)
    hs_entry: float = 0.0


def _card_for(idea: Idea, dec: Decision, cfg: IntradayConfig, pip: float | None) -> dict:
    t = dec.t
    expires = min(t + timedelta(minutes=15 * cfg.expiry_bars), entry_cutoff(t, cfg))
    spread_price = (dec.spread_pips or 0.0) * (pip or 0.0)
    return {"direction": idea.direction, "entry_type": idea.entry_type, "entry": idea.entry, "stop": idea.stop,
            "target1": idea.tp1, "target2": idea.tp2, "expires_at": expires.isoformat(),
            "flat_by": flat_time(t, cfg).isoformat(), "ready_distance": max(0.5 * dec.atr, 2 * spread_price),
            "details": {"config": {"breakeven_at_r": cfg.breakeven_at_r}}, "generated_at": t.isoformat()}


def _shift(op: _Open, d: float) -> None:
    """Put the plan's levels into mid-price terms: d = -s*hs on the entry side, +s*hs on the exit side."""
    i, ps = op.idea, op.ps
    ps.entry, ps.stop, ps.tp1, ps.tp2 = i.entry + d, i.stop + d, i.tp1 + d, i.tp2 + d
    if ps.state not in OPEN_STATES:
        ps.fill = op.fill_eff + d
        ps.stop_now = (op.fill_eff if ps.be_moved else i.stop) + d


def simulate(symbol: Symbol, m5: pd.DataFrame, decs: list[Decision], params: Params, cfg: IntradayConfig,
             costs: Costs, start: datetime | None = None, end: datetime | None = None) -> list[Trade]:
    """Trades of plans made at decisions in [start, end]. Open trades are followed past `end` until they close."""
    pip = pip_size(symbol) or 0.0
    unit = pip if pip else 1.0
    slip = costs.slippage_pips * pip
    typ_hs = 0.5 * (cfg.typical_spread_for(symbol.ticker) if pip else 0.0) * pip
    d = m5 if m5.index.tz is not None else m5.tz_localize("UTC")
    o, h, lo, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    if "ask_close" in d.columns:
        hs_arr = ((d["ask_close"] - d["bid_close"]).to_numpy(float) / 2)
        hs_arr = np.where(np.isfinite(hs_arr) & (hs_arr >= 0), hs_arr, typ_hs)
    else:
        hs_arr = np.full(len(d), typ_hs)
    closes = list((d.index + FIVE).to_pydatetime())
    dmap = {x.t: x for x in decs if (start is None or x.t >= start) and (end is None or x.t <= end)}
    tz = ZoneInfo(cfg.tz)
    losses: dict = {}
    trades: list[Trade] = []
    op: _Open | None = None
    first = 0
    if start is not None:
        first = int(np.searchsorted(np.array([x.timestamp() for x in closes]), start.timestamp(), side="left"))

    for k in range(first, len(closes)):
        tc = closes[k]
        past_end = end is not None and tc > end
        if past_end and op is None:
            break
        if op is not None:
            s = op.ps.sign
            hs = float(hs_arr[k])
            bar = Bar(tc, o[k], h[k], lo[k], c[k], closed_bar=tc.minute % 15 == 0)
            if op.ps.state in OPEN_STATES:
                _shift(op, -s * hs)
                snap = copy.deepcopy(op.ps)
                advance(op.ps, bar)
                if op.ps.state not in OPEN_STATES and op.ps.state not in ("cancelled", "expired"):
                    # filled on this bar: redo it as "fill, then check stop/targets on the exit side"
                    fill_m = op.ps.fill
                    op.ps = snap
                    advance(op.ps, Bar(tc, fill_m, fill_m, fill_m, fill_m, closed_bar=False))
                    op.fill_eff, op.hs_entry = fill_m + s * hs, hs
                    if not op.ps.closed:
                        _shift(op, s * hs)
                        advance(op.ps, bar)
            else:
                _shift(op, s * hs)
                advance(op.ps, bar)
            if op.ps.closed:
                t = _trade(symbol, op, unit, slip, hs, costs)
                if t is not None:
                    trades.append(t)
                    if t.outcome == "sl_hit":
                        day = t.closed_at.astimezone(tz).date()
                        losses[day] = losses.get(day, 0) + 1
                op = None
        if past_end:
            continue
        dec = dmap.get(tc)
        if dec is None:
            continue
        if op is not None and op.ps.state not in OPEN_STATES:
            continue                                   # in a trade: keep it, never replace it
        idea = dec.best(params)
        if idea is not None and losses.get(tc.astimezone(tz).date(), 0) >= cfg.daily_loss_limit:
            idea = None                                # daily loss limit reached: no new plans today
        if op is not None:
            same = (idea is not None and idea.setup == op.idea.setup and idea.direction == op.idea.direction
                    and abs(idea.entry - op.idea.entry) <= 0.25 * (dec.atr or 0))
            if same:
                card = _card_for(idea, dec, cfg, pip)
                op.idea, op.dec = idea, replace(op.dec, spread_pips=dec.spread_pips)
                op.ps.expires_at = datetime.fromisoformat(card["expires_at"])
                op.ps.ready_distance = card["ready_distance"] or op.ps.ready_distance
                continue
            op = None                                  # cancelled (replaced or conditions changed)
        if idea is not None:
            op = _Open(plan_state_from_card(_card_for(idea, dec, cfg, pip)), idea, dec)
    return trades


def _trade(symbol: Symbol, op: _Open, unit: float, slip: float, hs_exit: float, costs: Costs) -> Trade | None:
    ps, i = op.ps, op.idea
    if ps.state not in TRADE_OUTCOMES or op.fill_eff is None or ps.exit is None:
        return None
    s = ps.sign
    fin = op.fill_eff + (s * slip if i.entry_type == "stop" else 0.0)
    if ps.state == "tp2_hit":
        x = i.tp2                                       # limit order: the price asked for, no slippage
    else:                                               # stop / break-even stop / time stop: market fill
        x = ps.exit - s * hs_exit - s * slip
    tp1_hit = ps.tp1_at is not None
    move = 0.5 * (i.tp1 - fin) * s + 0.5 * (x - fin) * s if tp1_hit else (x - fin) * s
    pips = move / unit - costs.commission_pips
    risk_pips = abs(i.entry - i.stop) / unit
    mins = (ps.tp1_at - ps.triggered_at).total_seconds() / 60 if tp1_hit and ps.triggered_at else None
    return Trade(symbol.ticker, i.setup, i.direction, i.entry_type, op.dec.session, op.dec.market, op.dec.t,
                 ps.triggered_at, ps.closed_at, ps.state, i.entry, i.stop, i.tp1, i.tp2, round(fin, 6), round(x, 6),
                 tp1_hit, mins, round(pips, 2), round(pips / risk_pips, 3) if risk_pips else 0.0, round(risk_pips, 2),
                 round(2 * op.hs_entry / unit, 2))


def replay(symbol: Symbol, frames: dict[str, pd.DataFrame], cfg: IntradayConfig, params: Params, costs: Costs,
           start: datetime, end: datetime, news=None) -> tuple[list[Decision], list[Trade]]:
    """Both passes for one choice of settings (used by tests and quick runs)."""
    c = copy.deepcopy(cfg)
    c.min_confirmations, c.min_rr = params.min_confirmations, params.min_rr
    fr = Frames(frames)
    decs = decisions(symbol, fr, c, start, end, news)
    return decs, simulate(symbol, fr.frames["5m"], decs, params, c, costs, start, end)


def utc(x) -> datetime:
    t = pd.Timestamp(x)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()


__all__ = ["Costs", "Params", "Idea", "Decision", "Trade", "Frames", "decide", "decisions", "simulate", "replay",
           "base_config", "TFS", "utc", "timezone"]
