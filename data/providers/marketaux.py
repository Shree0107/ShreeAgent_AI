"""Marketaux (free key, 100 req/day): financial news with per-entity sentiment. Covers US and India."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from config.settings import get_settings
from data.http import ProviderError, get_json
from data.providers.base import NewsItem, NewsProvider
from data.symbols import Symbol

_URL = "https://api.marketaux.com/v1/news/all"


class MarketauxProvider(NewsProvider):
    name = "marketaux"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else get_settings().marketaux_api_key

    def get_news(self, symbol: Symbol, days: int = 7, limit: int = 20) -> list[NewsItem]:
        if not self.api_key:
            raise ProviderError("MARKETAUX_API_KEY not set")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
        params = {"api_token": self.api_key, "language": "en", "published_after": since, "limit": min(limit, 3)}
        if symbol.is_fx:
            params["search"] = f'"{symbol.ticker}" | "{symbol.plain}"'
        else:
            params["symbols"] = symbol.ticker if symbol.market != "US" else symbol.plain
            params["filter_entities"] = "true"
        js = get_json(_URL, params, provider=self.name, cpm=10)
        out = []
        for a in js.get("data") or []:
            ents = a.get("entities") or []
            scores = [e.get("sentiment_score") for e in ents if e.get("sentiment_score") is not None]
            out.append(
                NewsItem(
                    a.get("title", ""),
                    a.get("url", ""),
                    a.get("source", "Marketaux"),
                    pd.Timestamp(a.get("published_at")).to_pydatetime(),
                    a.get("description") or a.get("snippet") or "",
                    sum(scores) / len(scores) if scores else None,
                )
            )
        return [n for n in out if n.title]
