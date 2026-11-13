"""Twelve Data: fallback price provider (free key: 8 req/min, 800/day). Covers forex, metals and US stocks.
NSE/BSE data needs a paid Twelve Data plan.
"""
from __future__ import annotations

import pandas as pd

from config.settings import get_settings
from data.http import ProviderError, get_json
from data.providers.base import PriceProvider, normalise_ohlcv
from data.symbols import Symbol

_URL = "https://api.twelvedata.com/time_series"
_TF = {"1h": "1h", "4h": "4h", "1d": "1day", "1wk": "1week"}


class TwelveDataProvider(PriceProvider):
    name = "twelvedata"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else get_settings().twelvedata_api_key

    def get_ohlcv(self, symbol: Symbol, timeframe: str) -> pd.DataFrame:
        if not self.api_key:
            raise ProviderError("TWELVEDATA_API_KEY not set")
        params = {
            "symbol": symbol.twelvedata,
            "interval": _TF[timeframe],
            "outputsize": 5000,
            "timezone": "UTC",
            "apikey": self.api_key,
        }
        js = get_json(_URL, params, provider=self.name, cpm=7.5)
        if js.get("status") == "error":
            raise ProviderError(f"twelvedata: {js.get('message')}")
        vals = js.get("values") or []
        if not vals:
            raise ProviderError(f"twelvedata: no data for {symbol.twelvedata}")
        df = pd.DataFrame(vals).set_index("datetime")
        return normalise_ohlcv(df)
