"""OANDA v20 REST: forex & metals candles with bid/ask and tick volume (free practice account works).

Docs: https://developer.oanda.com/rest-live-v20/introduction/
- Auth: personal access token (Bearer). The account id is only needed for streaming and is discovered
  from the token when OANDA_ACCOUNT_ID is empty.
- Candles are requested aligned to UTC (dailyAlignment=0, alignmentTimezone=UTC, weeks start Monday), so
  OANDA, Yahoo and the live aggregator all agree on where a candle starts.
- `volume` is tick volume (number of price changes): an activity measure, not traded volume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from config.settings import get_settings
from data.http import ProviderError, get_json
from data.providers.base import PriceProvider
from data.symbols import Symbol

log = logging.getLogger(__name__)

GRANULARITY = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D", "1wk": "W"}
HOSTS = {
    "practice": ("https://api-fxpractice.oanda.com", "https://stream-fxpractice.oanda.com"),
    "live": ("https://api-fxtrade.oanda.com", "https://stream-fxtrade.oanda.com"),
}
MAX_COUNT = 5000
ALIGN = {"dailyAlignment": 0, "alignmentTimezone": "UTC", "weeklyAlignment": "Monday"}


def instrument(symbol: Symbol) -> str:
    """'EUR/USD' -> 'EUR_USD', 'XAU/USD' -> 'XAU_USD'."""
    return symbol.ticker.replace("/", "_")


def ticker_from_instrument(name: str) -> str:
    return name.replace("_", "/")


def parse_time(s: str) -> pd.Timestamp:
    """OANDA RFC3339 with nanoseconds ('2026-11-13T22:15:00.000000000Z') -> UTC Timestamp."""
    return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC")


def candles_to_frame(candles: list[dict], include_incomplete: bool = True) -> pd.DataFrame:
    """OANDA candle JSON -> OHLCV frame (mid prices) plus bid/ask OHLC columns when present."""
    rows, idx = [], []
    for c in candles:
        if not include_incomplete and not c.get("complete", True):
            continue
        mid = c.get("mid") or {}
        bid, ask = c.get("bid") or {}, c.get("ask") or {}
        if not mid and bid and ask:  # derive mid from bid/ask
            mid = {k: (float(bid[k]) + float(ask[k])) / 2 for k in "ohlc"}
        if not mid:
            continue
        row = {"open": float(mid["o"]), "high": float(mid["h"]), "low": float(mid["l"]), "close": float(mid["c"]),
               "volume": float(c.get("volume", 0))}
        for side, d in (("bid", bid), ("ask", ask)):
            for k, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
                if k in d:
                    row[f"{side}_{name}"] = float(d[k])
        rows.append(row)
        idx.append(parse_time(c["time"]))
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="time"))
    return df[~df.index.duplicated(keep="last")].sort_index()


class OandaProvider(PriceProvider):
    name = "oanda"

    def __init__(self, token: str | None = None, environment: str | None = None, account_id: str | None = None):
        s = get_settings()
        self.token = token if token is not None else s.oanda_api_token
        self.env = (environment or s.oanda_environment or "practice").lower()
        if self.env not in HOSTS:
            raise ProviderError(f"OANDA_ENVIRONMENT must be practice or live, not {self.env!r}")
        self.rest, self.stream_host = HOSTS[self.env]
        self._account = account_id if account_id is not None else s.oanda_account_id

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def supports(self, symbol: Symbol) -> bool:
        return symbol.is_fx

    def headers(self) -> dict:
        if not self.token:
            raise ProviderError("OANDA_API_TOKEN not set")
        return {"Authorization": f"Bearer {self.token}", "Accept-Datetime-Format": "RFC3339"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        return get_json(f"{self.rest}{path}", params or {}, provider=self.name, cpm=600, headers=self.headers())

    def account_id(self) -> str:
        if not self._account:
            accounts = self._get("/v3/accounts").get("accounts") or []
            if not accounts:
                raise ProviderError("This OANDA token has no accounts")
            self._account = accounts[0]["id"]
            log.info("Using OANDA %s account %s", self.env, self._account)
        return self._account

    def candles(self, symbol: Symbol, timeframe: str, count: int = MAX_COUNT, start: datetime | None = None,
                end: datetime | None = None, price: str = "M") -> pd.DataFrame:
        """One request: up to 5000 candles. price: 'M' mid, 'BA' bid+ask, 'MBA' all three."""
        if timeframe not in GRANULARITY:
            raise ProviderError(f"Unsupported timeframe {timeframe}")
        params: dict = {"granularity": GRANULARITY[timeframe], "price": price, **ALIGN}
        if start is not None:
            params["from"] = pd.Timestamp(start).tz_convert("UTC").isoformat() if pd.Timestamp(start).tzinfo \
                else pd.Timestamp(start, tz="UTC").isoformat()
        if end is not None:
            params["to"] = pd.Timestamp(end).tz_convert("UTC").isoformat() if pd.Timestamp(end).tzinfo \
                else pd.Timestamp(end, tz="UTC").isoformat()
        if start is None or end is None:
            params["count"] = min(count, MAX_COUNT)
        js = self._get(f"/v3/instruments/{instrument(symbol)}/candles", params)
        return candles_to_frame(js.get("candles") or [])

    def history(self, symbol: Symbol, timeframe: str, start: datetime, end: datetime | None = None,
                price: str = "BA") -> pd.DataFrame:
        """Page through [start, end) 5000 candles at a time (for multi-year backtest downloads)."""
        end = pd.Timestamp(end or datetime.now(timezone.utc))
        cur = pd.Timestamp(start)
        cur = cur.tz_localize("UTC") if cur.tzinfo is None else cur
        end = end.tz_localize("UTC") if end.tzinfo is None else end
        parts = []
        while cur < end:
            df = self.candles(symbol, timeframe, count=MAX_COUNT, start=cur, price=price)
            df = df[df.index < end]
            if df.empty:
                break
            parts.append(df)
            nxt = df.index[-1] + pd.Timedelta(seconds=1)
            if nxt <= cur:
                break
            cur = nxt
        if not parts:
            return pd.DataFrame()
        out = pd.concat(parts)
        return out[~out.index.duplicated(keep="last")].sort_index()

    def get_ohlcv(self, symbol: Symbol, timeframe: str) -> pd.DataFrame:
        if not self.supports(symbol):
            raise ProviderError(f"OANDA has no data for {symbol.ticker}")
        df = self.candles(symbol, timeframe, price="M")
        if df.empty:
            raise ProviderError(f"OANDA returned no candles for {symbol.ticker} {timeframe}")
        return df[["open", "high", "low", "close", "volume"]]
