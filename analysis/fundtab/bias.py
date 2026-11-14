"""Overall fundamental bias for any symbol (bullish / bearish / neutral + why in 1-3 plain sentences), and
stock key numbers turned into plain sentences. All numbers come from analysis/macro_fx.py and
analysis/fundamental.py; this module only words them."""
from __future__ import annotations

from datetime import date

from analysis.fundtab import BANK_SHORT, PLACE, cur_name

LEAN_WORDS = {"hawkish": "leaning to keep rates high or raise them", "dovish": "leaning to cut rates",
              "neutral": "on hold"}
HORIZON = "Big-picture view for the coming weeks and months, not a signal for today's trade."


def _cname(c: str) -> str:
    return cur_name(c).removeprefix("the ")


# ---------------- forex / metals ----------------
def fx_sentences(rep) -> list[tuple[float, str]]:
    """(weight, sentence) pairs, largest effect first."""
    b, q = rep.base, rep.quote
    out: list[tuple[float, str]] = []
    if rep.base.name in ("Gold", "Silver"):
        metal = rep.base.name.lower()
        ry = rep.extra.get("real_yield_10y", {}).get("change_3m")
        usd = rep.extra.get("usd_broad_index", {}).get("change_3m")
        if ry is not None:
            out.append((1.0, f"US interest rates after inflation have {'risen' if ry > 0 else 'fallen'} over the last "
                             f"3 months, which usually {'weighs on' if ry > 0 else 'helps'} {metal}."))
        if usd is not None:
            out.append((0.9, f"The US dollar has {'strengthened' if usd > 0 else 'weakened'} over the last 3 months, "
                             f"which usually {'weighs on' if usd > 0 else 'helps'} {metal}."))
        return out
    if b.policy_rate is not None and q.policy_rate is not None:
        diff = b.policy_rate - q.policy_rate
        if abs(diff) >= 0.05:
            hi, lo = (b, q) if diff > 0 else (q, b)
            out.append((min(1.0, abs(diff) / 2) + 0.2,
                        f"Interest rates are higher in {PLACE.get(hi.currency, hi.currency)} ({hi.policy_rate:.2f}%) than "
                        f"in {PLACE.get(lo.currency, lo.currency)} ({lo.policy_rate:.2f}%), which tends to support "
                        f"{cur_name(hi.currency)}."))
        else:
            out.append((0.1, f"Interest rates are about the same in {PLACE.get(b.currency, b.currency)} and "
                             f"{PLACE.get(q.currency, q.currency)} ({b.policy_rate:.2f}%)."))
    if b.cb_lean in LEAN_WORDS and q.cb_lean in LEAN_WORDS:
        bb, qb = BANK_SHORT.get(b.currency, b.central_bank), BANK_SHORT.get(q.currency, q.central_bank)
        if b.cb_lean != q.cb_lean:
            out.append((0.6, f"The {bb} is {LEAN_WORDS[b.cb_lean]}, while the {qb} is {LEAN_WORDS[q.cb_lean]}."))
        else:
            out.append((0.05, f"Both the {bb} and the {qb} are {LEAN_WORDS[b.cb_lean]}."))
    if b.gdp_growth_yoy is not None and q.gdp_growth_yoy is not None and abs(b.gdp_growth_yoy - q.gdp_growth_yoy) >= 0.3:
        hi, lo = (b, q) if b.gdp_growth_yoy > q.gdp_growth_yoy else (q, b)
        out.append((0.4, f"The economy is growing faster in {PLACE.get(hi.currency, hi.currency)} "
                         f"({hi.gdp_growth_yoy:.1f}% a year) than in {PLACE.get(lo.currency, lo.currency)} "
                         f"({lo.gdp_growth_yoy:.1f}%)."))
    for cm in (b, q):
        if cm.inflation_yoy is not None and cm.inflation_target is not None and cm.inflation_yoy - cm.inflation_target > 1:
            out.append((0.3, f"Inflation in {PLACE.get(cm.currency, cm.currency)} ({cm.inflation_yoy:.1f}%) is well "
                             f"above the {cm.inflation_target:g}% target, so rates there may stay high."))
    return sorted(out, key=lambda x: -x[0])


def fx_bias(symbol, data) -> dict:
    from analysis.macro_fx import analyse_fx

    rep = analyse_fx(symbol, data=data)
    if not rep.n_factors:
        return {"symbol": symbol.ticker, "kind": "fx", "bias": "unknown", "score": None,
                "headline": "Not enough data",
                "why": ["Interest rates and inflation come from FRED and are unavailable. "
                        "Set FRED_API_KEY in .env (free at fred.stlouisfed.org)."],
                "horizon": HORIZON, "source": "FRED", "estimate": True}
    sents = [s for _, s in fx_sentences(rep)]
    if rep.bias == "bullish":
        lead = f"The big picture favours {cur_name(symbol.base) if symbol.base not in ('XAU', 'XAG') else symbol.base}, so {symbol.ticker} leans up."
    elif rep.bias == "bearish":
        lead = f"The big picture favours {cur_name(symbol.quote)}, so {symbol.ticker} leans down."
    else:
        lead = f"The big-picture factors roughly balance out for {symbol.ticker}."
    if symbol.base in ("XAU", "XAG"):
        lead = {"bullish": f"The big picture is supportive for {symbol.ticker}.",
                "bearish": f"The big picture is a headwind for {symbol.ticker}."}.get(rep.bias, lead)
    return {"symbol": symbol.ticker, "kind": "fx", "bias": rep.bias, "score": rep.score,
            "headline": rep.bias.capitalize(), "why": [lead] + sents[:2], "horizon": HORIZON,
            "source": "FRED (monthly/daily data; some figures lag by weeks)", "estimate": True,
            "factors": rep.n_factors}


# ---------------- stocks ----------------
def _fmt_money(x: float | None, cur: str | None) -> str:
    if x is None:
        return "–"
    return f"{x:,.2f} {cur or ''}".strip()


def stock_facts(rep) -> list[dict]:
    """Key numbers as plain sentences: {key, label, value, text, tone: good|bad|neutral, tip}."""
    m, v = rep.metrics, rep.valuation
    out: list[dict] = []

    def add(key, label, value, text, tone, tip=""):
        out.append({"key": key, "label": label, "value": value, "text": text, "tone": tone, "tip": tip})

    rg = m.get("revenue_growth_pct")
    if rg is not None:
        add("sales", "Sales growth", f"{rg:+.0f}%",
            f"The company's sales {'grew' if rg >= 0 else 'fell'} {abs(rg):.0f}% over the last year.",
            "good" if rg > 10 else "bad" if rg < 0 else "neutral", "Change in revenue (sales) compared with a year ago.")
    eg = m.get("earnings_growth_pct")
    if eg is not None:
        add("profit_growth", "Profit growth", f"{eg:+.0f}%",
            f"Its profits {'grew' if eg >= 0 else 'fell'} {abs(eg):.0f}% over the last year.",
            "good" if eg > 10 else "bad" if eg < -5 else "neutral", "Change in earnings compared with a year ago.")
    pm = m.get("profit_margin_pct")
    if pm is not None:
        add("margin", "Profit margin", f"{pm:.0f}%",
            f"Out of every 100 in sales, about {pm:.0f} is left as profit.",
            "good" if pm > 15 else "bad" if pm < 3 else "neutral", "Net profit margin: profit divided by sales.")
    pe, bench = v.get("pe"), v.get("sector_pe")
    if pe is not None and pe > 0:
        rel = v.get("vs_sector")
        cmp = ""
        tone = "neutral"
        if bench and rel is not None:
            cmp = (f" Similar companies: about {bench:g}, so it looks "
                   f"{'expensive' if rel > 30 else 'cheap' if rel < -20 else 'fairly priced'}.")
            tone = "bad" if rel > 30 else "good" if rel < -20 else "neutral"
        add("valuation", "Price vs profit (P/E)", f"{pe:.1f}",
            f"Buyers pay {pe:.1f} times the company's yearly profit for its shares.{cmp}", tone,
            "P/E = share price divided by yearly profit per share. Higher means more expensive.")
    elif pe is not None:
        add("valuation", "Price vs profit (P/E)", "–", "The company made a loss, so it has no meaningful P/E.", "bad",
            "P/E = share price divided by yearly profit per share.")
    de = m.get("debt_to_equity")
    if de is not None:
        ratio = de / 100
        is_fin = (m.get("sector") or "") == "Financial Services"
        level = "high" if ratio > 2 else "low" if ratio < 0.5 else "moderate"
        add("debt", "Debt", f"{ratio:.2f}x",
            f"It owes {ratio:.2f} times the money its owners have put in ({level} debt"
            f"{', normal for a bank' if is_fin and level == 'high' else ''}).",
            "neutral" if is_fin else "bad" if level == "high" else "good" if level == "low" else "neutral",
            "Debt-to-equity: total debt divided by shareholders' equity.")
    roe = m.get("roe_pct")
    if roe is not None:
        add("roe", "Return on owners' money", f"{roe:.0f}%",
            f"For every 100 the owners have invested, the company earns about {roe:.0f} a year.",
            "good" if roe > 15 else "bad" if roe < 5 else "neutral", "Return on equity (ROE).")
    return out


def earnings_info(rep, today: date | None = None) -> dict | None:
    ned = rep.metrics.get("next_earnings_date")
    if not ned:
        return None
    today = today or date.today()
    try:
        d = date.fromisoformat(str(ned)[:10])
    except ValueError:
        return None
    days = (d - today).days
    text = (f"Next earnings report: {d.isoformat()} (in {days} days). Share prices often jump around earnings."
            if days >= 0 else f"Last earnings report: {d.isoformat()}.")
    return {"date": d.isoformat(), "days_away": days, "text": text}


def analyst_info(rep) -> dict | None:
    m, v = rep.metrics, rep.valuation
    rec, tgt = m.get("recommendation"), m.get("analyst_target")
    if not rec and not tgt:
        return None
    parts = []
    if rec:
        parts.append(f"Analysts' average rating: {str(rec).replace('_', ' ')}.")
    up = v.get("analyst_upside_pct")
    if tgt:
        rel = f", {abs(up):.0f}% {'above' if up >= 0 else 'below'} today's price" if up is not None else ""
        parts.append(f"Their average price target is {_fmt_money(tgt, m.get('currency'))}{rel}.")
    parts.append("Analysts are often wrong; treat this as one opinion.")
    return {"recommendation": rec, "target": tgt, "upside_pct": up, "text": " ".join(parts)}


def stock_view(symbol, data) -> dict:
    from analysis.fundamental import analyse_stock

    rep = analyse_stock(symbol, data=data)
    return {"symbol": symbol.ticker, "name": rep.metrics.get("name"), "sector": rep.metrics.get("sector"),
            "price": rep.metrics.get("price"), "currency": rep.metrics.get("currency"),
            "facts": stock_facts(rep), "earnings": earnings_info(rep), "analysts": analyst_info(rep),
            "source": rep.source or "yfinance", "_rep": rep}


def stock_bias(symbol, data) -> dict:
    view = stock_view(symbol, data)
    rep = view.pop("_rep")
    facts = view["facts"]
    good = [f["text"] for f in facts if f["tone"] == "good"]
    bad = [f["text"] for f in facts if f["tone"] == "bad"]
    if not facts:
        return {"symbol": symbol.ticker, "kind": "stock", "bias": "unknown", "score": None,
                "headline": "Not enough data", "why": ["No company figures are available for this symbol."],
                "horizon": HORIZON, "source": view["source"], "estimate": True}
    if rep.bias == "bullish":
        why = ["The company's numbers look healthy overall."] + good[:2]
    elif rep.bias == "bearish":
        why = ["The company's numbers show some weak spots."] + bad[:2]
    else:
        why = ["The company's numbers are mixed."] + (good[:1] + bad[:1])
    return {"symbol": symbol.ticker, "kind": "stock", "bias": rep.bias, "score": rep.score,
            "headline": rep.bias.capitalize(), "why": why[:3], "horizon": HORIZON,
            "source": view["source"], "estimate": True}


def fundamental_bias(symbol, data) -> dict:
    return fx_bias(symbol, data) if symbol.is_fx else stock_bias(symbol, data)
