"""Per-timeframe technical signal + multi-timeframe combination.

Each indicator casts a weighted vote in [-1, 1]. The weighted sum is scaled to a score in [-100, 100]:
  score >= +20 -> bullish, <= -20 -> bearish, otherwise neutral.
Every vote records a plain-English reason so the signal can be explained.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from analysis import indicators as ind
from analysis.levels import pivot_points, support_resistance
from analysis.patterns import recent_patterns
from data.symbols import Symbol

log = logging.getLogger(__name__)

TF_WEIGHTS = {"1h": 0.15, "4h": 0.25, "1d": 0.35, "1wk": 0.25}
BIAS_THRESHOLD = 20


def bias_label(score: float) -> str:
    if score >= BIAS_THRESHOLD:
        return "bullish"
    if score <= -BIAS_THRESHOLD:
        return "bearish"
    return "neutral"


@dataclass
class TimeframeSignal:
    timeframe: str
    score: float
    bias: str
    trend: str
    trend_strength: str
    reasons: list[str]
    snapshot: dict
    supports: list[dict]
    resistances: list[dict]
    pivots: dict
    patterns: list[dict]
    bars: int
    last_bar: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MultiTimeframeSignal:
    symbol: str
    score: float
    bias: str
    alignment: str
    timeframes: dict[str, TimeframeSignal] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self, compact: bool = False) -> dict:
        tfs = {}
        for k, v in self.timeframes.items():
            d = v.as_dict()
            if compact:
                d.pop("pivots", None)
                d["patterns"] = d["patterns"][-4:]
            tfs[k] = d
        return {"symbol": self.symbol, "score": self.score, "bias": self.bias, "alignment": self.alignment,
                "timeframes": tfs, "errors": self.errors}


def _r(x, nd=5):
    try:
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)
    except (TypeError, ValueError):
        return None


def trend_state(d: pd.DataFrame) -> tuple[str, str]:
    """Trend direction from EMA stack and swing structure. Strength comes from ADX."""
    last = d.iloc[-1]
    c, e21, e50, e200 = last.close, last.get("ema_21"), last.get("ema_50"), last.get("ema_200")
    up = sum([c > e21, e21 > e50, (e50 > e200) if pd.notna(e200) else False])
    down = sum([c < e21, e21 < e50, (e50 < e200) if pd.notna(e200) else False])
    direction = "uptrend" if up >= 2 and up > down else "downtrend" if down >= 2 and down > up else "sideways"
    a = last.get("adx")
    strength = "n/a" if pd.isna(a) else "strong" if a >= 25 else "weak" if a < 20 else "moderate"
    return direction, strength


def analyse_frame(df: pd.DataFrame, timeframe: str, has_volume: bool = True) -> TimeframeSignal:
    if len(df) < 60:
        raise ValueError(f"Not enough bars for {timeframe} ({len(df)})")
    d = ind.add_all(df, has_volume=has_volume, intraday=timeframe in ("1h", "4h"))
    last, prev = d.iloc[-1], d.iloc[-2]
    votes: list[tuple[float, float, str]] = []  # (vote, weight, reason)

    def vote(v: float, w: float, reason: str):
        votes.append((max(-1.0, min(1.0, v)), w, reason))

    c = last.close
    # --- Trend: moving averages ---
    if pd.notna(last.ema_50):
        vote(1 if c > last.ema_50 else -1, 1.0, f"Price {'above' if c > last.ema_50 else 'below'} EMA50")
    if pd.notna(last.ema_200):
        vote(1 if c > last.ema_200 else -1, 1.5, f"Price {'above' if c > last.ema_200 else 'below'} EMA200 (long-term trend)")
    if pd.notna(last.ema_9) and pd.notna(last.ema_21):
        cross_up = prev.ema_9 <= prev.ema_21 and last.ema_9 > last.ema_21
        cross_dn = prev.ema_9 >= prev.ema_21 and last.ema_9 < last.ema_21
        if cross_up or cross_dn:
            vote(1 if cross_up else -1, 1.0, f"Fresh EMA9/21 {'bullish' if cross_up else 'bearish'} crossover")
        else:
            vote(0.5 if last.ema_9 > last.ema_21 else -0.5, 0.7, f"EMA9 {'above' if last.ema_9 > last.ema_21 else 'below'} EMA21")

    # --- ADX direction (only counts when trending) ---
    if pd.notna(last.adx) and last.adx >= 20:
        di_up = last.plus_di > last.minus_di
        vote(1 if di_up else -1, 1.0, f"ADX {last.adx:.0f} trending, {'+DI > -DI' if di_up else '-DI > +DI'}")

    # --- Momentum ---
    if pd.notna(last.macd_hist):
        rising = last.macd_hist > prev.macd_hist
        v = (0.6 if last.macd_hist > 0 else -0.6) + (0.4 if rising else -0.4)
        vote(v, 1.0, f"MACD histogram {'positive' if last.macd_hist > 0 else 'negative'} and {'rising' if rising else 'falling'}")
    if pd.notna(last.rsi_14):
        r = last.rsi_14
        if r >= 70:
            vote(-0.5, 0.8, f"RSI {r:.0f} overbought (pullback risk)")
        elif r <= 30:
            vote(0.5, 0.8, f"RSI {r:.0f} oversold (bounce potential)")
        else:
            vote((r - 50) / 20, 0.8, f"RSI {r:.0f} {'bullish' if r > 50 else 'bearish'} momentum zone")
    if pd.notna(last.stoch_k) and pd.notna(last.stoch_d):
        if last.stoch_k > 80 and last.stoch_k < last.stoch_d:
            vote(-0.7, 0.5, "Stochastic turning down from overbought")
        elif last.stoch_k < 20 and last.stoch_k > last.stoch_d:
            vote(0.7, 0.5, "Stochastic turning up from oversold")

    # --- Volatility position ---
    if pd.notna(last.bb_pctb):
        if last.bb_pctb > 1:
            vote(-0.3, 0.4, "Close above upper Bollinger Band (stretched)")
        elif last.bb_pctb < 0:
            vote(0.3, 0.4, "Close below lower Bollinger Band (stretched)")

    # --- Volume ---
    if "vwap" in d and pd.notna(last.get("vwap")):
        vote(0.6 if c > last.vwap else -0.6, 0.6, f"Price {'above' if c > last.vwap else 'below'} VWAP")
    if "vol_sma_20" in d and pd.notna(last.get("vol_sma_20")) and last.vol_sma_20 > 0:
        rel = last.volume / last.vol_sma_20
        if rel > 1.5:
            vote(0.8 if c > prev.close else -0.8, 0.6, f"Volume {rel:.1f}x average on a {'up' if c > prev.close else 'down'} bar")

    # --- Patterns ---
    pats = recent_patterns(d[["open", "high", "low", "close", "volume"]], bars=3)
    for p in pats[-3:]:
        if p.direction != "neutral":
            vote(0.5 if p.direction == "bullish" else -0.5, 0.4, f"{p.name} pattern ({p.date[:10]})")

    total_w = sum(w for _, w, _ in votes) or 1
    score = float(round(100 * sum(v * w for v, w, _ in votes) / total_w, 1))
    trend, strength = trend_state(d)
    sr = support_resistance(d)
    reasons = [r for v, w, r in sorted(votes, key=lambda x: -abs(x[0] * x[1]))]

    snapshot = {
        "close": _r(c), "change_pct": _r((c / prev.close - 1) * 100, 3),
        "ema_21": _r(last.ema_21), "ema_50": _r(last.ema_50), "ema_200": _r(last.ema_200),
        "sma_50": _r(last.sma_50), "sma_200": _r(last.sma_200),
        "rsi_14": _r(last.rsi_14, 1), "macd": _r(last.macd), "macd_signal": _r(last.macd_signal),
        "macd_hist": _r(last.macd_hist), "bb_upper": _r(last.bb_upper), "bb_lower": _r(last.bb_lower),
        "stoch_k": _r(last.stoch_k, 1), "stoch_d": _r(last.stoch_d, 1), "adx": _r(last.adx, 1),
        "atr_14": _r(last.atr_14), "atr_pct": _r(last.atr_14 / c * 100, 3),
        "vwap": _r(last.get("vwap")) if "vwap" in d else None,
    }
    return TimeframeSignal(
        timeframe=timeframe, score=score, bias=bias_label(score), trend=trend, trend_strength=strength,
        reasons=reasons[:8], snapshot=snapshot,
        supports=[l.as_dict() for l in sr["supports"]], resistances=[l.as_dict() for l in sr["resistances"]],
        pivots={k: _r(v) for k, v in pivot_points(d).items()},
        patterns=[p.as_dict() for p in pats], bars=len(d), last_bar=d.index[-1].isoformat(),
    )


def analyse_symbol(symbol: Symbol, timeframes: tuple[str, ...] = ("1h", "4h", "1d", "1wk"), data=None) -> MultiTimeframeSignal:
    """Multi-timeframe analysis. Higher timeframes carry more weight (see TF_WEIGHTS)."""
    from data.service import get_data_service

    data = data or get_data_service()
    tfs: dict[str, TimeframeSignal] = {}
    errors: dict[str, str] = {}
    for tf in timeframes:
        try:
            df = data.get_ohlcv(symbol, tf)
            tfs[tf] = analyse_frame(df, tf, has_volume=symbol.has_real_volume)
        except Exception as e:
            log.warning("TA %s %s failed: %s", symbol.ticker, tf, e)
            errors[tf] = str(e)
    if not tfs:
        raise RuntimeError(f"No timeframe could be analysed for {symbol.ticker}: {errors}")
    w = {tf: TF_WEIGHTS.get(tf, 0.2) for tf in tfs}
    score = float(round(sum(tfs[tf].score * w[tf] for tf in tfs) / sum(w.values()), 1))
    biases = {s.bias for s in tfs.values()}
    alignment = "aligned" if len(biases) == 1 else "mixed" if "neutral" in biases and len(biases) == 2 else "conflicting"
    return MultiTimeframeSignal(symbol.ticker, score, bias_label(score), alignment, tfs, errors)
