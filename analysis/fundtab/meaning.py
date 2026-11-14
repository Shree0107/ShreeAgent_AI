"""What an economic event means for the selected symbol, in plain words.

A rules table decides the direction: event type (inflation, jobs, interest rate, ...) x does a higher number
make the event's currency stronger or weaker x is that currency the pair's base (left) or quote (right) currency.
When the actual number is known it is compared with the forecast ("came in higher than expected -> ...").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from analysis.fundtab import ADJ, PLACE, cur_name

# (type, pattern, direction, plain noun). direction: +1 = a higher number usually makes the currency stronger,
# -1 = weaker, 0 = no simple rule (speeches, minutes). First match wins, so the order matters.
EVENT_RULES: list[tuple[str, str, int, str]] = [
    ("speech", r"speaks|speech|testif|press conference|minutes|hearing", 0, "comments from central-bank officials"),
    ("rate", r"rate decision|policy decision|funds rate|main refinancing|official bank rate|bank rate|policy rate|"
             r"cash rate|overnight rate|interest rate|deposit facility|rate statement|monetary policy|fomc statement|"
             r"fomc", 1, "interest rate"),
    ("core_inflation", r"core (cpi|pce|ppi|inflation)|trimmed mean|median cpi", 1, "core inflation"),
    ("housing", r"housing|home sales|building permits|building approvals|house price|\bhpi\b|mortgage", 1, "housing"),
    ("inflation", r"\bcpi\b|hicp|inflation|\bpce\b|price index|\bppi\b|\brpi\b|prices", 1, "inflation"),
    ("unemployment", r"unemployment|claimant count|jobless|claims", -1, "unemployment"),
    ("jobs", r"non-farm|nonfarm|payrolls|employment change|\badp\b|jolts|job openings|employment", 1, "job growth"),
    ("wages", r"earnings|wage|labor cost|labour cost", 1, "wage growth"),
    ("growth", r"\bgdp\b|economic growth", 1, "economic growth"),
    ("spending", r"retail sales|spending|consumption", 1, "shopping (retail sales)"),
    ("business", r"\bpmi\b|\bism\b|industrial production|manufacturing|factory|durable goods|\bifo\b|zew|tankan|"
                 r"business", 1, "business activity"),
    ("confidence", r"sentiment|confidence", 1, "confidence"),
    ("trade", r"trade balance|current account", 1, "trade balance"),
]

PLAIN_TITLES = [
    ("speech", "{adj} central-bank speech"),
    ("rate", "{adj} interest-rate decision"),
    ("core_inflation", "{adj} core inflation"),
    ("inflation", "{adj} inflation"),
    ("unemployment", "{adj} unemployment"),
    ("jobs", "{adj} jobs report"),
    ("wages", "{adj} wages"),
    ("growth", "{adj} economic growth (GDP)"),
    ("spending", "{adj} shopping (retail sales)"),
    ("business", "{adj} business activity"),
    ("confidence", "{adj} confidence survey"),
    ("housing", "{adj} housing data"),
    ("trade", "{adj} trade balance"),
]

_NUM = re.compile(r"(-?\d+(?:\.\d+)?)\s*([KMBT%]?)", re.I)
_MULT = {"": 1, "%": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


@dataclass
class Rule:
    type: str
    direction: int
    noun: str


def classify(title: str, impact: str = "") -> Rule | None:
    if impact == "holiday" or "holiday" in title.lower():
        return Rule("holiday", 0, "bank holiday")
    t = title.lower()
    for typ, pat, d, noun in EVENT_RULES:
        if re.search(pat, t):
            return Rule(typ, d, noun)
    return None


def plain_title(title: str, currency: str, impact: str = "") -> str:
    """Beginner wording for an event title, e.g. 'CPI m/m' (USD) -> 'US inflation'. Falls back to the title."""
    r = classify(title, impact)
    if r is None or r.type == "holiday":
        return title
    tpl = dict(PLAIN_TITLES).get(r.type)
    return tpl.format(adj=ADJ.get(currency, currency)) if tpl else title


def parse_number(text: str) -> float | None:
    """'0.3%' -> 0.3, '245K' -> 245000, '-1.2B' -> -1.2e9. None when there is no number."""
    m = _NUM.search((text or "").replace(",", ""))
    if not m:
        return None
    return float(m.group(1)) * _MULT[m.group(2).upper()]


def surprise(actual: str, forecast: str) -> str | None:
    """higher | lower | inline, or None when either number is missing."""
    a, f = parse_number(actual), parse_number(forecast)
    if a is None or f is None:
        return None
    if abs(a - f) < 1e-9 * max(1.0, abs(f)):
        return "inline"
    return "higher" if a > f else "lower"


def _pair_effect(currency: str, stronger: bool, symbol) -> str:
    """'EUR/USD tends to fall' etc. Empty when the currency is not part of the symbol."""
    if not symbol.is_fx:
        return ""
    if currency == symbol.base:
        return f"{symbol.ticker} tends to {'rise' if stronger else 'fall'}"
    if currency == symbol.quote:
        return f"{symbol.ticker} tends to {'fall' if stronger else 'rise'}"
    return ""


def _stock_effect(rule: Rule, higher: bool) -> str:
    if rule.type in ("rate", "inflation", "core_inflation", "wages"):
        return ("can keep interest rates high, which often weighs on share prices" if higher
                else "can bring interest rates down, which often helps share prices")
    if rule.type == "unemployment":
        return ("points to a weaker economy, which can hurt company sales" if higher
                else "points to a healthy economy, which usually helps company sales")
    return ("points to a stronger economy, which usually helps company sales" if higher
            else "points to a weaker economy, which can hurt company sales")


def meaning(title: str, currency: str, symbol, impact: str = "", actual: str = "", forecast: str = "") -> str:
    """One plain-language line about what the event means for `symbol` (a data.symbols.Symbol)."""
    rule = classify(title, impact)
    name = cur_name(currency)
    adj = ADJ.get(currency, currency)
    if currency in ("All", "") or rule and rule.type == "holiday":
        where = PLACE.get(currency, "some countries") if currency not in ("All", "") else "several countries"
        return (f"Bank holiday in {where}: fewer traders, so prices may move less, or jump on thin trading.")
    in_symbol = (symbol.is_fx and currency in (symbol.base, symbol.quote)) or \
                (not symbol.is_fx and currency in _home(symbol))
    if not in_symbol:
        return f"Mainly moves {name}. Little direct effect on {symbol.ticker}."
    if rule is None:
        return (f"Can move {name}. A result far from the forecast matters most "
                f"({_direction_hint(symbol, currency)}).")
    if rule.direction == 0:
        return (f"Comments from {adj} central-bank officials can move {name} if they hint at future interest-rate "
                f"changes. Watch for surprises in tone.")

    s = surprise(actual, forecast) if actual else None
    if s == "inline":
        return f"Came in as expected ({actual}): no surprise, so the reaction is usually small."
    if s in ("higher", "lower"):
        higher = s == "higher"
        stronger = higher if rule.direction > 0 else not higher
        lead = f"Came in {s} than expected ({actual} vs {forecast} forecast)"
        if not symbol.is_fx:
            return f"{lead}: this {_stock_effect(rule, higher)}."
        return f"{lead} → usually makes {name} {'stronger' if stronger else 'weaker'} → {_pair_effect(currency, stronger, symbol)}."

    # Not released yet (or no actual number): explain the usual reaction to a higher-than-expected number.
    noun = "interest rate (or a hint of more hikes)" if rule.type == "rate" else f"{adj} {rule.noun}"
    if not symbol.is_fx:
        return f"Higher-than-expected {noun} {_stock_effect(rule, True)}."
    stronger = rule.direction > 0
    return (f"Higher {noun} usually makes {name} {'stronger' if stronger else 'weaker'} → "
            f"{_pair_effect(currency, stronger, symbol)}.")


def _home(symbol) -> list[str]:
    from analysis.fundtab import symbol_currencies

    return symbol_currencies(symbol)


def _direction_hint(symbol, currency: str) -> str:
    if not symbol.is_fx:
        return f"it can move {symbol.ticker} through the wider economy"
    return (f"a stronger {cur_name(currency).removeprefix('the ')} means {_pair_effect(currency, True, symbol)}")
