"""Build candles from ticks for every timeframe at once.

Buckets are aligned to UTC (like the OANDA request alignment and Yahoo): a 15m candle starts at :00, :15,
:30, :45; 4h at 00/04/08/12/16/20 UTC; daily at 00:00 UTC; weekly on Monday 00:00 UTC.
Tick volume = number of price updates in the candle (forex has no central traded volume).
"""
from __future__ import annotations

from dataclasses import dataclass

from data.providers.base import TF_SECONDS

MONDAY_OFFSET = 4 * 86400  # 1970-01-01 was a Thursday; Monday 1970-01-05 = 4 days later


def bucket_start(ts: float, tf: str) -> int:
    sec = TF_SECONDS[tf]
    if tf == "1wk":
        return int((ts - MONDAY_OFFSET) // sec * sec + MONDAY_OFFSET)
    return int(ts // sec * sec)


@dataclass
class Bar:
    time: int     # bucket start, unix seconds UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict:
        return {"time": self.time, "open": self.open, "high": self.high, "low": self.low, "close": self.close,
                "volume": self.volume}


class CandleAggregator:
    """One instance per symbol. Feed ticks; get back ('update' | 'closed', tf, bar) events."""

    def __init__(self, timeframes: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d", "1wk")):
        self.timeframes = timeframes
        self.bars: dict[str, Bar] = {}
        self.last_ts: float = 0.0

    def seed(self, tf: str, bar: dict) -> None:
        """Start from the provider's current (incomplete) candle, so its real open/high/low are kept."""
        if tf in self.timeframes:
            self.bars[tf] = Bar(int(bar["time"]), float(bar["open"]), float(bar["high"]), float(bar["low"]),
                                float(bar["close"]), float(bar.get("volume") or 0))

    def on_tick(self, ts: float, price: float, volume: float = 1.0) -> list[tuple[str, str, dict]]:
        events: list[tuple[str, str, dict]] = []
        if ts < self.last_ts - 1:   # out-of-order tick from a reconnect: ignore, the backfill covers it
            return events
        self.last_ts = max(self.last_ts, ts)
        for tf in self.timeframes:
            start = bucket_start(ts, tf)
            cur = self.bars.get(tf)
            if cur is not None and start < cur.time:
                continue  # tick belongs to an older candle than the current (seeded) one
            if cur is not None and start > cur.time:
                events.append(("closed", tf, cur.as_dict()))
                cur = None
            if cur is None:
                cur = Bar(start, price, price, price, price, 0.0)
                self.bars[tf] = cur
            cur.high = max(cur.high, price)
            cur.low = min(cur.low, price)
            cur.close = price
            cur.volume += volume
            events.append(("update", tf, cur.as_dict()))
        return events

    def close_due(self, now: float) -> list[tuple[str, str, dict]]:
        """Close candles whose time is over even if no new tick arrived (quiet market), so 'candle close'
        triggers fire on time. The next tick then opens a fresh candle."""
        events = []
        for tf, cur in list(self.bars.items()):
            if now >= cur.time + TF_SECONDS[tf] and not (tf == "1wk" and now < cur.time + 7 * 86400):
                events.append(("closed", tf, cur.as_dict()))
                del self.bars[tf]
        return events

    def current(self, tf: str) -> dict | None:
        b = self.bars.get(tf)
        return b.as_dict() if b else None
