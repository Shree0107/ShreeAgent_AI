"""Test setup: isolated cache/user dirs, no API keys, no network, naive forecaster."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="shreeagent_test_"))
os.environ.update({
    "CACHE_DIR": str(_tmp / "cache"), "USER_DATA_DIR": str(_tmp / "user"),
    "FORECAST_MODEL": "naive", "SENTIMENT_MODEL": "lexicon", "WHATSAPP_BACKEND": "none",
    "ANTHROPIC_API_KEY": "", "FRED_API_KEY": "", "FINNHUB_API_KEY": "", "MARKETAUX_API_KEY": "",
    "TWELVEDATA_API_KEY": "",
})

import numpy as np
import pandas as pd
import pytest

from data.providers.base import EconomicEvent, Fundamentals, NewsItem


def make_ohlcv(n: int = 400, drift: float = 0.0, seed: int = 0, start: float = 100.0, freq: str = "D",
               volume: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.01, n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.006, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.date_range("2022-01-03", periods=n, freq=freq, tz="UTC")
    vol = rng.integers(1_000, 5_000, n).astype(float) if volume else np.zeros(n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


class FakeData:
    """Stands in for DataService. Deterministic, offline."""

    def __init__(self, drift: float = 0.0):
        self.drift = drift

    def get_ohlcv(self, symbol, timeframe="1d"):
        freq = {"1h": "h", "4h": "4h", "1d": "D", "1wk": "W"}[timeframe]
        return make_ohlcv(400, self.drift, seed=hash(timeframe) % 100, freq=freq, volume=symbol.has_real_volume)

    def get_ohlcv_ticker(self, ticker, timeframe="1d"):
        return None

    def last_price(self, symbol):
        df = self.get_ohlcv(symbol)
        return {"symbol": symbol.ticker, "price": float(df.close.iloc[-1]), "change_pct": 0.1, "as_of": "",
                "source": "fake", "investing_url": symbol.investing_url}

    def get_fundamentals(self, symbol):
        return Fundamentals(symbol.ticker, {
            "name": "Test Corp", "sector": "Technology", "pe_trailing": 18.0, "pe_forward": 15.0,
            "revenue_growth": 0.2, "earnings_growth": 0.25, "profit_margin": 0.2, "roe": 0.22,
            "debt_to_equity": 30.0, "price": 100.0, "analyst_target": 125.0}, "fake")

    def get_peers(self, symbol):
        return []

    def get_news(self, symbol, days=7, limit=20):
        now = pd.Timestamp.now(tz="UTC").to_pydatetime()
        return [NewsItem("Test Corp beats estimates, shares surge", "http://x", "Wire", now),
                NewsItem("Analysts upgrade Test Corp on strong growth", "http://y", "Wire", now)]

    def get_macro_series(self, series_id):
        idx = pd.date_range("2020-01-01", periods=72, freq="MS")
        if series_id in ("DFF", "IRSTCB01GBM156N"):
            base = 5.0 if series_id == "DFF" else 4.0
            return pd.Series(np.linspace(base - 0.5, base, 72), index=idx)
        if series_id == "ECBDFR":
            return pd.Series(np.linspace(3.0, 2.0, 72), index=idx)
        return pd.Series(np.linspace(100, 115, 72), index=idx)  # CPI / GDP index (rising ~2.5%/yr)

    def upcoming_events(self, currencies, days=14):
        return [EconomicEvent(pd.Timestamp.now(tz="UTC").to_pydatetime(), "USD", "US CPI", "high", "fake")]


@pytest.fixture
def fake_data():
    return FakeData()
