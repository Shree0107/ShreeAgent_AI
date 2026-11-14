"""Direction per timeframe, sideways detection, and the multi-timeframe (MTF) agreement rule.

Per timeframe (pure function of its completed bars):
  moving averages  close vs EMA 21 / EMA 50 and the EMA 21 slope (in ATR units over 10 bars)   weight 40
  swing structure  last swing high/low labels: HH + HL = up, LH + LL = down                    weight 30
  structure break  direction of the last BOS / CHoCH (CHoCH counts half)                       weight 30
  -> score -100..100; direction "up" at >= 35, "down" at <= -35, else "neutral".

Market state (the label on every card), from the trading timeframe:
  sideways   ADX(14) < 20, or >= 70 % of the last 32 closes inside a band no wider than 2.5 x ATR, or choppy
             (efficiency ratio < 0.25: the net move over 64 bars is small compared with the distance travelled)
  otherwise  trending_up / trending_down from the timeframe direction (neutral -> sideways)

MTF rule (BUY; SELL is the mirror):
  big picture  neither Daily nor 4H points down, and at least one of them points up
               (or both neutral while the 1H trend is strong, |score| >= 70)
  today        1H points up
  setup        the 15M setup is a buy (5M is used for timing: a confirmation candle)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from analysis import indicators as ind
from analysis.structure.market import label_swings, structure_events, trend_from_labels
from analysis.structure.swings import zigzag

UP, DOWN = 35, -35
TF_NAME = {"1d": "daily chart", "4h": "4-hour chart", "1h": "1-hour chart", "15m": "15-minute chart",
           "5m": "5-minute chart"}


@dataclass
class TFBias:
    tf: str
    direction: str            # up | down | neutral
    score: float
    ma: int                   # -1 / 0 / 1
    swings: int
    breaks: float
    last_break: dict | None = None
    details: list[str] = field(default_factory=list)   # jargon allowed (Show details)
    bars: int = 0

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def sign(self) -> int:
        return 1 if self.direction == "up" else -1 if self.direction == "down" else 0


def tf_bias(df: pd.DataFrame, tf: str, swing_mult: float = 2.0) -> TFBias:
    if df is None or len(df) < 60:
        return TFBias(tf, "neutral", 0.0, 0, 0, 0.0, None, ["not enough candles"], 0 if df is None else len(df))
    d = df.tail(400)
    c = d["close"]
    e21, e50 = ind.ema(c, 21), ind.ema(c, 50)
    a = ind.atr(d)
    atr = float(a.iloc[-1]) if pd.notna(a.iloc[-1]) and a.iloc[-1] > 0 else float((d.high - d.low).mean())
    last = float(c.iloc[-1])
    slope = float(e21.iloc[-1] - e21.iloc[-11]) / atr if pd.notna(e21.iloc[-11]) else 0.0
    if last > e21.iloc[-1] > e50.iloc[-1] and slope > 0.2:
        ma = 1
    elif last < e21.iloc[-1] < e50.iloc[-1] and slope < -0.2:
        ma = -1
    else:
        ma = 0
    sw = label_swings(zigzag(d, swing_mult))
    st = trend_from_labels(sw)
    swings = 1 if st == "up" else -1 if st == "down" else 0
    events, _ = structure_events(d, sw)
    lb = events[-1] if events else None
    breaks = 0.0
    if lb is not None:
        breaks = (1.0 if lb.direction == "up" else -1.0) * (1.0 if lb.kind == "BOS" else 0.5)
    score = round(40 * ma + 30 * swings + 30 * breaks, 1)
    direction = "up" if score >= UP else "down" if score <= DOWN else "neutral"
    det = [f"EMA21 {'>' if e21.iloc[-1] > e50.iloc[-1] else '<'} EMA50, close {'above' if last > e21.iloc[-1] else 'below'} "
           f"EMA21, EMA21 slope {slope:+.2f} ATR/10 bars",
           f"swings: {st} ({' '.join(s.label for s in sw[-4:] if s.label) or 'n/a'})"]
    if lb is not None:
        det.append(f"last {lb.kind} {lb.direction} through {lb.level:.5g}")
    return TFBias(tf, direction, score, ma, swings, breaks, lb.as_dict() if lb else None, det, len(d))


def market_state(df: pd.DataFrame, lookback: int = 32, band_atr: float = 2.5, inside: float = 0.7,
                 adx_max: float = 20.0, direction: str | None = None) -> dict:
    """{'state': trending_up | trending_down | sideways, 'adx', 'range': {low, high} | None, 'inside_pct'}

    The range is the high/low of the last `lookback` bars (where the price is "stuck"), reported when sideways.
    `direction` (from tf_bias) decides up/down when the market is trending; without it the EMA 21 slope does.
    """
    if df is None or len(df) < max(lookback, 30):
        return {"state": "sideways", "adx": None, "range": None, "inside_pct": None, "reason": "not enough candles"}
    d = df.tail(300)
    a = ind.atr(d)
    atr = float(a.iloc[-1]) if pd.notna(a.iloc[-1]) and a.iloc[-1] > 0 else float((d.high - d.low).mean())
    adx_s = ind.adx(d)["adx"]
    adx = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else None
    tail = d.tail(lookback)
    mid = float(tail.close.median())
    half = band_atr * atr / 2
    inside_pct = float(np.mean((tail.close >= mid - half) & (tail.close <= mid + half)))
    low_adx = adx is not None and adx < adx_max
    contained = inside_pct >= inside
    er_tail = d.close.tail(2 * lookback)          # efficiency over a longer window, so one swing doesn't decide it
    path = float(er_tail.diff().abs().sum())
    er = abs(float(er_tail.iloc[-1] - er_tail.iloc[0])) / path if path > 0 else 0.0
    choppy = er < 0.25
    if direction is None:
        e21 = ind.ema(d.close, 21)
        slope = float(e21.iloc[-1] - e21.iloc[-11]) / atr if pd.notna(e21.iloc[-11]) else 0.0
        direction = "up" if slope > 0.3 else "down" if slope < -0.3 else "neutral"
    sideways = low_adx or contained or choppy or direction == "neutral"
    state = "sideways" if sideways else ("trending_up" if direction == "up" else "trending_down")
    rng = {"low": float(tail.low.min()), "high": float(tail.high.max())} if state == "sideways" else None
    reason = ("weak trend strength (ADX < %.0f)" % adx_max if low_adx else
              "%d%% of recent closes inside a narrow band" % round(inside_pct * 100) if contained else
              "choppy: back and forth without getting anywhere" if choppy else
              "no clear direction" if direction == "neutral" else "trend")
    return {"state": state, "adx": None if adx is None else round(adx, 1), "range": rng,
            "inside_pct": round(inside_pct, 2), "efficiency": round(er, 2), "reason": reason}


@dataclass
class MTF:
    big_picture: int          # +1 up / -1 down / 0 neutral or mixed
    today: int                # 1H sign
    biases: dict[str, TFBias]
    conflict: str | None      # plain-words description of the disagreement (None = agree)

    def allows(self, direction: str) -> bool:
        d = 1 if direction == "long" else -1
        opposed = any(self.biases[k].sign == -d for k in ("1d", "4h") if k in self.biases)
        return self.today == d and not opposed and (
            self.big_picture == d or abs(self.biases["1h"].score) >= 70)

    def lean(self) -> int:
        """Overall lean even when not tradable: sum of the weighted timeframe scores."""
        w = {"1d": 0.3, "4h": 0.3, "1h": 0.4}
        s = sum(w[k] * self.biases[k].score for k in w if k in self.biases)
        return 1 if s >= 20 else -1 if s <= -20 else 0

    def as_dict(self) -> dict:
        return {"big_picture": self.big_picture, "today": self.today, "conflict": self.conflict,
                "timeframes": {k: v.as_dict() for k, v in self.biases.items()}}


WORD = {1: "rising", -1: "falling", 0: "going sideways"}


def mtf(biases: dict[str, TFBias]) -> MTF:
    d, h4, h1 = (biases.get(k) for k in ("1d", "4h", "1h"))
    sd, s4, s1 = (b.sign if b else 0 for b in (d, h4, h1))
    if sd and s4 and sd != s4:
        big = 0
    else:
        big = sd or s4
    conflict = None
    if sd and s4 and sd != s4:
        conflict = f"The daily chart is {WORD[sd]} but the 4-hour chart is {WORD[s4]}, so the big picture is unclear."
    elif s1 == 0:
        conflict = "The 1-hour chart has no clear direction today."
    elif big and s1 != big:
        conflict = (f"The big picture (daily and 4-hour charts) is {WORD[big]}, but today's 1-hour chart is "
                    f"{WORD[s1]}. They need to agree first.")
    elif big == 0 and h1 and abs(h1.score) < 70:
        conflict = f"Today's 1-hour chart is {WORD[s1]}, but the bigger charts (daily and 4-hour) don't confirm it yet."
    return MTF(big, s1, {k: v for k, v in biases.items() if v is not None}, conflict)


def all_biases(ctx) -> dict[str, TFBias]:
    memo = ctx.cache()
    if "biases" not in memo:
        memo["biases"] = {tf: tf_bias(ctx.df(tf), tf) for tf in ("1d", "4h", "1h", "15m")}
    return memo["biases"]
