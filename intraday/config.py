"""Intraday settings as one plain object (built from config.settings, or directly in tests/backtests)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

ALL_SETUPS = ("trend_pullback", "squeeze_breakout", "range_breakout", "asian_range_breakout", "bos_retest",
              "range_reversal")
DEFAULT_SETUPS = ALL_SETUPS[:-1]          # range_reversal is off by default


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def parse_symbol_map(s: str) -> dict[str, float]:
    """'EUR/USD:2.0,default:3.0' -> {'EUR/USD': 2.0, 'default': 3.0} (the last ':' separates the value)."""
    out: dict[str, float] = {}
    for part in (s or "").split(","):
        if ":" not in part:
            continue
        k, v = part.rsplit(":", 1)
        try:
            out[k.strip().upper() if k.strip().lower() != "default" else "default"] = float(v)
        except ValueError:
            continue
    return out


@dataclass
class IntradayConfig:
    timeframe: str = "15m"
    min_rr: float = 1.5
    min_confirmations: int = 3
    blackout_minutes: int = 30
    tz: str = "Europe/Berlin"
    no_new_entries_after: time = time(18, 0)
    flat_by: time = time(21, 30)
    breakeven_at_r: float = 1.0
    max_spread: dict[str, float] = field(default_factory=lambda: {"EUR/USD": 2.0, "default": 3.0})
    typical_spread: dict[str, float] = field(default_factory=lambda: {"EUR/USD": 1.0, "default": 2.0})
    setups_enabled: tuple[str, ...] = DEFAULT_SETUPS
    daily_loss_limit: int = 2
    expiry_bars: int = 8
    refresh_delay_s: int = 20

    def max_spread_for(self, ticker: str) -> float:
        return self.max_spread.get(ticker.upper(), self.max_spread.get("default", 3.0))

    def typical_spread_for(self, ticker: str) -> float:
        return self.typical_spread.get(ticker.upper(), self.typical_spread.get("default", 2.0))

    def as_dict(self) -> dict:
        return {"timeframe": self.timeframe, "min_rr": self.min_rr, "min_confirmations": self.min_confirmations,
                "blackout_minutes": self.blackout_minutes, "timezone": self.tz,
                "no_new_entries_after": self.no_new_entries_after.strftime("%H:%M"),
                "flat_by": self.flat_by.strftime("%H:%M"), "breakeven_at_r": self.breakeven_at_r,
                "setups_enabled": list(self.setups_enabled), "daily_loss_limit": self.daily_loss_limit,
                "expiry_bars": self.expiry_bars}


def from_settings(s=None) -> IntradayConfig:
    if s is None:
        from config.settings import get_settings

        s = get_settings()
    setups = tuple(x.strip() for x in s.intraday_setups_enabled.split(",") if x.strip() in ALL_SETUPS)
    return IntradayConfig(
        timeframe=s.intraday_timeframe, min_rr=s.intraday_min_rr, min_confirmations=s.intraday_min_confirmations,
        blackout_minutes=s.news_blackout_minutes, tz=s.session_timezone,
        no_new_entries_after=parse_hhmm(s.no_new_entries_after), flat_by=parse_hhmm(s.flat_by),
        breakeven_at_r=s.breakeven_at_r, max_spread=parse_symbol_map(s.max_spread_pips) or {"default": 3.0},
        typical_spread=parse_symbol_map(s.typical_spread_pips) or {"default": 2.0},
        setups_enabled=setups, daily_loss_limit=s.daily_loss_limit, expiry_bars=s.intraday_plan_expiry_bars,
        refresh_delay_s=s.intraday_refresh_delay_s)
