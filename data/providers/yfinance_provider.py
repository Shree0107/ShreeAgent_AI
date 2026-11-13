"""Yahoo Finance via yfinance: free, no key. Covers forex, metals (futures), US stocks and NSE/BSE.

yfinance is unofficial, so it can break or throttle. DataService falls back to Twelve Data for prices.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import pandas as pd

from data.http import ProviderError, TransientProviderError, limiter
from data.providers.base import (
    Fundamentals,
    FundamentalsProvider,
    NewsItem,
    NewsProvider,
    PriceProvider,
    normalise_ohlcv,
    resample_ohlcv,
)
from data.symbols import Symbol

log = logging.getLogger(__name__)

# (yfinance interval, period). Yahoo caps 1h history at ~730 days.
_TF = {"1h": ("1h", "729d"), "4h": ("1h", "729d"), "1d": ("1d", "10y"), "1wk": ("1wk", "20y")}


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


class YFinanceProvider(PriceProvider, FundamentalsProvider, NewsProvider):
    name = "yfinance"

    def _yf(self):
        import yfinance as yf

        return yf

    def get_ohlcv(self, symbol: Symbol, timeframe: str) -> pd.DataFrame:
        if timeframe not in _TF:
            raise ProviderError(f"Unsupported timeframe {timeframe}")
        interval, period = _TF[timeframe]
        limiter(self.name, 60).wait()
        try:
            df = self._yf().Ticker(symbol.yahoo).history(period=period, interval=interval, auto_adjust=True)
        except Exception as e:
            raise TransientProviderError(f"yfinance error for {symbol.yahoo}: {e}") from e
        df = normalise_ohlcv(df)
        if df.empty:
            raise ProviderError(f"yfinance returned no data for {symbol.yahoo} ({timeframe})")
        if timeframe == "4h":
            df = resample_ohlcv(df, "4h")
        return df

    def get_fundamentals(self, symbol: Symbol) -> Fundamentals:
        limiter(self.name, 60).wait()
        try:
            t = self._yf().Ticker(symbol.yahoo)
            info = t.info or {}
        except Exception as e:
            raise TransientProviderError(f"yfinance fundamentals error for {symbol.yahoo}: {e}") from e
        if not info:
            raise ProviderError(f"No fundamentals for {symbol.ticker}")

        next_earn = None
        try:
            cal = t.calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if dates:
                next_earn = str(dates[0])
        except Exception:
            pass
        if not next_earn and info.get("earningsTimestamp"):
            next_earn = datetime.fromtimestamp(info["earningsTimestamp"], tz=timezone.utc).date().isoformat()

        d = {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency"),
            "market_cap": _num(info.get("marketCap")),
            "price": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
            "pe_trailing": _num(info.get("trailingPE")),
            "pe_forward": _num(info.get("forwardPE")),
            "peg": _num(info.get("trailingPegRatio") or info.get("pegRatio")),
            "price_to_book": _num(info.get("priceToBook")),
            "eps_trailing": _num(info.get("trailingEps")),
            "eps_forward": _num(info.get("forwardEps")),
            "revenue_growth": _num(info.get("revenueGrowth")),
            "earnings_growth": _num(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")),
            "gross_margin": _num(info.get("grossMargins")),
            "operating_margin": _num(info.get("operatingMargins")),
            "profit_margin": _num(info.get("profitMargins")),
            "roe": _num(info.get("returnOnEquity")),
            "debt_to_equity": _num(info.get("debtToEquity")),
            "current_ratio": _num(info.get("currentRatio")),
            "dividend_yield": _num(info.get("dividendYield")),
            "beta": _num(info.get("beta")),
            "next_earnings_date": next_earn,
            "fifty_two_week_high": _num(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _num(info.get("fiftyTwoWeekLow")),
            "analyst_target": _num(info.get("targetMeanPrice")),
            "recommendation": info.get("recommendationKey"),
        }
        return Fundamentals(symbol.ticker, d, self.name)

    def get_news(self, symbol: Symbol, days: int = 7, limit: int = 20) -> list[NewsItem]:
        limiter(self.name, 60).wait()
        try:
            raw = self._yf().Ticker(symbol.yahoo).news or []
        except Exception as e:
            raise TransientProviderError(f"yfinance news error: {e}") from e
        items = []
        for n in raw[:limit]:
            c = n.get("content", n)  # newer yfinance nests under "content"
            title = c.get("title") or ""
            url = (c.get("canonicalUrl") or {}).get("url") or c.get("link") or ""
            src = (c.get("provider") or {}).get("displayName") or c.get("publisher") or "Yahoo"
            ts = c.get("pubDate") or c.get("providerPublishTime")
            try:
                pub = (
                    datetime.fromtimestamp(ts, tz=timezone.utc)
                    if isinstance(ts, (int, float))
                    else pd.Timestamp(ts).to_pydatetime()
                )
            except Exception:
                pub = datetime.now(timezone.utc)
            if title:
                items.append(NewsItem(title, url, src, pub, c.get("summary") or ""))
        return items
