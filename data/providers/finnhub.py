"""Finnhub (free key, 60 req/min): company news, earnings calendar and peers. Mostly covers US listings."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from config.settings import get_settings
from data.http import ProviderError, get_json
from data.providers.base import NewsItem, NewsProvider
from data.symbols import Symbol

_BASE = "https://finnhub.io/api/v1"


class FinnhubProvider(NewsProvider):
    name = "finnhub"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else get_settings().finnhub_api_key

    def _get(self, path: str, **params):
        if not self.api_key:
            raise ProviderError("FINNHUB_API_KEY not set")
        params["token"] = self.api_key
        return get_json(f"{_BASE}/{path}", params, provider=self.name, cpm=55)

    def get_news(self, symbol: Symbol, days: int = 7, limit: int = 20) -> list[NewsItem]:
        end = date.today()
        start = end - timedelta(days=days)
        if symbol.is_fx:
            raw = self._get("news", category="forex")
            keys = {symbol.base, symbol.quote, symbol.ticker, symbol.plain}
            raw = [n for n in raw if any(k in (n.get("headline", "") + n.get("summary", "")) for k in keys)]
        else:
            raw = self._get("company-news", symbol=symbol.plain, **{"from": start.isoformat(), "to": end.isoformat()})
        out = []
        for n in (raw or [])[:limit]:
            out.append(
                NewsItem(
                    n.get("headline", ""),
                    n.get("url", ""),
                    n.get("source", "Finnhub"),
                    datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc),
                    n.get("summary", ""),
                )
            )
        return [n for n in out if n.title]

    def peers(self, symbol: Symbol) -> list[str]:
        if symbol.market != "US":
            return []
        res = self._get("stock/peers", symbol=symbol.plain)
        return [p for p in (res or []) if p != symbol.plain][:8]

    def earnings_calendar(self, symbol: Symbol, days: int = 60) -> list[dict]:
        end = date.today() + timedelta(days=days)
        res = self._get("calendar/earnings", symbol=symbol.plain, **{"from": date.today().isoformat(), "to": end.isoformat()})
        return (res or {}).get("earningsCalendar", [])
