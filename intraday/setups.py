"""Intraday setups on the 15-minute chart. Each is a pure function `detect(ctx) -> list[Candidate]`.

They read only `ctx` (completed bars as of ctx.now, plus ctx.last = the latest price), so phase 7 can replay them
bar by bar. A candidate is an *idea* with an entry, a stop and a plain-language trigger; the engine (plan.py)
then adds targets, confirmations, the gates (MTF, R:R, news, session, spread) and decides BUY / SELL / WAIT.

  trend_pullback        limit order where price should hold in the 1H trend direction (15M/1H zone, yesterday's
                        level, round number, pullback level); a 5M rejection candle is an extra confirmation
  squeeze_breakout      15M volatility squeeze (Bollinger inside Keltner >= 6 bars): stop order beyond its range
  range_breakout        15M sideways range (1.5-6 x ATR tall): stop order beyond the range
  asian_range_breakout  forex, London morning (08:00-11:00 London): stop order beyond the night's (Asian) range
  bos_retest            first return to a level the 15M chart just broke through (break of structure): limit order
  range_reversal        (off by default) fade the edge of a sideways range back to the middle
Breakout detectors return both directions; the MTF rule in the engine keeps only the one with the trend
(both are still shown as "if it breaks above / below" scenarios on WAIT cards).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from zoneinfo import ZoneInfo

import numpy as np

from analysis.patterns import detect_at
from analysis.structure.market import label_swings, structure_events
from analysis.structure.patterns_chart import regime
from analysis.structure.swings import zigzag
from intraday.bias import all_biases, market_state
from intraday.levels import asian_range, key_levels


@dataclass
class Candidate:
    setup: str
    direction: str                 # long | short
    entry_type: str                # limit (buy when price comes down to it) | stop (buy only if it breaks above)
    entry: float
    entry_low: float
    entry_high: float
    stop: float
    stop_reason: str               # plain words
    trigger: str                   # plain words, without prices (the explainer adds them)
    level_label: str = ""          # what the entry is based on, in plain words
    rng: dict | None = None        # {low, high} for range/breakout setups
    targets: list[float] | None = None   # fixed targets (range reversal); otherwise from levels
    extra_confirmations: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def sign(self) -> int:
        return 1 if self.direction == "long" else -1

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    def as_dict(self) -> dict:
        return asdict(self)


def _buf(ctx) -> float:
    return 0.1 * ctx.atr15 + ctx.spread_price


MIN_STOP_PIPS = 5.0     # forex: never a stop tighter than this (normal intraday noise)


def _min_stop(ctx) -> float:
    return max(0.5 * ctx.atr15, 3 * ctx.spread_price, MIN_STOP_PIPS * (ctx.pip or 0.0))


def _fix_stop(ctx, entry: float, stop: float, sign: int) -> float:
    """Never closer than the minimum stop distance (normal noise + spread)."""
    if (entry - stop) * sign < _min_stop(ctx):
        stop = entry - sign * _min_stop(ctx)
    return stop


# ---------------------------------------------------------------- trend pullback
def five_min_rejection(ctx, lo: float, hi: float, sign: int, bars: int = 3) -> dict | None:
    """A recent completed 5M candle that dipped into [lo, hi] and closed back strongly in the trade direction."""
    m5 = ctx.df("5m")
    if len(m5) < 5:
        return None
    for i in range(len(m5) - 1, max(len(m5) - 1 - bars, 1), -1):
        r = m5.iloc[i]
        rng = max(r.high - r.low, 1e-12)
        touched = (r.low <= hi) if sign > 0 else (r.high >= lo)
        strong = ((r.close > r.open and (r.close - r.low) / rng >= 0.6) if sign > 0 else
                  (r.close < r.open and (r.high - r.close) / rng >= 0.6))
        pats = [n for n, d in detect_at(m5, i) if d == ("bullish" if sign > 0 else "bearish")]
        if touched and (strong or pats):
            return {"key": "five_min", "plain": "A 5-minute candle bounced " + ("up" if sign > 0 else "down") +
                    " from the entry area", "detail": "5M rejection candle" + (f" ({', '.join(pats)})" if pats else ""),
                    "tf": "5m"}
    return None


def trend_pullback(ctx) -> list[Candidate]:
    b = all_biases(ctx)
    h1 = b.get("1h")
    if not h1 or h1.sign == 0 or len(ctx.main) < 60:
        return []
    sign = h1.sign
    atr, price = ctx.atr15, ctx.last
    from analysis.indicators import ema

    e21 = float(ema(ctx.main["close"], 21).iloc[-1])
    cands = [(l.low if l.low is not None else l.price - 0.15 * atr, l.high if l.high is not None else l.price + 0.15 * atr,
              l.strength, l.label) for l in key_levels(ctx) if l.kind not in ("pdc", "pivot")]
    cands.append((e21 - 0.15 * atr, e21 + 0.15 * atr, 0.8, "the short-term average price"))
    best = None
    for lo, hi, strength, label in cands:
        if hi - lo > 0.6 * atr:                          # keep the entry area small
            mid = (lo + hi) / 2
            lo, hi = mid - 0.3 * atr, mid + 0.3 * atr
        edge = hi if sign > 0 else lo                    # first price of the area that gets touched
        dist = (price - edge) * sign                     # > 0: price is still above (long) the area
        if not (-0.2 * atr <= dist <= 3.0 * atr):
            continue
        far_side = lo if sign > 0 else hi
        if (price - far_side) * sign < 0:                # already broke through the area
            continue
        score = strength - 0.5 * max(dist, 0) / atr
        if best is None or score > best[0]:
            best = (score, lo, hi, label)
    if best is None:
        return []
    _, lo, hi, label = best
    entry = hi if sign > 0 else lo
    stop = (lo - 0.3 * atr - ctx.spread_price) if sign > 0 else (hi + 0.3 * atr + ctx.spread_price)
    stop = _fix_stop(ctx, entry, stop, sign)
    c = Candidate("trend_pullback", "long" if sign > 0 else "short", "limit", entry, lo, hi, stop,
                  ("just below" if sign > 0 else "just above") + f" {label}, where the idea is proven wrong",
                  "pullback", label, details={"zone": [lo, hi], "level": label})
    rej = five_min_rejection(ctx, lo, hi, sign)
    if rej:
        c.extra_confirmations.append(rej)
    return [c]


# ---------------------------------------------------------------- breakouts
def _breakouts(ctx, setup: str, lo: float, hi: float, label: str, details: dict) -> list[Candidate]:
    buf = _buf(ctx)
    price = ctx.last
    if not (lo - 0.3 * ctx.atr15 <= price <= hi + 0.3 * ctx.atr15):
        return []          # already far outside: the breakout has happened without us
    out = []
    mid = (lo + hi) / 2
    for sign in (1, -1):
        entry = hi + buf if sign > 0 else lo - buf
        far = lo - buf if sign > 0 else hi + buf
        stop = max(far, mid) if sign > 0 else min(far, mid)
        why = ("beyond the other side of " if stop == far else "back in the middle of ") + label
        stop = _fix_stop(ctx, entry, stop, sign)
        out.append(Candidate(setup, "long" if sign > 0 else "short", "stop", entry, entry, entry, stop,
                             why + ": then the breakout has failed", "breakout", label,
                             {"low": lo, "high": hi}, details=dict(details)))
    return out


def squeeze_breakout(ctx) -> list[Candidate]:
    d = ctx.main
    if len(d) < 60:
        return []
    r = regime(d.tail(200))
    if not r["squeeze"] or r["squeeze_bars"] < 6:
        return []
    n = max(r["squeeze_bars"], 8)
    t = d.tail(n)
    lo, hi = float(t.low.min()), float(t.high.max())
    return _breakouts(ctx, "squeeze_breakout", lo, hi, "the quiet range of the last hours",
                      {"squeeze_bars": r["squeeze_bars"], "range": [lo, hi]})


def range_breakout(ctx) -> list[Candidate]:
    st = market_state(ctx.main, direction=all_biases(ctx)["15m"].direction)
    if st["state"] != "sideways" or not st["range"]:
        return []
    lo, hi = st["range"]["low"], st["range"]["high"]
    h = hi - lo
    if not (1.5 * ctx.atr15 <= h <= 6 * ctx.atr15):
        return []
    return _breakouts(ctx, "range_breakout", lo, hi, "the sideways range", {"range": [lo, hi], "adx": st["adx"]})


def asian_range_breakout(ctx) -> list[Candidate]:
    if not ctx.symbol.is_fx:
        return []
    ldn = ctx.now.astimezone(ZoneInfo("Europe/London"))
    if ldn.weekday() >= 5 or not (8 <= ldn.hour < 11):
        return []
    ar = asian_range(ctx.main, ctx.now)
    if not ar or not ar["complete"]:
        return []
    h = ar["high"] - ar["low"]
    if not (1.0 * ctx.atr15 <= h <= 5 * ctx.atr15):
        return []
    return _breakouts(ctx, "asian_range_breakout", ar["low"], ar["high"], "the night's (Asian session) range",
                      {"asian_range": [ar["low"], ar["high"]]})


# ---------------------------------------------------------------- break of structure retest
def bos_retest(ctx) -> list[Candidate]:
    d = ctx.main.tail(300)
    if len(d) < 60:
        return []
    atr = ctx.atr15
    sw = label_swings(zigzag(d, 2.0))
    events, _ = structure_events(d, sw)
    if not events:
        return []
    ev = events[-1]
    n = len(d)
    if n - 1 - ev.idx > 24 or n - 1 - ev.idx < 2:
        return []
    sign = 1 if ev.direction == "up" else -1
    L = ev.level
    after = d.iloc[ev.idx + 1:]
    lows, highs = after.low.to_numpy(float), after.high.to_numpy(float)
    touched = np.any(lows <= L + 0.1 * atr) if sign > 0 else np.any(highs >= L - 0.1 * atr)
    if touched:
        return []          # only the FIRST retest is traded
    price = ctx.last
    if not (0 <= (price - L) * sign <= 3 * atr):
        return []
    lo, hi = (L - 0.1 * atr, L + 0.2 * atr) if sign > 0 else (L - 0.2 * atr, L + 0.1 * atr)
    entry = hi if sign > 0 else lo
    prior = [s for s in sw if s.kind == ("L" if sign > 0 else "H") and s.idx < ev.idx]
    stop = L - sign * 1.0 * atr
    if prior and 0 < (L - prior[-1].price) * sign <= 2 * atr:
        stop = prior[-1].price - sign * (0.1 * atr + ctx.spread_price)
    stop = _fix_stop(ctx, entry, stop, sign)
    return [Candidate("bos_retest", "long" if sign > 0 else "short", "limit", entry, lo, hi, stop,
                      ("below" if sign > 0 else "above") + " the last turning point before the break",
                      "retest", "the level the price just broke " + ("above" if sign > 0 else "below"),
                      details={"event": ev.as_dict()})]


# ---------------------------------------------------------------- range reversal (off by default)
def range_reversal(ctx) -> list[Candidate]:
    st = market_state(ctx.main, direction=all_biases(ctx)["15m"].direction)
    if st["state"] != "sideways" or not st["range"]:
        return []
    lo, hi = st["range"]["low"], st["range"]["high"]
    atr, price = ctx.atr15, ctx.last
    if not (2 * atr <= hi - lo <= 6 * atr):
        return []
    mid = (lo + hi) / 2
    out = []
    if abs(price - lo) <= 0.6 * atr:
        e = lo + 0.1 * atr
        out.append(Candidate("range_reversal", "long", "limit", e, lo, lo + 0.2 * atr, _fix_stop(ctx, e, lo - 0.5 * atr, 1),
                             "below the bottom of the sideways range", "reversal", "the bottom of the sideways range",
                             {"low": lo, "high": hi}, targets=[mid, hi - 0.1 * atr]))
    if abs(hi - price) <= 0.6 * atr:
        e = hi - 0.1 * atr
        out.append(Candidate("range_reversal", "short", "limit", e, hi - 0.2 * atr, hi, _fix_stop(ctx, e, hi + 0.5 * atr, -1),
                             "above the top of the sideways range", "reversal", "the top of the sideways range",
                             {"low": lo, "high": hi}, targets=[mid, lo + 0.1 * atr]))
    return out


DETECTORS = {"trend_pullback": trend_pullback, "squeeze_breakout": squeeze_breakout, "range_breakout": range_breakout,
             "asian_range_breakout": asian_range_breakout, "bos_retest": bos_retest, "range_reversal": range_reversal}

SETUP_NAME = {"trend_pullback": "Pullback in the trend", "squeeze_breakout": "Breakout after a quiet period",
              "range_breakout": "Breakout from a sideways range", "asian_range_breakout": "Breakout of the night's range",
              "bos_retest": "Retest after a breakout", "range_reversal": "Bounce inside a sideways range"}


def detect_all(ctx, enabled: tuple[str, ...] | None = None) -> list[Candidate]:
    out: list[Candidate] = []
    for name, fn in DETECTORS.items():
        if enabled is not None and name not in enabled:
            continue
        try:
            out += fn(ctx)
        except Exception as e:  # one broken detector must not hide the others
            import logging

            logging.getLogger(__name__).warning("setup %s failed: %s", name, e)
    return out
