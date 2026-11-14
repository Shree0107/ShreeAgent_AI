"""Central banks table: current rate, next meeting, and an honest estimate of where rates are heading.

There is no free source of futures-implied rate probabilities, so the 'market expectation' is a proxy built
from three public facts (each optional):
  1. the change in the policy rate over the last 6 months (cutting / hiking already),
  2. inflation vs the bank's target (well above -> pressure to stay high or hike; below -> room to cut),
  3. the 2-year government bond yield vs the policy rate, where a FRED series exists (macro_series.yaml
     `yield_2y`): a 2-year yield clearly below the policy rate means markets expect cuts, above means hikes.
It is always labelled an estimate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from analysis.fundtab import BANK_SHORT, cur_name
from analysis.fundtab.meaning import classify
from analysis.macro_fx import country_macro, macro_config

log = logging.getLogger(__name__)

CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "INR")
TOOLTIP = ("An estimate, not a market price. Built from: how the bank changed rates in the last 6 months, "
           "inflation compared with its target, and (where available) whether 2-year bond yields sit below or "
           "above the bank's rate. Real futures-based probabilities are not available for free.")


def expectation(rate_change_6m: float | None, inflation: float | None, target: float | None,
                yield_2y: float | None, policy_rate: float | None) -> dict:
    """{'lean': cut|hold|hike|unknown, 'label', 'score', 'reasons': [plain sentences], 'inputs': n}."""
    score, n, reasons = 0, 0, []
    if rate_change_6m is not None:
        n += 1
        if rate_change_6m < -0.1:
            score -= 1
            reasons.append(f"It cut rates by {abs(rate_change_6m):.2f} points in the last 6 months.")
        elif rate_change_6m > 0.1:
            score += 1
            reasons.append(f"It raised rates by {rate_change_6m:.2f} points in the last 6 months.")
        else:
            reasons.append("Rates have barely changed in the last 6 months.")
    if inflation is not None and target is not None:
        n += 1
        gap = inflation - target
        if gap > 1.0:
            score += 1
            reasons.append(f"Inflation ({inflation:.1f}%) is well above the {target:g}% target, so cuts are less likely.")
        elif gap < -0.5:
            score -= 1
            reasons.append(f"Inflation ({inflation:.1f}%) is below the {target:g}% target, which leaves room to cut.")
        else:
            reasons.append(f"Inflation ({inflation:.1f}%) is close to the {target:g}% target.")
    if yield_2y is not None and policy_rate is not None:
        n += 1
        spread = yield_2y - policy_rate
        if spread < -0.25:
            score -= 1
            reasons.append(f"The 2-year bond yield ({yield_2y:.2f}%) is below the bank's rate ({policy_rate:.2f}%): "
                           "markets expect cuts.")
        elif spread > 0.25:
            score += 1
            reasons.append(f"The 2-year bond yield ({yield_2y:.2f}%) is above the bank's rate ({policy_rate:.2f}%): "
                           "markets expect hikes.")
        else:
            reasons.append(f"The 2-year bond yield ({yield_2y:.2f}%) is close to the bank's rate.")
    if n == 0:
        return {"lean": "unknown", "label": "not enough data", "score": 0, "reasons": [], "inputs": 0}
    lean = "cut" if score <= -1 else "hike" if score >= 1 else "hold"
    label = {"cut": "leaning to cut (estimate)", "hike": "leaning to hike (estimate)",
             "hold": "leaning to hold (estimate)"}[lean]
    return {"lean": lean, "label": label, "score": score, "reasons": reasons, "inputs": n}


def _next_meeting(currency: str, today, calendar_events: list | None) -> dict | None:
    """Earliest upcoming rate decision: the live calendar (exact time) or config/events.yaml (date only)."""
    best = None
    for e in calendar_events or []:
        r = classify(e.title, e.impact)
        if e.currency == currency and r and r.type == "rate" and e.major and e.time.date() >= today:
            best = {"date": e.time.date().isoformat(), "time": e.time.isoformat(), "title": e.title,
                    "source": "ForexFactory"}
            break
    try:
        from data.service import _curated_events

        future = sorted((e for e in _curated_events() if e.currency == currency and e.date.date() >= today),
                        key=lambda e: e.date)
        if future and (best is None or future[0].date.date().isoformat() < best["date"]):
            e = future[0]
            best = {"date": e.date.date().isoformat(), "time": None, "title": e.title, "source": "config/events.yaml"}
    except Exception as ex:
        log.info("events.yaml unreadable: %s", ex)
    return best


def _series_info(data, sid: str | None):
    """(last value, last observation date) or (None, None)."""
    if not sid:
        return None, None
    try:
        s = data.get_macro_series(sid).dropna()
        return (round(float(s.iloc[-1]), 3), s.index[-1].date().isoformat()) if len(s) else (None, None)
    except Exception:
        return None, None


def central_banks(data, calendar_events: list | None = None, now: datetime | None = None,
                  currencies=CURRENCIES) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = macro_config()
    rows, missing_any, have_any = [], False, False
    for c in currencies:
        if c not in cfg:
            continue
        try:
            cm = country_macro(c, data)
        except Exception as e:  # one country failing must not hide the rest
            log.info("Macro for %s failed: %s", c, e)
            rows.append({"currency": c, "bank": cfg[c].get("central_bank", c), "error": str(e)})
            continue
        _, rate_date = _series_info(data, cfg[c].get("policy_rate"))
        y2, y2_date = _series_info(data, cfg[c].get("yield_2y"))
        exp = expectation(cm.rate_change_6m, cm.inflation_yoy, cm.inflation_target, y2, cm.policy_rate)
        if cm.policy_rate is None:
            missing_any = True
        else:
            have_any = True
        stale = bool(rate_date) and (now.date() - datetime.fromisoformat(rate_date).date()).days > 90
        nm = _next_meeting(c, now.date(), calendar_events)
        rows.append({
            "currency": c, "currency_name": cur_name(c), "bank": cm.central_bank, "short": BANK_SHORT.get(c, c),
            "policy_rate": cm.policy_rate, "rate_as_of": rate_date, "rate_stale": stale,
            "rate_change_6m": cm.rate_change_6m,
            "inflation_yoy": cm.inflation_yoy, "inflation_target": cm.inflation_target,
            "yield_2y": y2, "yield_2y_as_of": y2_date,
            "next_meeting": nm, "next_meeting_text": nm["date"] if nm else "date not in calendar file",
            "expectation": exp, "missing": cm.missing,
        })
    notes = []
    if missing_any and not have_any:
        notes.append("Interest rates are unavailable. They come from FRED: set FRED_API_KEY in .env "
                     "(free at fred.stlouisfed.org).")
    elif missing_any:
        notes.append("Some interest rates are unavailable from FRED (the series may have stopped updating; the IDs "
                     "are in config/macro_series.yaml). Their estimate uses the other facts only.")
    if any(r.get("rate_stale") for r in rows):
        notes.append("Rates marked 'old data' are more than 3 months old in FRED and may no longer be current.")
    notes.append("Rates come from FRED. Some countries' rates are monthly figures that can lag by a month or "
                 "more: check the 'as of' date.")
    return {"banks": rows, "tooltip": TOOLTIP, "notes": notes, "source": "FRED + config/events.yaml"}
