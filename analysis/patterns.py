"""Common candlestick patterns. Each detector looks at the last 1-3 bars ending at index i."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Pattern:
    date: str
    name: str
    direction: str  # bullish | bearish | neutral

    def as_dict(self) -> dict:
        return {"date": self.date, "name": self.name, "direction": self.direction}


def _parts(row):
    body = abs(row.close - row.open)
    rng = max(row.high - row.low, 1e-12)
    upper = row.high - max(row.close, row.open)
    lower = min(row.close, row.open) - row.low
    return body, rng, upper, lower


def detect_at(df: pd.DataFrame, i: int) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    c = df.iloc[i]
    body, rng, upper, lower = _parts(c)
    bull, bear = c.close > c.open, c.close < c.open

    # Prior 5-bar drift decides whether a hammer-shaped bar is a hammer or a hanging man.
    trend = df["close"].iloc[max(0, i - 5)] - df["close"].iloc[max(0, i - 1)] if i >= 1 else 0

    if body <= 0.1 * rng:
        found.append(("Doji", "neutral"))
    if lower >= 2 * body and upper <= 0.3 * max(body, 1e-12) + 0.1 * rng and body > 0.05 * rng:
        found.append(("Hammer", "bullish") if trend > 0 else ("Hanging Man", "bearish"))
    if upper >= 2 * body and lower <= 0.3 * max(body, 1e-12) + 0.1 * rng and body > 0.05 * rng:
        found.append(("Shooting Star", "bearish") if trend < 0 else ("Inverted Hammer", "bullish"))
    if body >= 0.9 * rng:
        found.append(("Bullish Marubozu", "bullish") if bull else ("Bearish Marubozu", "bearish"))

    if i >= 1:
        p = df.iloc[i - 1]
        p_bull, p_bear = p.close > p.open, p.close < p.open
        if bull and p_bear and c.close >= p.open and c.open <= p.close:
            found.append(("Bullish Engulfing", "bullish"))
        if bear and p_bull and c.close <= p.open and c.open >= p.close:
            found.append(("Bearish Engulfing", "bearish"))
        if c.high < p.high and c.low > p.low:
            found.append(("Inside Bar", "neutral"))

    if i >= 2:
        a, b = df.iloc[i - 2], df.iloc[i - 1]
        a_body = abs(a.close - a.open)
        b_body = abs(b.close - b.open)
        if a.close < a.open and b_body < 0.5 * a_body and bull and c.close > (a.open + a.close) / 2:
            found.append(("Morning Star", "bullish"))
        if a.close > a.open and b_body < 0.5 * a_body and bear and c.close < (a.open + a.close) / 2:
            found.append(("Evening Star", "bearish"))
        if all(df.iloc[j].close > df.iloc[j].open for j in (i - 2, i - 1, i)) and a.close < b.close < c.close:
            found.append(("Three White Soldiers", "bullish"))
        if all(df.iloc[j].close < df.iloc[j].open for j in (i - 2, i - 1, i)) and a.close > b.close > c.close:
            found.append(("Three Black Crows", "bearish"))
    return found


def recent_patterns(df: pd.DataFrame, bars: int = 5) -> list[Pattern]:
    out = []
    for i in range(max(0, len(df) - bars), len(df)):
        for name, direction in detect_at(df, i):
            out.append(Pattern(df.index[i].isoformat(), name, direction))
    return out
