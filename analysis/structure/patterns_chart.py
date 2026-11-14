"""Chart patterns, divergences and market regime.

Chart patterns (from the latest swings):
  double top / bottom : two highs (lows) within 0.3 x ATR with a meaningful dip (rally) between; confirmed
                        once price closes beyond the neckline (the dip low / rally high)
  head & shoulders    : three highs, the middle highest by >= 0.5 ATR, shoulders within 0.6 ATR of each
                        other; inverse for lows
  triangle            : last two swing highs falling and last two lows rising (converging), or one side flat
  flag                : a strong impulse (>= 4 ATR in <= 10 bars) followed by a tight counter-drift
Divergence: price makes a higher high but RSI a lower high (bearish), or a lower low with a higher RSI low.
Regime: trending vs sideways from ADX(14) and range containment; squeeze = Bollinger Bands inside the Keltner
channel (volatility compressed: a breakout often follows).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from analysis import indicators as ind
from analysis.structure.swings import Swing, atr_series, times_of


@dataclass
class Pattern:
    name: str            # double_top | double_bottom | head_shoulders | inverse_head_shoulders | triangle | flag
    direction: str       # bullish | bearish | neutral
    points: list[dict]   # swing points making the pattern (time, price)
    neckline: float | None
    confirmed: bool
    target: float | None = None
    plain: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _pt(s: Swing) -> dict:
    return {"time": s.time, "price": s.price, "kind": s.kind}


def chart_patterns(df: pd.DataFrame, swings: list[Swing]) -> list[Pattern]:
    if len(swings) < 4:
        return []
    atr = float(atr_series(df)[-1])
    close = df["close"].to_numpy(float)
    last_close = close[-1]
    out: list[Pattern] = []
    s = swings

    # double top / bottom: last 3 swings X-Y-X
    a, b, c = s[-3], s[-2], s[-1]
    if a.kind == c.kind and abs(a.price - c.price) <= 0.3 * atr and abs(b.price - a.price) >= 1.5 * atr:
        top = a.kind == "H"
        neck = b.price
        after = close[c.idx:]
        confirmed = bool(np.any(after < neck) if top else np.any(after > neck))
        height = abs(max(a.price, c.price) - neck) if top else abs(neck - min(a.price, c.price))
        out.append(Pattern("double_top" if top else "double_bottom", "bearish" if top else "bullish",
                           [_pt(a), _pt(b), _pt(c)], neck, confirmed, neck - height if top else neck + height,
                           ("Two tops at about the same price: buyers failed twice" if top else
                            "Two bottoms at about the same price: sellers failed twice")))

    # head & shoulders: X Y X Y X with middle X extreme
    if len(s) >= 5:
        p = s[-5:]
        if p[0].kind == p[2].kind == p[4].kind:
            top = p[0].kind == "H"
            ls, hd, rs = p[0], p[2], p[4]
            head_ok = (hd.price - max(ls.price, rs.price) >= 0.5 * atr) if top else (min(ls.price, rs.price) - hd.price >= 0.5 * atr)
            if head_ok and abs(ls.price - rs.price) <= 0.6 * atr:
                neck = (p[1].price + p[3].price) / 2
                after = close[rs.idx:]
                confirmed = bool(np.any(after < neck) if top else np.any(after > neck))
                height = abs(hd.price - neck)
                out.append(Pattern("head_shoulders" if top else "inverse_head_shoulders", "bearish" if top else "bullish",
                                   [_pt(x) for x in p], neck, confirmed, neck - height if top else neck + height,
                                   "Head and shoulders: the uptrend is losing strength" if top else
                                   "Inverse head and shoulders: the downtrend is losing strength"))

    # triangle: last two highs and two lows
    hs = [x for x in s if x.kind == "H"][-2:]
    ls_ = [x for x in s if x.kind == "L"][-2:]
    if len(hs) == 2 and len(ls_) == 2:
        dh, dl = hs[1].price - hs[0].price, ls_[1].price - ls_[0].price
        flat = 0.3 * atr
        kind = None
        if dh < -flat and dl > flat:
            kind, direction = "symmetrical", "neutral"
        elif abs(dh) <= flat and dl > flat:
            kind, direction = "ascending", "bullish"
        elif dh < -flat and abs(dl) <= flat:
            kind, direction = "descending", "bearish"
        if kind:
            upper, lower = hs[1].price, ls_[1].price
            out.append(Pattern("triangle", direction, [_pt(x) for x in sorted(hs + ls_, key=lambda q: q.idx)], None,
                               bool(last_close > upper or last_close < lower), None,
                               f"Price is being squeezed into a {kind} triangle: a breakout is getting closer",
                               {"type": kind, "upper": upper, "lower": lower}))

    # flag: strong impulse then shallow pullback channel
    n = len(close)
    if n > 30:
        for L in range(5, 11):
            seg = close[n - 10 - L:n - 10]
            if len(seg) < 2:
                continue
            impulse = seg[-1] - seg[0]
            if abs(impulse) >= 4 * atr:
                tail = close[n - 10:]
                drift = tail[-1] - tail[0]
                rng = tail.max() - tail.min()
                if rng <= 0.5 * abs(impulse) and np.sign(drift) != np.sign(impulse):
                    bull = impulse > 0
                    out.append(Pattern("flag", "bullish" if bull else "bearish", [], None, False,
                                       float(last_close + impulse),
                                       "A strong move followed by a small pause (flag): the move often continues"))
                break
    return out


def divergences(df: pd.DataFrame, swings: list[Swing], lookback: int = 6) -> list[dict]:
    rsi = ind.rsi(df["close"]).to_numpy()
    out = []
    for kind in ("H", "L"):
        pts = [x for x in swings if x.kind == kind][-lookback:]
        for a, b in zip(pts, pts[1:]):
            ra, rb = rsi[a.idx], rsi[b.idx]
            if np.isnan(ra) or np.isnan(rb):
                continue
            if kind == "H" and b.price > a.price and rb < ra - 2:
                out.append({"type": "bearish", "indicator": "RSI", "from": _pt(a), "to": _pt(b),
                            "plain": "Price made a higher high but momentum is weaker: the rise may be tiring"})
            if kind == "L" and b.price < a.price and rb > ra + 2:
                out.append({"type": "bullish", "indicator": "RSI", "from": _pt(a), "to": _pt(b),
                            "plain": "Price made a lower low but momentum is stronger: the fall may be tiring"})
    return out[-4:]


def regime(df: pd.DataFrame, lookback: int = 40) -> dict:
    """{'state': trending_up | trending_down | sideways, 'adx', 'squeeze', 'range': (low, high) | None}"""
    d = ind.add_all(df, has_volume=False)
    last = d.iloc[-1]
    atr = float(last.atr_14) if pd.notna(last.atr_14) else float((df.high - df.low).mean())
    adx = float(last.adx) if pd.notna(last.adx) else None
    tail = df.tail(lookback)
    lo_q, hi_q = float(tail.close.quantile(0.05)), float(tail.close.quantile(0.95))
    contained = float(np.mean((tail.close >= lo_q) & (tail.close <= hi_q)))
    narrow = (hi_q - lo_q) <= 4.0 * atr
    ema21, ema50 = last.ema_21, last.ema_50
    slope = float(d.ema_21.iloc[-1] - d.ema_21.iloc[-10]) / atr if len(d) > 10 and pd.notna(d.ema_21.iloc[-10]) else 0.0
    if (adx is not None and adx < 20 and narrow) or (narrow and abs(slope) < 0.5 and contained >= 0.9):
        state = "sideways"
    elif pd.notna(ema21) and pd.notna(ema50) and ema21 > ema50 and slope > 0.3:
        state = "trending_up"
    elif pd.notna(ema21) and pd.notna(ema50) and ema21 < ema50 and slope < -0.3:
        state = "trending_down"
    else:
        state = "sideways"
    # Squeeze: Bollinger Bands (20, 2) inside the Keltner channel (EMA20 +- 1.5 ATR)
    kc_mid = ind.ema(df["close"], 20)
    kc_up, kc_lo = kc_mid + 1.5 * ind.atr(df, 20), kc_mid - 1.5 * ind.atr(df, 20)
    squeeze_series = (d.bb_upper < kc_up) & (d.bb_lower > kc_lo)
    squeeze = bool(squeeze_series.iloc[-1]) if pd.notna(d.bb_upper.iloc[-1]) else False
    bars_in_squeeze = 0
    if squeeze:
        for v in reversed(squeeze_series.to_numpy()):
            if not v:
                break
            bars_in_squeeze += 1
    t = times_of(df)
    return {"state": state, "adx": None if adx is None else round(adx, 1), "squeeze": squeeze,
            "squeeze_bars": bars_in_squeeze, "slope_atr": round(slope, 2),
            "range": {"low": lo_q, "high": hi_q, "t_start": int(t[-len(tail)])} if state == "sideways" else None}
