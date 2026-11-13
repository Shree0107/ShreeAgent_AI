"""Forex / metals fundamentals: rate differentials, inflation, growth, central-bank lean, upcoming events."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import pandas as pd
import yaml

from config.settings import ROOT
from data.symbols import Symbol

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def macro_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "macro_series.yaml").read_text(encoding="utf-8")) or {}


@dataclass
class CountryMacro:
    currency: str
    name: str = ""
    central_bank: str = ""
    policy_rate: float | None = None
    rate_change_6m: float | None = None
    inflation_yoy: float | None = None
    inflation_target: float | None = None
    bond_10y: float | None = None
    gdp_growth_yoy: float | None = None
    cb_lean: str = "unknown"  # hawkish | dovish | neutral | unknown
    missing: list[str] = field(default_factory=list)


@dataclass
class FxFundamentalReport:
    symbol: str
    score: float
    bias: str
    base: CountryMacro
    quote: CountryMacro
    rate_differential: float | None
    yield_differential: float | None
    drivers: list[str]
    events: list[dict]
    extra: dict = field(default_factory=dict)
    n_factors: int = 0  # 0 = no macro data, so the score is meaningless and is left out of the combined view

    def as_dict(self) -> dict:
        return asdict(self)


def _yoy(s: pd.Series) -> float | None:
    """YoY % change of the last observation, from monthly or quarterly data."""
    s = s.dropna()
    if len(s) < 5:
        return None
    last_date = s.index[-1]
    prior = s[s.index <= last_date - pd.DateOffset(months=12)]
    if prior.empty:
        return None
    return round((s.iloc[-1] / prior.iloc[-1] - 1) * 100, 2)


def _last(s: pd.Series) -> float | None:
    s = s.dropna()
    return round(float(s.iloc[-1]), 3) if len(s) else None


def _change(s: pd.Series, months: int) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    prior = s[s.index <= s.index[-1] - pd.DateOffset(months=months)]
    return round(float(s.iloc[-1] - prior.iloc[-1]), 3) if len(prior) else None


def country_macro(currency: str, data) -> CountryMacro:
    cfg = macro_config().get(currency)
    cm = CountryMacro(currency)
    if not cfg:
        cm.missing.append("no macro config")
        return cm
    cm.name, cm.central_bank, cm.inflation_target = cfg.get("name", ""), cfg.get("central_bank", ""), cfg.get("inflation_target")

    def series(key):
        sid = cfg.get(key)
        if not sid:
            return None
        try:
            return data.get_macro_series(sid)
        except Exception as e:
            cm.missing.append(f"{key} ({sid}): {e}")
            return None

    if (s := series("policy_rate")) is not None:
        cm.policy_rate, cm.rate_change_6m = _last(s), _change(s, 6)
    if (s := series("cpi")) is not None:
        cm.inflation_yoy = _yoy(s)
    if (s := series("bond_10y")) is not None:
        cm.bond_10y = _last(s)
    if (s := series("gdp")) is not None:
        cm.gdp_growth_yoy = _yoy(s)

    # Central-bank lean: hiking, or inflation well above target, reads hawkish. Cutting, or inflation below target, reads dovish.
    lean = 0
    if cm.rate_change_6m is not None:
        lean += 1 if cm.rate_change_6m > 0.1 else -1 if cm.rate_change_6m < -0.1 else 0
    if cm.inflation_yoy is not None and cm.inflation_target is not None:
        gap = cm.inflation_yoy - cm.inflation_target
        lean += 1 if gap > 1.0 else -1 if gap < -0.5 else 0
    if cm.rate_change_6m is not None or cm.inflation_yoy is not None:
        cm.cb_lean = "hawkish" if lean > 0 else "dovish" if lean < 0 else "neutral"
    return cm


def _diff(a, b):
    return round(a - b, 3) if a is not None and b is not None else None


def analyse_fx(symbol: Symbol, data=None, event_days: int = 14) -> FxFundamentalReport:
    """Positive score favours the BASE currency (pair up), negative favours the QUOTE currency."""
    from data.service import get_data_service

    data = data or get_data_service()
    is_metal = symbol.asset_class == "metal"
    quote = country_macro(symbol.quote, data)
    base = CountryMacro(symbol.base, name="Gold" if symbol.base == "XAU" else "Silver") if is_metal else country_macro(symbol.base, data)

    drivers: list[str] = []
    pts = 0.0
    n = 0
    extra: dict = {}

    rate_diff = _diff(base.policy_rate, quote.policy_rate)
    yld_diff = _diff(base.bond_10y, quote.bond_10y)
    if not is_metal:
        if rate_diff is not None:
            n += 1
            pts += max(-1, min(1, rate_diff / 2))
            drivers.append(f"Policy rate differential {symbol.base}-{symbol.quote}: {rate_diff:+.2f} pp "
                           f"({'supports' if rate_diff > 0 else 'weighs on'} {symbol.ticker})")
        if base.rate_change_6m is not None and quote.rate_change_6m is not None:
            mom = base.rate_change_6m - quote.rate_change_6m
            if abs(mom) > 0.1:
                n += 1
                pts += 0.5 if mom > 0 else -0.5
                drivers.append(f"Rate momentum (6m) favours {symbol.base if mom > 0 else symbol.quote}")
        lean_val = {"hawkish": 1, "neutral": 0, "dovish": -1}
        if base.cb_lean in lean_val and quote.cb_lean in lean_val:
            d = lean_val[base.cb_lean] - lean_val[quote.cb_lean]
            if d:
                n += 1
                pts += 0.5 * d
            drivers.append(f"{base.central_bank} lean: {base.cb_lean}; {quote.central_bank} lean: {quote.cb_lean}")
        if base.gdp_growth_yoy is not None and quote.gdp_growth_yoy is not None:
            g = base.gdp_growth_yoy - quote.gdp_growth_yoy
            n += 1
            pts += max(-0.5, min(0.5, g / 2))
            drivers.append(f"GDP growth gap {g:+.1f} pp")
    else:
        # Gold and silver: driven by USD real yields and USD strength (both inverse).
        g = macro_config().get("gold_drivers", {})
        for key, label in (("real_yield_10y", "US 10y real yield"), ("usd_broad_index", "Broad USD index")):
            try:
                s = data.get_macro_series(g[key])
                ch = _change(s, 3)
                extra[key] = {"last": _last(s), "change_3m": ch}
                if ch is not None:
                    n += 1
                    pts += -0.7 if ch > 0 else 0.7
                    drivers.append(f"{label} {'rising' if ch > 0 else 'falling'} over 3m ({ch:+.2f}): "
                                   f"{'headwind' if ch > 0 else 'tailwind'} for {symbol.base}")
            except Exception as e:
                extra[key] = {"error": str(e)}
        if quote.cb_lean != "unknown":
            drivers.append(f"Fed lean: {quote.cb_lean}")

    currencies = [c for c in (symbol.base, symbol.quote) if c not in ("XAU", "XAG")]
    try:
        events = [
            {"date": e.date.date().isoformat(), "currency": e.currency, "title": e.title, "impact": e.impact, "source": e.source}
            for e in data.upcoming_events(currencies, event_days)
        ]
    except Exception as e:
        log.info("Events unavailable: %s", e)
        events = []

    score = round(100 * pts / max(n, 2), 1) if n else 0.0
    bias = "bullish" if score >= 20 else "bearish" if score <= -20 else "neutral"
    if not n:
        drivers.append("Macro data unavailable. Set FRED_API_KEY in .env.")
    return FxFundamentalReport(symbol.ticker, score, bias, base, quote, rate_diff, yld_diff, drivers, events, extra, n)
