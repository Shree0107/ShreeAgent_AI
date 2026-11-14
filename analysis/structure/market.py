"""Market structure from swings: HH/HL/LH/LL labels, break of structure (BOS), change of character (CHoCH).

  BOS   : a close beyond the last swing in the direction of the current trend (trend continues)
  CHoCH : the first close beyond the last swing *against* the trend (trend may be turning)
Trend: "up" after higher highs and higher lows, "down" after lower highs and lower lows, else "range".
Fibonacci retracements/extensions are taken from the last major swing (>= 3 x ATR).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from analysis.structure.swings import Swing, atr_series, times_of


def label_swings(swings: list[Swing]) -> list[Swing]:
    last = {"H": None, "L": None}
    for s in swings:
        prev = last[s.kind]
        if prev is not None:
            if s.kind == "H":
                s.label = "HH" if s.price > prev.price else "LH"
            else:
                s.label = "HL" if s.price > prev.price else "LL"
        last[s.kind] = s
    return swings


@dataclass
class StructureEvent:
    kind: str          # BOS | CHoCH
    direction: str     # up | down (direction of the break)
    level: float       # the swing price that was broken
    swing_time: int
    idx: int           # bar index of the breaking close
    time: int

    def as_dict(self) -> dict:
        return asdict(self)


def trend_from_labels(swings: list[Swing]) -> str:
    hs = [s.label for s in swings if s.kind == "H" and s.label][-2:]
    ls = [s.label for s in swings if s.kind == "L" and s.label][-2:]
    if hs and ls and hs[-1] == "HH" and ls[-1] == "HL":
        return "up"
    if hs and ls and hs[-1] == "LH" and ls[-1] == "LL":
        return "down"
    return "range"


def structure_events(df: pd.DataFrame, swings: list[Swing]) -> tuple[list[StructureEvent], str]:
    """Walk forward bar by bar; each swing can be broken once. Returns (events, current trend)."""
    close = df["close"].to_numpy(float)
    t = times_of(df)
    events: list[StructureEvent] = []
    trend = "range"
    broken: set[int] = set()
    for i in range(len(df)):
        known = [s for s in swings if s.confirmed_at <= i and s.idx not in broken]
        last_h = next((s for s in reversed(known) if s.kind == "H"), None)
        last_l = next((s for s in reversed(known) if s.kind == "L"), None)
        if last_h and close[i] > last_h.price:
            kind = "BOS" if trend == "up" else "CHoCH"
            events.append(StructureEvent(kind, "up", last_h.price, last_h.time, i, int(t[i])))
            broken.add(last_h.idx)
            trend = "up"
        elif last_l and close[i] < last_l.price:
            kind = "BOS" if trend == "down" else "CHoCH"
            events.append(StructureEvent(kind, "down", last_l.price, last_l.time, i, int(t[i])))
            broken.add(last_l.idx)
            trend = "down"
    return events, trend


FIB_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
FIB_EXTEND = (1.272, 1.618)


def fibonacci(df: pd.DataFrame, swings: list[Swing], min_atr: float = 3.0) -> dict | None:
    """Levels of the latest swing leg that moved at least `min_atr` x ATR.

    For an up-leg (low -> high) retracements are measured down from the high; extensions project above it.
    """
    if len(swings) < 2:
        return None
    atr = float(atr_series(df)[-1])
    for a, b in zip(reversed(swings[:-1]), reversed(swings[1:])):
        move = b.price - a.price
        if abs(move) >= min_atr * atr:
            up = move > 0
            retr = [{"ratio": r, "price": b.price - move * r} for r in FIB_RETRACE]
            ext = [{"ratio": r, "price": a.price + move * r} for r in FIB_EXTEND]
            return {"direction": "up" if up else "down", "from": a.as_dict(), "to": b.as_dict(),
                    "retracements": retr, "extensions": ext}
    return None
