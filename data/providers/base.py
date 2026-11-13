"""Provider interfaces. Implement one of these to plug in a new data source."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from data.symbols import Symbol

TIMEFRAMES = ("1h", "4h", "1d", "1wk")
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: datetime
    summary: str = ""
    sentiment: float | None = None  # -1..1 if the provider supplies it


@dataclass
class EconomicEvent:
    date: datetime
    currency: str
    title: str
    impact: str = "medium"
    source: str = ""


@dataclass
class Fundamentals:
    symbol: str
    data: dict = field(default_factory=dict)  # normalised keys, see FUNDAMENTAL_KEYS
    source: str = ""


FUNDAMENTAL_KEYS = [
    "name", "sector", "industry", "currency", "market_cap", "price",
    "pe_trailing", "pe_forward", "peg", "price_to_book", "eps_trailing", "eps_forward",
    "revenue_growth", "earnings_growth", "gross_margin", "operating_margin", "profit_margin",
    "roe", "debt_to_equity", "current_ratio", "dividend_yield", "beta",
    "next_earnings_date", "fifty_two_week_high", "fifty_two_week_low", "analyst_target", "recommendation",
]


class PriceProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_ohlcv(self, symbol: Symbol, timeframe: str) -> pd.DataFrame:
        """Return a DataFrame indexed by tz-aware UTC timestamps with OHLCV_COLUMNS."""


class FundamentalsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_fundamentals(self, symbol: Symbol) -> Fundamentals: ...


class NewsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_news(self, symbol: Symbol, days: int = 7, limit: int = 20) -> list[NewsItem]: ...


class MacroProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_series(self, series_id: str, start: str | None = None) -> pd.Series: ...


def normalise_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case columns, UTC index, numeric, sorted, no all-NaN rows."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[OHLCV_COLUMNS].apply(pd.to_numeric, errors="coerce")
    idx = pd.to_datetime(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0.0)
    return df


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])
