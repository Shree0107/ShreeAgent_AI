"""Combine technical + fundamental + sentiment + forecast into one deterministic view.

Used by the agent (as a tool), the report exporter and the daily scanner. The LLM adds the
narrative, but the scores, levels and confidence here are computed in code.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from analysis.technical import analyse_symbol, bias_label
from analysis.trade_plan import build_plan
from data.symbols import Symbol

log = logging.getLogger(__name__)

WEIGHTS = {"technical": 0.45, "fundamental": 0.25, "sentiment": 0.10, "forecast": 0.20}
TRUST_FACTOR = {"moderate": 1.0, "low": 0.5}  # other labels count as 0 (forecast ignored)

DISCLAIMER = (
    "This is automated analysis for educational purposes, not financial advice. "
    "Markets are risky. Verify the data (e.g. on Investing.com) and make your own decision."
)


def forecast_score(fc: dict) -> tuple[float, float]:
    """Map a forecast to a score in [-100, 100] and a weight multiplier based on backtest trust."""
    prob_up = fc.get("prob_up", 0.5)
    score = max(-100.0, min(100.0, (prob_up - 0.5) * 200))
    bt = fc.get("backtest") or {}
    factor = TRUST_FACTOR.get(bt.get("trust", ""), 0.0) if bt else 0.25  # not backtested yet: small weight
    return round(score, 1), factor


def confidence(components: dict[str, float], alignment: str, total: float) -> tuple[str, list[str]]:
    signs = {k: (1 if v >= 20 else -1 if v <= -20 else 0) for k, v in components.items()}
    direction = 1 if total > 0 else -1
    agree = sum(1 for s in signs.values() if s == direction)
    disagree = sum(1 for s in signs.values() if s == -direction)
    why = [f"{agree} of {len(signs)} components agree with the overall direction"]
    if disagree:
        why.append(f"{disagree} component(s) point the other way")
    why.append(f"timeframes {alignment}")
    if len(signs) < 2:
        why.append("only one component available")
    if abs(total) >= 40 and disagree == 0 and alignment == "aligned" and agree >= 2:
        return "High", why
    if abs(total) >= 20 and disagree <= 1:
        return "Medium", why
    return "Low", why


def full_analysis(
    symbol: Symbol,
    timeframe: str = "1d",
    horizon: int = 10,
    include_forecast: bool = True,
    include_news: bool = True,
    data=None,
    forecaster=None,
) -> dict:
    from data.service import get_data_service

    data = data or get_data_service()
    out: dict = {"symbol": symbol.ticker, "name": symbol.name, "asset_class": symbol.asset_class,
                 "market": symbol.market, "investing_url": symbol.investing_url,
                 "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "errors": {}}
    comps: dict[str, float] = {}

    # Technical analysis (required)
    mtf = analyse_symbol(symbol, data=data)
    out["technical"] = mtf.as_dict(compact=True)
    comps["technical"] = mtf.score
    tf_sig = mtf.timeframes.get(timeframe) or next(iter(mtf.timeframes.values()))
    price = tf_sig.snapshot["close"]
    out["price"] = price

    # Fundamentals
    try:
        if symbol.is_fx:
            from analysis.macro_fx import analyse_fx

            f = analyse_fx(symbol, data=data)
        else:
            from analysis.fundamental import analyse_stock

            f = analyse_stock(symbol, data=data)
        out["fundamental"] = f.as_dict()
        if getattr(f, "n_factors", 1) > 0:  # FX with no macro data: leave it out instead of counting it as neutral
            comps["fundamental"] = f.score
    except Exception as e:
        log.warning("Fundamentals failed for %s: %s", symbol.ticker, e)
        out["errors"]["fundamental"] = str(e)

    # News sentiment
    if include_news:
        try:
            from analysis.sentiment import analyse_news

            s = analyse_news(symbol, data=data)
            d = s.as_dict()
            d["headlines"] = d["headlines"][:6]
            out["sentiment"] = d
            if s.n_articles:
                comps["sentiment"] = round(s.score * 100, 1)
        except Exception as e:
            out["errors"]["sentiment"] = str(e)

    # Forecast
    weights = dict(WEIGHTS)
    if include_forecast:
        try:
            from forecasting.service import forecast_symbol

            fc = forecast_symbol(symbol, timeframe, horizon, data=data, forecaster=forecaster)
            fcd = fc.as_dict(compact=True)
            out["forecast"] = fcd
            sc, factor = forecast_score(fcd)
            comps["forecast"] = sc
            weights["forecast"] *= factor
        except Exception as e:
            log.warning("Forecast failed for %s: %s", symbol.ticker, e)
            out["errors"]["forecast"] = str(e)

    used = {k: weights[k] for k in comps if weights.get(k, 0) > 0}
    total = round(sum(comps[k] * used[k] for k in used) / (sum(used.values()) or 1), 1)
    conf, why = confidence({k: comps[k] for k in used}, mtf.alignment, total)
    bias = bias_label(total)
    out["combined"] = {"score": total, "bias": bias, "confidence": conf, "confidence_reasons": why,
                       "components": comps, "weights": {k: round(v, 3) for k, v in used.items()}}

    plan = build_plan(
        bias, price, tf_sig.snapshot.get("atr_14") or 0,
        [l["price"] for l in tf_sig.supports], [l["price"] for l in tf_sig.resistances],
    )
    out["trade_plan"] = {"timeframe": tf_sig.timeframe, **plan.as_dict()}
    out["key_levels"] = {"supports": tf_sig.supports, "resistances": tf_sig.resistances, "pivots": tf_sig.pivots}
    out["disclaimer"] = DISCLAIMER
    return out
