"""Stock fundamental analysis: valuation, growth, profitability, balance sheet, earnings timing."""
from __future__ import annotations

import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date

from data.symbols import Symbol

log = logging.getLogger(__name__)

# Rough long-run sector median trailing P/E. Used only when peer data isn't available.
# Indian equities usually trade at a premium, so they get a multiplier.
SECTOR_PE = {
    "Technology": 28, "Communication Services": 20, "Consumer Cyclical": 22, "Consumer Defensive": 22,
    "Healthcare": 24, "Financial Services": 14, "Industrials": 22, "Energy": 12, "Basic Materials": 15,
    "Utilities": 18, "Real Estate": 30,
}
INDIA_PE_MULTIPLIER = 1.3


@dataclass
class FundamentalReport:
    symbol: str
    score: float
    bias: str
    metrics: dict
    valuation: dict
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    upcoming: list[str] = field(default_factory=list)
    source: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _pct(x):
    return None if x is None else round(x * 100, 2)


def sector_pe_benchmark(symbol: Symbol, sector: str | None, peer_pes: list[float]) -> tuple[float | None, str]:
    clean = [p for p in peer_pes if p and 0 < p < 200]
    if len(clean) >= 3:
        return round(statistics.median(clean), 1), f"median of {len(clean)} peers"
    base = SECTOR_PE.get(sector or "")
    if base is None:
        return None, "n/a"
    if symbol.market in ("NSE", "BSE"):
        return round(base * INDIA_PE_MULTIPLIER, 1), "approx. Indian sector median"
    return float(base), "approx. sector median"


def evaluate(symbol: Symbol, f: dict, peer_pes: list[float] | None = None) -> FundamentalReport:
    """Score fundamentals in [-100, 100] from simple, explainable rules."""
    pts: list[tuple[float, str]] = []
    strengths, weaknesses = [], []

    def add(v: float, text: str):
        pts.append((v, text))
        (strengths if v > 0 else weaknesses).append(text)

    pe = f.get("pe_trailing")
    bench, bench_src = sector_pe_benchmark(symbol, f.get("sector"), peer_pes or [])
    valuation = {"pe": pe, "pe_forward": f.get("pe_forward"), "sector_pe": bench, "benchmark": bench_src, "vs_sector": None}
    if pe and pe > 0 and bench:
        rel = pe / bench - 1
        valuation["vs_sector"] = round(rel * 100, 1)
        if rel < -0.2:
            add(1, f"P/E {pe:.1f} is {abs(rel)*100:.0f}% below sector ({bench})")
        elif rel > 0.3:
            add(-1, f"P/E {pe:.1f} is {rel*100:.0f}% above sector ({bench}), rich valuation")
    elif pe is not None and pe <= 0:
        add(-1, "Negative earnings (no meaningful P/E)")
    if f.get("pe_forward") and pe and f["pe_forward"] < pe * 0.9:
        add(0.5, f"Forward P/E {f['pe_forward']:.1f} < trailing, earnings expected to grow")

    rg, eg = f.get("revenue_growth"), f.get("earnings_growth")
    if rg is not None:
        if rg > 0.10:
            add(1, f"Revenue growth {rg*100:.1f}% YoY")
        elif rg < 0:
            add(-1, f"Revenue shrinking {rg*100:.1f}% YoY")
    if eg is not None:
        if eg > 0.10:
            add(1, f"Earnings growth {eg*100:.1f}% YoY")
        elif eg < -0.05:
            add(-1, f"Earnings falling {eg*100:.1f}% YoY")

    pm, roe = f.get("profit_margin"), f.get("roe")
    if pm is not None:
        if pm > 0.15:
            add(0.7, f"High net margin {pm*100:.1f}%")
        elif pm < 0.03:
            add(-0.7, f"Thin net margin {pm*100:.1f}%")
    if roe is not None:
        if roe > 0.15:
            add(0.7, f"Strong ROE {roe*100:.1f}%")
        elif roe < 0.05:
            add(-0.5, f"Weak ROE {roe*100:.1f}%")

    de = f.get("debt_to_equity")  # Yahoo reports this as a percent (e.g. 150 = 1.5x)
    is_fin = (f.get("sector") or "") == "Financial Services"  # high leverage is normal for banks
    if de is not None and not is_fin:
        if de > 200:
            add(-1, f"High leverage: debt/equity {de/100:.2f}x")
        elif de < 50:
            add(0.5, f"Conservative balance sheet: debt/equity {de/100:.2f}x")

    tgt, price = f.get("analyst_target"), f.get("price")
    if tgt and price:
        up = tgt / price - 1
        valuation["analyst_upside_pct"] = round(up * 100, 1)
        if up > 0.15:
            add(0.5, f"Analyst mean target implies {up*100:.0f}% upside")
        elif up < -0.05:
            add(-0.5, f"Price above analyst mean target ({up*100:.0f}%)")

    upcoming = []
    ned = f.get("next_earnings_date")
    if ned:
        try:
            days = (date.fromisoformat(str(ned)[:10]) - date.today()).days
            if 0 <= days <= 30:
                upcoming.append(f"Earnings in {days} days ({ned}): expect volatility")
            elif days > 30:
                upcoming.append(f"Next earnings {ned}")
        except ValueError:
            pass

    score = round(100 * sum(v for v, _ in pts) / max(len(pts), 4), 1) if pts else 0.0
    bias = "bullish" if score >= 20 else "bearish" if score <= -20 else "neutral"
    metrics = {
        "name": f.get("name"), "sector": f.get("sector"), "industry": f.get("industry"),
        "market_cap": f.get("market_cap"), "price": price, "currency": f.get("currency"),
        "pe_trailing": pe, "pe_forward": f.get("pe_forward"), "peg": f.get("peg"), "price_to_book": f.get("price_to_book"),
        "eps_trailing": f.get("eps_trailing"), "eps_forward": f.get("eps_forward"),
        "revenue_growth_pct": _pct(rg), "earnings_growth_pct": _pct(eg),
        "gross_margin_pct": _pct(f.get("gross_margin")), "operating_margin_pct": _pct(f.get("operating_margin")),
        "profit_margin_pct": _pct(pm), "roe_pct": _pct(roe), "debt_to_equity": de, "current_ratio": f.get("current_ratio"),
        "dividend_yield": f.get("dividend_yield"), "beta": f.get("beta"),
        "52w_high": f.get("fifty_two_week_high"), "52w_low": f.get("fifty_two_week_low"),
        "analyst_target": tgt, "recommendation": f.get("recommendation"), "next_earnings_date": ned,
    }
    return FundamentalReport(symbol.ticker, score, bias, metrics, valuation, strengths, weaknesses, upcoming)


def analyse_stock(symbol: Symbol, data=None) -> FundamentalReport:
    from data.service import get_data_service

    data = data or get_data_service()
    fund = data.get_fundamentals(symbol)
    peer_pes: list[float] = []
    for p in data.get_peers(symbol)[:6]:
        try:
            from data.symbols import Symbol as S

            pf = data.get_fundamentals(S(p, "stock", "US", p))
            if pf.data.get("pe_trailing"):
                peer_pes.append(pf.data["pe_trailing"])
        except Exception:
            continue
    rep = evaluate(symbol, fund.data, peer_pes)
    rep.source = fund.source
    return rep
