"""FRED (St. Louis Fed): macro series and US data-release dates. Free key, 120 req/min."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from config.settings import get_settings
from data.http import ProviderError, get_json
from data.providers.base import EconomicEvent, MacroProvider

_BASE = "https://api.stlouisfed.org/fred"

# Release names (as FRED spells them) that count as high-impact US events.
KEY_RELEASES = {
    "Consumer Price Index": "US CPI (inflation)",
    "Employment Situation": "US Non-Farm Payrolls / Unemployment",
    "Gross Domestic Product": "US GDP",
    "Personal Income and Outlays": "US PCE inflation / spending",
    "Advance Monthly Sales for Retail and Food Services": "US Retail Sales",
    "Producer Price Index": "US PPI",
    "Job Openings and Labor Turnover Survey": "US JOLTS job openings",
}


class FredProvider(MacroProvider):
    name = "fred"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else get_settings().fred_api_key

    def _get(self, path: str, **params):
        if not self.api_key:
            raise ProviderError("FRED_API_KEY not set")
        params.update(api_key=self.api_key, file_type="json")
        return get_json(f"{_BASE}/{path}", params, provider=self.name, cpm=100)

    def get_series(self, series_id: str, start: str | None = None) -> pd.Series:
        start = start or (date.today() - timedelta(days=365 * 6)).isoformat()
        js = self._get("series/observations", series_id=series_id, observation_start=start)
        obs = js.get("observations") or []
        s = pd.Series(
            {pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in obs},
            name=series_id,
            dtype="float64",
        ).dropna()
        if s.empty:
            raise ProviderError(f"FRED series {series_id} returned no data")
        return s.sort_index()

    def upcoming_releases(self, days: int = 14) -> list[EconomicEvent]:
        today = date.today()
        js = self._get(
            "releases/dates",
            realtime_start=today.isoformat(),
            realtime_end=(today + timedelta(days=days)).isoformat(),
            include_release_dates_with_no_data="true",
            limit=1000,
        )
        out = []
        for r in js.get("release_dates") or []:
            name = r.get("release_name", "")
            if name in KEY_RELEASES:
                d = datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc)
                out.append(EconomicEvent(d, "USD", KEY_RELEASES[name], "high", "FRED"))
        return out
