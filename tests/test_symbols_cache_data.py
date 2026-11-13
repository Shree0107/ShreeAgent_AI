import time

import pandas as pd
import pytest

from data.cache import Cache
from data.http import ProviderError
from data.providers.base import PriceProvider, resample_ohlcv
from data.service import DataService
from data.symbols import parse_symbol, resolve
from data.watchlist import Watchlist
from tests.conftest import make_ohlcv


@pytest.mark.parametrize("text,ticker,yahoo,cls", [
    ("EUR/USD", "EUR/USD", "EURUSD=X", "forex"),
    ("eurusd", "EUR/USD", "EURUSD=X", "forex"),
    ("GBPUSD=X", "GBP/USD", "GBPUSD=X", "forex"),
    ("XAU/USD", "XAU/USD", "GC=F", "metal"),
    ("RELIANCE.NS", "RELIANCE.NS", "RELIANCE.NS", "stock"),
    ("reliance", "RELIANCE.NS", "RELIANCE.NS", "stock"),
    ("AAPL", "AAPL", "AAPL", "stock"),
])
def test_parse_symbol(text, ticker, yahoo, cls):
    s = parse_symbol(text)
    assert s.ticker == ticker and s.yahoo == yahoo and s.asset_class == cls


def test_markets_and_links():
    assert parse_symbol("TCS.NS").market == "NSE" and parse_symbol("500325.BO").market == "BSE"
    assert parse_symbol("EUR/USD").investing_url == "https://www.investing.com/currencies/eur-usd"
    assert "search" in parse_symbol("ZZZZ").investing_url
    assert parse_symbol("TCS.NS").twelvedata == "TCS:NSE"
    assert not parse_symbol("EUR/USD").has_real_volume
    assert resolve("EUR/USD").ticker == "EUR/USD" and resolve("AAPL").ticker == "AAPL"


def test_cache_ttl_and_stale_fallback(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.set("k", {"a": 1}, ttl=0.05)
    assert c.get("k") == {"a": 1}
    time.sleep(0.1)
    assert c.get("k") is None
    # If the fetch fails after expiry, the stale value is served instead of raising.
    assert c.get_or_fetch("k", 10, lambda: (_ for _ in ()).throw(ProviderError("down"))) == {"a": 1}


class _Failing(PriceProvider):
    name = "failing"

    def get_ohlcv(self, symbol, timeframe):
        raise ProviderError("boom")


class _Working(PriceProvider):
    name = "working"

    def get_ohlcv(self, symbol, timeframe):
        return make_ohlcv(100)


def test_dataservice_falls_back_to_next_provider(tmp_path):
    ds = DataService(price_providers=[_Failing(), _Working()], cache=Cache(tmp_path / "c.sqlite"))
    df = ds.get_ohlcv(parse_symbol("AAPL"), "1d")
    assert len(df) == 100 and df.attrs["source"] == "working"
    ds2 = DataService(price_providers=[_Failing()], cache=Cache(tmp_path / "c2.sqlite"))
    with pytest.raises(ProviderError):
        ds2.get_ohlcv(parse_symbol("AAPL"), "1d")


def test_resample_4h():
    df = make_ohlcv(48, freq="h")
    out = resample_ohlcv(df, "4h")
    assert len(out) == 12
    assert out.high.iloc[0] == df.high.iloc[:4].max() and out.close.iloc[0] == df.close.iloc[3]


def test_watchlist_add_remove(tmp_path):
    wl = Watchlist(tmp_path / "wl.yaml")
    assert wl.symbols() == ["EUR/USD"]
    assert wl.add("gbpusd") == "GBP/USD"
    wl.add("RELIANCE.NS")
    wl.add("GBP/USD")  # duplicate ignored
    assert wl.symbols() == ["EUR/USD", "GBP/USD", "RELIANCE.NS"]
    wl.remove("EUR/USD")
    assert wl.symbols() == ["GBP/USD", "RELIANCE.NS"]
