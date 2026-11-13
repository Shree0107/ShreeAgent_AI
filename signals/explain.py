"""Plain-language explanations built from rules and templates, so wording is always consistent.

Every sentence is generated from a measured fact (see structure.py / analysis output). No indicator
names (RSI, MACD, ATR, EMA, ...) appear in the main-view text; they live only in "Show details".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from data.symbols import Symbol
from signals.decision import Decision
from signals.events import UpcomingEvent
from signals.levels import LevelPlan
from signals.market import CURRENCY_SIGNS, fmt_distance, fmt_money, fmt_price
from signals.sizing import PositionSize
from signals.structure import MarketFacts

DISCLAIMER = "This is analysis, not financial advice. Always use a stop loss."

GLOSSARY = {
    "Stop loss": "An order that closes your trade automatically at a set price, so a loss can't grow beyond what you planned.",
    "Take profit": "An order that closes your trade automatically once the price reaches your target, locking in the gain.",
    "Entry zone": "The price range where the trade makes sense to open. Outside it, the risk and reward no longer fit.",
    "Daily candle": "One day of price movement. Its 'close' is the last price of that trading day.",
    "Risk vs reward": "How much you could gain compared with how much you could lose if the stop loss is hit.",
    "Lot": "The trade size unit in forex. 1 lot = 100,000 units of the first currency (e.g. €100,000 for EUR/USD); 0.01 lots = 1,000.",
    "Pip": "The standard small price step in forex. For EUR/USD 1 pip = 0.0001 (1.0900 → 1.0901).",
    "Spread": "The small gap between the buy and sell price – the broker's fee. It's why your trade starts slightly negative.",
    "Margin": "Money your broker sets aside while the trade is open. It's not a fee and you get it back when you close.",
    "Confidence": "How strongly the different checks (price trend, economy/company, news, forecast) agree with each other.",
    "Expiry": "If the trade hasn't been entered by this time, the idea is out of date – ignore it and wait for a new signal.",
    "Shares": "Units of a company's stock. Buying 10 shares means you own 10 pieces of the company.",
}

ACTION_WORD = {"BUY": "Buy", "SELL": "Sell"}
PLACE = {"USD": "the US", "EUR": "the Eurozone", "GBP": "the UK", "JPY": "Japan", "CHF": "Switzerland",
         "AUD": "Australia", "NZD": "New Zealand", "CAD": "Canada", "INR": "India"}
CURRENCY_NAME = {"USD": "US dollar", "EUR": "euro", "GBP": "British pound", "JPY": "Japanese yen", "CHF": "Swiss franc",
                 "AUD": "Australian dollar", "NZD": "New Zealand dollar", "CAD": "Canadian dollar", "INR": "Indian rupee"}
_COMPONENT_WORDS = {"technical": "the price trend", "sentiment": "the news", "forecast": "the forecast"}


@dataclass
class Explanation:
    reasons: list[str]
    waiting_for: list[str]
    entry_text: str
    entry_confirm: str
    stop_text: str
    stop_why: str
    targets: list[dict]
    cancel: list[str]
    confidence_text: str
    rr_text: str
    size_text: str
    size_note: str
    event_warning: str | None
    events: list[dict] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------- small helpers ----------------
def fmt_day(d: str | date | datetime, today: date | None = None) -> str:
    dd = d if isinstance(d, date) and not isinstance(d, datetime) else (
        d.date() if isinstance(d, datetime) else date.fromisoformat(str(d)[:10]))
    today = today or date.today()
    label = dd.strftime("%a %d %b").replace(" 0", " ")
    gap = (dd - today).days
    if gap == 0:
        return f"today ({label})"
    if gap == 1:
        return f"tomorrow ({label})"
    return label


def join_words(xs: list[str]) -> str:
    xs = [x for x in xs if x]
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " and " + xs[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def component_word(name: str, symbol: Symbol) -> str:
    if name == "fundamental":
        return "the economic background" if symbol.is_fx else "the company's finances"
    return _COMPONENT_WORDS.get(name, name)


# ---------------- reasons ----------------
def fact_sentences(symbol: Symbol, facts: MarketFacts, analysis: dict) -> list[tuple[int, float, str]]:
    """(side, weight, sentence). side: +1 supports a rise, -1 supports a fall, 0 neutral."""
    out: list[tuple[int, float, str]] = []
    f = fmt_price
    n = abs(facts.days_in_trend)
    up = facts.days_in_trend > 0
    if n >= 10:
        w = round(n / 5)
        out.append((1 if up else -1, 3.0,
                    f"The price has been {'rising' if up else 'falling'} steadily for about {w} week{'s' if w != 1 else ''}"))
    elif n >= 3:
        out.append((1 if up else -1, 2.0, f"The price has been {'rising' if up else 'falling'} for the last {n} days"))
    else:
        out.append((0, 1.0, "The price has been moving sideways recently, with no clear direction"))

    if facts.above_200d is not None:
        out.append((1 if facts.above_200d else -1, 1.8,
                    f"The price is {'above' if facts.above_200d else 'below'} its average of the last 200 days, "
                    f"so the long-term direction is {'up' if facts.above_200d else 'down'}"))

    wk = ((analysis.get("technical") or {}).get("timeframes") or {}).get("1wk") or {}
    if wk.get("trend") in ("uptrend", "downtrend"):
        out.append((1 if wk["trend"] == "uptrend" else -1, 1.6,
                    f"The weekly chart is also pointing {'up' if wk['trend'] == 'uptrend' else 'down'}"))
    elif wk.get("trend") == "sideways":
        out.append((0, 0.8, "The weekly chart has no clear direction"))

    if facts.momentum == "rising":
        out.append((1, 1.4, "Buyers have been getting stronger over the last few days"))
    elif facts.momentum == "falling":
        out.append((-1, 1.4, "Sellers have been getting stronger over the last few days"))

    if facts.stretched == "overbought":
        out.append((-1, 1.5, "The price has risen a lot in a short time, so a pause or small dip is likely"))
    elif facts.stretched == "oversold":
        out.append((1, 1.5, "The price has fallen a lot in a short time, so a bounce is possible"))

    if facts.bounce_side == "support":
        out.append((1, 2.5, f"The price bounced off {f(symbol, facts.bounce_level)}, a level where buyers have stepped in before"))
    elif facts.bounce_side == "resistance":
        out.append((-1, 2.5, f"The price was pushed back from {f(symbol, facts.bounce_level)}, a level where sellers have stepped in before"))

    out += _fundamental_sentences(symbol, analysis.get("fundamental") or {})

    s = analysis.get("sentiment") or {}
    heads = s.get("headlines") or []
    if s.get("n_articles", 0) >= 3 and heads:
        pos = sum(1 for h in heads if h.get("sentiment", 0) > 0.15)
        neg = sum(1 for h in heads if h.get("sentiment", 0) < -0.15)
        if s.get("label") == "positive":
            out.append((1, 1.0, f"Recent news is mostly positive ({pos} of {len(heads)} headlines)"))
        elif s.get("label") == "negative":
            out.append((-1, 1.0, f"Recent news is mostly negative ({neg} of {len(heads)} headlines)"))
        else:
            out.append((0, 0.6, "Recent news is mixed"))

    fc = analysis.get("forecast") or {}
    if fc:
        p, chg, h = fc.get("prob_up", 0.5), fc.get("expected_change_pct", 0.0), fc.get("horizon", 10)
        days = f"{h} trading days" if fc.get("timeframe") == "1d" else f"{h} candles"
        size = "a little" if abs(chg) < 0.5 else "" if abs(chg) < 1.5 else "noticeably"
        trust = (fc.get("backtest") or {}).get("trust")
        weight = 2.0 if trust == "moderate" else 1.2
        if p >= 0.55:
            out.append((1, weight, f"Our forecasting model expects the price to rise {size} over the next {days}".replace("  ", " ")))
        elif p <= 0.45:
            out.append((-1, weight, f"Our forecasting model expects the price to fall {size} over the next {days}".replace("  ", " ")))
        else:
            out.append((0, 0.8, f"Our forecasting model doesn't expect a big move over the next {days}"))
    return out


def _fundamental_sentences(symbol: Symbol, fd: dict) -> list[tuple[int, float, str]]:
    out: list[tuple[int, float, str]] = []
    if not fd:
        return out
    if symbol.is_fx and "base" in fd:
        base, quote = fd.get("base") or {}, fd.get("quote") or {}
        diff = fd.get("rate_differential")
        bn, qn = PLACE.get(symbol.base, symbol.base), PLACE.get(symbol.quote, symbol.quote)
        if diff is not None and abs(diff) >= 0.25 and symbol.asset_class == "forex":
            hi, lo = (bn, qn) if diff > 0 else (qn, bn)
            hi_rate = base.get("policy_rate") if diff > 0 else quote.get("policy_rate")
            lo_rate = quote.get("policy_rate") if diff > 0 else base.get("policy_rate")
            ccy = CURRENCY_NAME.get(symbol.base if diff > 0 else symbol.quote, symbol.base if diff > 0 else symbol.quote)
            if hi_rate is not None and lo_rate is not None:
                out.append((1 if diff > 0 else -1, 2.0,
                            f"Interest rates are higher in {hi} than in {lo} ({hi_rate:.2f}% vs {lo_rate:.2f}%), "
                            f"which tends to support the {ccy}"))
        for cm, side in ((base, 1), (quote, -1)):
            ch = cm.get("rate_change_6m")
            bank = cm.get("central_bank") or ""
            if bank == "ECB":
                bank = "European Central Bank"
            if ch is not None and abs(ch) > 0.1 and bank:
                cutting = ch < 0
                out.append((-side if cutting else side, 1.5,
                            f"The {bank} has been {'cutting' if cutting else 'raising'} interest rates over the last 6 months"))
        if not out and fd.get("n_factors"):
            sc = fd.get("score", 0)
            if abs(sc) >= 20:
                out.append((1 if sc > 0 else -1, 1.0,
                            f"The economic background favours a {'rise' if sc > 0 else 'fall'} in {symbol.ticker}"))
        return out

    m, v = fd.get("metrics") or {}, fd.get("valuation") or {}
    rg, eg = m.get("revenue_growth_pct"), m.get("earnings_growth_pct")
    if rg is not None and eg is not None and rg > 10 and eg > 10:
        out.append((1, 2.0, f"The company's sales and profits are growing fast ({rg:.0f}% and {eg:.0f}% in a year)"))
    elif rg is not None and rg < 0:
        out.append((-1, 2.0, f"The company's sales are shrinking ({rg:.0f}% in a year)"))
    elif eg is not None and eg < -5:
        out.append((-1, 1.8, f"The company's profits are falling ({eg:.0f}% in a year)"))
    vs = v.get("vs_sector")
    if vs is not None and vs < -20:
        out.append((1, 1.5, "The share price looks cheap compared with similar companies"))
    elif vs is not None and vs > 30:
        out.append((-1, 1.5, "The share price looks expensive compared with similar companies"))
    up = v.get("analyst_upside_pct")
    if up is not None and up > 15:
        out.append((1, 1.0, f"Analysts on average expect the price to rise about {up:.0f}%"))
    elif up is not None and up < -5:
        out.append((-1, 1.0, "The price is already above what analysts on average expect"))
    return out


def pick_reasons(sentences: list[tuple[int, float, str]], action: str, lean: str | None) -> list[str]:
    """2-4 reasons. BUY/SELL: the strongest supporting facts. WAIT: the best of both sides."""
    by_w = sorted(sentences, key=lambda x: -x[1])
    if action in ("BUY", "SELL"):
        d = 1 if action == "BUY" else -1
        picked = [s for side, _, s in by_w if side == d][:4]
        if len(picked) < 2:
            picked += [s for side, _, s in by_w if side == 0][: 2 - len(picked)]
        return picked
    d = 1 if lean == "long" else -1 if lean == "short" else 0
    if d == 0:
        return [s for _, _, s in by_w][:3]
    pro = [s for side, _, s in by_w if side == d][:2]
    con = [s for side, _, s in by_w if side != d][:2]
    return (pro + con)[:4] if pro or con else [s for _, _, s in by_w][:3]


# ---------------- WAIT conditions ----------------
def _nearest(analysis: dict, facts: MarketFacts) -> tuple[float | None, float | None]:
    tf = ((analysis.get("key_levels") or {}))
    res = sorted([l["price"] for l in tf.get("resistances", []) if l["price"] > facts.price])
    sup = sorted([l["price"] for l in tf.get("supports", []) if l["price"] < facts.price], reverse=True)
    return (res[0] if res else facts.high_60d), (sup[0] if sup else facts.low_60d)


def waiting_for(symbol: Symbol, d: Decision, plan: LevelPlan | None, facts: MarketFacts, analysis: dict,
                today: date | None = None, min_rr: float = 1.5) -> list[str]:
    f = lambda x: fmt_price(symbol, x)
    res, sup = _nearest(analysis, facts)
    long = d.lean == "long"
    trigger = (plan.breakout_level if plan and plan.breakout_level else (res if long else sup))
    out: list[str] = []
    codes = d.wait_codes
    conflicts = {"no_direction", "trend_not_confirming", "timeframes_conflict", "components_conflict"}

    if "no_direction" in codes or d.lean is None:
        parts = []
        if res:
            parts.append(f"a daily close above {f(res)} would point to a buy")
        if sup:
            parts.append(f"a daily close below {f(sup)} would point to a sell")
        out.append("Wait for a clear direction: " + (" – ".join(parts) if parts else "the signals are too weak right now"))
    if "trend_not_confirming" in codes and d.lean:
        what = f" – for example a daily close {'above' if long else 'below'} {f(trigger)}" if trigger else ""
        out.append(f"Wait for the price trend to turn {'up' if long else 'down'} as well{what}")
    if "timeframes_conflict" in codes:
        out.append("Wait until the daily and weekly charts point in the same direction")
    if "components_conflict" in codes:
        names = join_words([component_word(x, symbol) for x in d.oppose])
        out.append(f"Wait until {names} stop pointing the other way")
    if "low_confidence" in codes and not (conflicts & set(codes)):
        out.append("Wait for stronger agreement between the price trend, the news and the forecast")
    if "event" in codes and d.blocking_event:
        e = d.blocking_event
        what = e["plain"] if e["title"] != "Earnings" else "company's earnings report"
        out.append(f"Wait until after the {what} {fmt_day(e['date'], today)} – big news can move the price sharply")
    if "stale_data" in codes:
        out.append(f"Wait for fresh prices – the latest data is from {fmt_day(facts.last_bar[:10], today)}")
    if "stop_too_wide" in codes and plan:
        out.append(f"Wait for a calmer market – a safe stop loss would have to be {fmt_distance(symbol, plan.entry_mid, plan.stop)} "
                   f"away right now, which is too far")
    if "level_too_close" in codes and plan and plan.breakout_level:
        out.append(f"Wait for a daily close {'above' if long else 'below'} {f(plan.breakout_level)} – that level is right in front "
                   f"of the price and could push it back")
    elif "rr_too_low" in codes and plan:
        if plan.better_entry:
            out.append(f"Wait for the price to {'dip' if long else 'rise'} to about {f(plan.better_entry)} – from there the "
                       f"possible gain would be at least {min_rr:g}× the risk")
        else:
            out.append(f"Wait – the next level at {f(plan.target1_level or plan.target1)} is too close, so the possible gain "
                       f"isn't worth the risk")
    if "no_levels" in codes:
        out.append("Wait – there isn't enough price history to place a safe stop loss")
    return list(dict.fromkeys(out))


# ---------------- main texts ----------------
def confidence_text(d: Decision, symbol: Symbol) -> str:
    w = lambda xs: join_words([component_word(x, symbol) for x in xs])
    verb = lambda xs: "is" if len(xs) == 1 else "are"
    if d.confidence == "High":
        return f"High – {w(d.agree)} all point the same way"
    if d.confidence == "Medium":
        if d.oppose:
            return f"Medium – {w(d.agree)} agree, but {w(d.oppose)} {'points' if len(d.oppose) == 1 else 'point'} the other way"
        if d.mixed:
            return f"Medium – {w(d.agree)} {'agree' if len(d.agree) > 1 else 'is clear'}, but {w(d.mixed)} {verb(d.mixed)} mixed"
        return f"Medium – {w(d.agree)} agree, but the signal isn't very strong yet"
    if d.oppose and d.agree:
        return f"Low – {w(d.agree)} and {w(d.oppose)} disagree"
    return "Low – the signals are weak or mixed"


def money_texts(symbol: Symbol, action: str, rr1: float, rr2: float, size: PositionSize | None, ccy: str) -> dict:
    """Risk/reward sentence, position-size sentence and per-target money. Recomputed whenever the user
    changes the account size / risk % / currency, so it's separate from the stored explanation."""
    ccy = size.currency if size else ccy
    sign = CURRENCY_SIGNS.get(ccy, "")
    one = f"{sign}1" if sign else f"1 {ccy}"
    out = {"rr_text": f"You risk {one} to potentially make {fmt_money(rr1, ccy)} at target 1 "
                      f"(or {fmt_money(rr2, ccy)} at target 2)",
           "size_text": "", "size_note": "", "target_money": [None, None]}
    if not size or action not in ACTION_WORD:
        return out
    verb = ACTION_WORD[action]
    if size.too_small:
        unit = "0.01 lots" if symbol.is_fx else "1 share"
        out["size_text"] = f"Your risk amount is too small for the smallest trade ({unit})"
        out["size_note"] = (f"{unit} would risk {fmt_money(size.min_trade_risk, size.currency)}, more than your "
                            f"{fmt_money(size.risk_budget, size.currency)}. Increase the risk % or skip this trade.")
    else:
        if symbol.is_fx:
            out["size_text"] = (f"{verb} {size.lots:.2f} lots ({size.units:,.0f} units) – risk "
                                f"{fmt_money(size.actual_risk, size.currency)}")
            out["size_note"] = (f"Margin needed ≈ {fmt_money(size.margin_or_cost, size.currency)} · "
                                f"1 pip ≈ {fmt_money(size.pip_value, size.currency)} at this size")
        else:
            out["size_text"] = f"{verb} {size.units:,.0f} shares – risk {fmt_money(size.actual_risk, size.currency)}"
            out["size_note"] = f"Cost ≈ {fmt_money(size.margin_or_cost, size.currency)}"
        out["target_money"] = [fmt_money(size.gain_target1, size.currency, signed=True),
                               fmt_money(size.gain_target2, size.currency, signed=True)]
    if not size.converted:
        out["size_note"] += f" (no exchange rate found, amounts are in {size.currency})"
    return out


def build_explanation(
    symbol: Symbol,
    d: Decision,
    plan: LevelPlan | None,
    facts: MarketFacts,
    analysis: dict,
    events: list[UpcomingEvent],
    size: PositionSize | None,
    expires_at: datetime,
    warning_days: int = 7,
    min_rr: float = 1.5,
    today: date | None = None,
) -> Explanation:
    f = lambda x: fmt_price(symbol, x)
    reasons = pick_reasons(fact_sentences(symbol, facts, analysis), d.action, d.lean)
    wait = waiting_for(symbol, d, plan, facts, analysis, today, min_rr) if d.action == "WAIT" else []
    exp = expires_at.strftime("%a %d %b %H:%M UTC").replace(" 0", " ")

    entry_text = entry_confirm = stop_text = stop_why = rr_text = size_text = size_note = ""
    targets: list[dict] = []
    cancel: list[str] = []
    if plan is not None and d.action in ("BUY", "SELL"):
        long = d.action == "BUY"
        verb = ACTION_WORD[d.action]
        entry_text = f"{verb} between {f(min(plan.entry_low, plan.entry_high))} and {f(max(plan.entry_low, plan.entry_high))}"
        edge = plan.entry_low if long else plan.entry_high
        if plan.entry_kind == "pullback" and plan.entry_anchor:
            entry_confirm = (f"Only enter if a daily candle closes {'above' if long else 'below'} {f(edge)} – that shows "
                             f"{'buyers' if long else 'sellers'} are defending the level at {f(plan.entry_anchor)}")
        else:
            entry_confirm = (f"This is around the current price. Only enter if a daily candle closes "
                             f"{'above' if long else 'below'} {f(edge)}")

        stop_text = f"{f(plan.stop)} ({fmt_distance(symbol, plan.entry_mid, plan.stop)} {'below' if long else 'above'} your entry)"
        side = "low" if long else "high"
        if plan.stop_kind == "swing" and plan.stop_anchor:
            stop_why = (f"{'Below' if long else 'Above'} the recent {side} of {f(plan.stop_anchor)} "
                        f"({fmt_day(plan.stop_anchor_date, today)}) plus a small safety margin, so a normal "
                        f"{'dip' if long else 'bounce'} won't knock you out")
        elif plan.stop_kind == "min_distance":
            stop_why = (f"About one normal day's price movement {'below' if long else 'above'} your entry, so ordinary "
                        f"ups and downs won't knock you out (the recent {side} is too close to use)")
        else:
            stop_why = (f"About one and a half normal days' movement {'below' if long else 'above'} the entry zone – "
                        f"there's no recent {side} to hide behind")

        for i, (t, kind, lvl) in enumerate(((plan.target1, plan.target1_kind, plan.target1_level),
                                             (plan.target2, plan.target2_kind, None)), start=1):
            pct = abs(t - plan.entry_mid) / plan.entry_mid * 100
            why = (f"just before {f(lvl)}, where the price turned back before" if kind == "level" and lvl
                   else "just before the next level where the price turned back before" if kind == "level"
                   else "estimated from how far the price normally moves – there's no clear level ahead")
            targets.append({"label": f"Target {i}", "price": t, "price_text": f(t),
                            "pct": round(pct, 2), "distance": fmt_distance(symbol, plan.entry_mid, t),
                            "money": None, "why": why})
        m = money_texts(symbol, d.action, plan.rr1, plan.rr2, size, size.currency if size else "EUR")
        rr_text, size_text, size_note = m["rr_text"], m["size_text"], m["size_note"]
        for t, money in zip(targets, m["target_money"]):
            t["money"] = money

        cancel = [
            f"If the price closes {'below' if long else 'above'} {f(plan.stop)} before you enter, this idea is no longer valid – don't enter",
            f"If the price reaches {f(plan.target1)} before you enter, you've missed it – don't chase it",
            f"If you haven't entered by {exp}, the signal has expired",
        ]
        soon = [e for e in events if e.major and e.days_away <= max(3, warning_days // 2)]
        if soon:
            e = soon[0]
            cancel.append(f"If you haven't entered before the {e.plain} {fmt_day(e.date, today)}, wait until after it")

    warn = None
    near = [e for e in events if e.days_away <= warning_days]
    if near:
        e = near[0]
        words = "the company's earnings report" if e.title == "Earnings" else f"the {e.plain}"
        warn = f"{_cap(words)} is {fmt_day(e.date, today)}" + (" – expect big price moves" if e.major else "")

    return Explanation(
        reasons=reasons, waiting_for=wait, entry_text=entry_text, entry_confirm=entry_confirm,
        stop_text=stop_text, stop_why=stop_why, targets=targets, cancel=cancel,
        confidence_text=confidence_text(d, symbol), rr_text=rr_text, size_text=size_text, size_note=size_note,
        event_warning=warn, events=[e.as_dict() for e in events if e.days_away <= max(warning_days, 14)][:6],
    )
