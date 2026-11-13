"""DataService: single entry point for all market data.

It picks providers from config, caches every response, and falls back to the
next provider (or stale cache) when one fails, so analysis code never talks to an API directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
import yaml

from config.settings import ROOT, get_settings
from data.cache import TTL, Cache, get_cache
from data.http import ProviderError
from data.providers.base import (
    TIMEFRAMES,
    EconomicEvent,
    Fundamentals,
    MacroProvider,
    NewsItem,
    NewsProvider,
    PriceProvider,
)
from data.symbols import Symbol, parse_symbol

log = logging.getLogger(__name__)


def _price_registry() -> dict[str, type[PriceProvider]]:
    from data.providers.twelvedata import TwelveDataProvider
    from data.providers.yfinance_provider import YFinanceProvider

    return {"yfinance": YFinanceProvider, "twelvedata": TwelveDataProvider}


class DataService:
    def __init__(
        self,
        price_providers: list[PriceProvider] | None = None,
        news_providers: list[NewsProvider] | None = None,
        macro: MacroProvider | None = None,
        cache: Cache | None = None,
    ):
        s = get_settings()
        reg = _price_registry()
        if price_providers is None:
            price_providers = [reg[n]() for n in (s.price_provider, s.price_fallback_provider) if n in reg]
        self.price_providers = price_providers
        self.cache = cache or get_cache()
        self._news = news_providers
        self._macro = macro

    # ---------- prices ----------
    def get_ohlcv(self, symbol: Symbol, timeframe: str = "1d") -> pd.DataFrame:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        key = f"ohlcv:{symbol.ticker}:{timeframe}"

        def fetch():
            errors = []
            for p in self.price_providers:
                try:
                    df = p.get_ohlcv(symbol, timeframe)
                    if not df.empty:
                        df.attrs["source"] = p.name
                        return df
                except ProviderError as e:
                    errors.append(str(e))
                    log.warning("Price provider %s failed: %s", p.name, e)
            raise ProviderError("; ".join(errors) or "no price providers configured")

        return self.cache.get_or_fetch(key, TTL[f"ohlcv_{timeframe}"], fetch)

    def get_ohlcv_ticker(self, ticker: str, timeframe: str = "1d") -> pd.DataFrame | None:
        """Convenience for related assets ('^NSEI', 'DX-Y.NYB'). Returns None on failure."""
        sym = parse_symbol(ticker)
        if not sym:
            return None
        try:
            return self.get_ohlcv(sym, timeframe)
        except Exception as e:
            log.info("Related asset %s unavailable: %s", ticker, e)
            return None

    def last_price(self, symbol: Symbol) -> dict:
        df = self.get_ohlcv(symbol, "1d")
        last, prev = df["close"].iloc[-1], df["close"].iloc[-2] if len(df) > 1 else df["close"].iloc[-1]
        return {
            "symbol": symbol.ticker,
            "price": float(last),
            "change_pct": float((last / prev - 1) * 100),
            "as_of": df.index[-1].isoformat(),
            "source": df.attrs.get("source", ""),
            "investing_url": symbol.investing_url,
        }

    # ---------- fundamentals ----------
    def get_fundamentals(self, symbol: Symbol) -> Fundamentals:
        from data.providers.yfinance_provider import YFinanceProvider

        return self.cache.get_or_fetch(
            f"fund:{symbol.ticker}", TTL["fundamentals"], lambda: YFinanceProvider().get_fundamentals(symbol)
        )

    def get_peers(self, symbol: Symbol) -> list[str]:
        from data.providers.finnhub import FinnhubProvider

        try:
            return self.cache.get_or_fetch(f"peers:{symbol.ticker}", TTL["fundamentals"], lambda: FinnhubProvider().peers(symbol))
        except ProviderError:
            return []

    # ---------- news ----------
    def news_providers(self) -> list[NewsProvider]:
        if self._news is not None:
            return self._news
        from data.providers.finnhub import FinnhubProvider
        from data.providers.marketaux import MarketauxProvider
        from data.providers.yfinance_provider import YFinanceProvider

        s = get_settings()
        out: list[NewsProvider] = []
        if s.marketaux_api_key:
            out.append(MarketauxProvider())
        if s.finnhub_api_key:
            out.append(FinnhubProvider())
        out.append(YFinanceProvider())  # keyless fallback
        return out

    def get_news(self, symbol: Symbol, days: int = 7, limit: int = 20) -> list[NewsItem]:
        def fetch():
            items: list[NewsItem] = []
            seen = set()
            for p in self.news_providers():
                try:
                    for n in p.get_news(symbol, days, limit):
                        k = n.title.lower()[:80]
                        if k not in seen:
                            seen.add(k)
                            items.append(n)
                except ProviderError as e:
                    log.info("News provider %s failed: %s", p.name, e)
                if len(items) >= limit:
                    break
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            items = [n for n in items if _aware(n.published) >= cutoff] or items
            return sorted(items, key=lambda n: _aware(n.published), reverse=True)[:limit]

        return self.cache.get_or_fetch(f"news:{symbol.ticker}:{days}", TTL["news"], fetch)

    # ---------- macro ----------
    @property
    def macro(self) -> MacroProvider:
        if self._macro is None:
            from data.providers.fred import FredProvider

            self._macro = FredProvider()
        return self._macro

    def get_macro_series(self, series_id: str) -> pd.Series:
        return self.cache.get_or_fetch(f"macro:{series_id}", TTL["macro"], lambda: self.macro.get_series(series_id))

    def upcoming_events(self, currencies: list[str], days: int = 14) -> list[EconomicEvent]:
        """FRED US release dates + curated central-bank meetings (config/events.yaml)."""
        events: list[EconomicEvent] = []
        if "USD" in currencies:
            try:
                fred_events = self.cache.get_or_fetch(
                    f"cal:fred:{days}", TTL["calendar"], lambda: self.macro.upcoming_releases(days)
                )
                events.extend(fred_events)
            except (ProviderError, AttributeError) as e:
                log.info("FRED calendar unavailable: %s", e)
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=days)
        for ev in _curated_events():
            if ev.currency in currencies and now - timedelta(days=1) <= ev.date <= horizon:
                events.append(ev)
        return sorted(events, key=lambda e: e.date)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _curated_events() -> tuple[EconomicEvent, ...]:
    path = ROOT / "config" / "events.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return ()
    out = []
    for e in raw.get("events") or []:
        try:
            d = pd.Timestamp(str(e["date"])).to_pydatetime().replace(tzinfo=timezone.utc)
            out.append(EconomicEvent(d, e["currency"], e["title"], e.get("impact", "high"), "events.yaml"))
        except Exception:
            log.warning("Bad event entry in events.yaml: %s", e)
    return tuple(out)


_service: DataService | None = None


def get_data_service() -> DataService:
    global _service
    if _service is None:
        _service = DataService()
    return _service
