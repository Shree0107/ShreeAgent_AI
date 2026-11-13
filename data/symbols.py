"""Symbol model, parsing, provider-specific tickers and Investing.com links.

Canonical forms:
  forex / metals : "EUR/USD", "XAU/USD"
  stocks         : Yahoo-style tickers, "AAPL", "RELIANCE.NS" (NSE), "500325.BO" (BSE)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote_plus

import yaml

from config.settings import ROOT

log = logging.getLogger(__name__)

CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "INR", "CNY", "SGD", "HKD", "SEK", "NOK", "ZAR", "MXN"}
METALS = {"XAU", "XAG"}
INVESTING_BASE = "https://www.investing.com"


@dataclass(frozen=True)
class Symbol:
    ticker: str            # canonical, e.g. "EUR/USD" or "RELIANCE.NS"
    asset_class: str       # forex | metal | stock | index
    market: str            # FX | US | NSE | BSE | INDEX
    name: str = ""

    @property
    def is_fx(self) -> bool:
        return self.asset_class in ("forex", "metal")

    @property
    def has_real_volume(self) -> bool:
        # Spot FX has no centralised volume. Yahoo returns zeros, so volume indicators are skipped.
        return self.asset_class in ("stock", "index")

    @property
    def base(self) -> str:
        return self.ticker.split("/")[0] if self.is_fx else ""

    @property
    def quote(self) -> str:
        return self.ticker.split("/")[1] if self.is_fx else ""

    @property
    def yahoo(self) -> str:
        if self.asset_class == "metal":
            # Yahoo has no reliable spot-metal ticker. Front-month futures track spot closely.
            return {"XAU": "GC=F", "XAG": "SI=F"}[self.base]
        if self.asset_class == "forex":
            return f"{self.base}{self.quote}=X"
        return self.ticker

    @property
    def twelvedata(self) -> str:
        if self.is_fx:
            return self.ticker
        if self.market == "NSE":
            return f"{self.ticker.removesuffix('.NS')}:NSE"
        if self.market == "BSE":
            return f"{self.ticker.removesuffix('.BO')}:BSE"
        return self.ticker

    @property
    def plain(self) -> str:
        """Ticker without exchange suffix (for news APIs)."""
        return self.ticker.split(".")[0].replace("/", "")

    @property
    def investing_url(self) -> str:
        path = _investing_paths().get(self.ticker)
        if path:
            return f"{INVESTING_BASE}/{path}"
        return f"{INVESTING_BASE}/search/?q={quote_plus(self.plain if not self.is_fx else self.ticker)}"


@dataclass
class SymbolCandidate:
    symbol: Symbol
    exchange: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _symbol_config() -> dict:
    path = ROOT / "config" / "symbols.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _investing_paths() -> dict[str, str]:
    cfg = _symbol_config()
    out = {}
    for section in ("forex", "stocks"):
        for tk, meta in (cfg.get(section) or {}).items():
            if meta and meta.get("investing"):
                out[tk] = meta["investing"]
    return out


def _aliases() -> dict[str, str]:
    out = {}
    for tk, meta in (_symbol_config().get("stocks") or {}).items():
        out[tk.lower()] = tk
        out[tk.split(".")[0].lower()] = tk
        for a in (meta or {}).get("aliases", []) or []:
            out[str(a).lower()] = tk
    return out


def related_tickers(sym: Symbol) -> list[str]:
    rel = _symbol_config().get("related") or {}
    if sym.ticker in rel:
        return list(rel[sym.ticker])
    if sym.asset_class == "stock":
        return list(rel.get(f"_{sym.market}", []))
    return []


def market_from_ticker(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith(".NS"):
        return "NSE"
    if t.endswith(".BO"):
        return "BSE"
    if t.startswith("^"):
        return "INDEX"
    return "US"


def parse_symbol(text: str) -> Symbol | None:
    """Parse an unambiguous symbol string, or return None.

    Accepts "EUR/USD", "eurusd", "EURUSD=X", "XAUUSD", "AAPL", "RELIANCE.NS", "^NSEI".
    A bare word like "reliance" is matched against the alias table.
    """
    if not text:
        return None
    raw = text.strip()
    t = raw.upper().replace(" ", "").removesuffix("=X")
    m = re.fullmatch(r"([A-Z]{3})[/\-_]?([A-Z]{3})", t)
    if m and (m.group(1) in CURRENCIES | METALS) and m.group(2) in CURRENCIES:
        base, quote = m.groups()
        cls = "metal" if base in METALS else "forex"
        return Symbol(f"{base}/{quote}", cls, "FX", f"{base}/{quote}")
    alias = _aliases().get(raw.lower())
    if alias:
        return Symbol(alias, "stock", market_from_ticker(alias), alias)
    if t.startswith("^"):
        return Symbol(t, "index", "INDEX", t)
    if re.fullmatch(r"[A-Z0-9&\-]{1,15}(\.(NS|BO))?", t):
        return Symbol(t, "stock", market_from_ticker(t), t)
    if re.fullmatch(r"[A-Z0-9&\-]{1,15}\.[A-Z]{1,4}", t):  # other Yahoo tickers, e.g. DX-Y.NYB (dollar index)
        return Symbol(t, "index", "INDEX", t)
    return None


def search_symbols(query: str, limit: int = 8) -> list[SymbolCandidate]:
    """Resolve free text ("tata motors", "apple") to candidate symbols.

    Order: exact parse/alias -> Yahoo Finance search (US + NSE/BSE listings).
    """
    out: list[SymbolCandidate] = []
    q = (query or "").strip()
    if not q:
        return out
    direct = _aliases().get(q.lower())
    if direct:
        out.append(SymbolCandidate(Symbol(direct, "stock", market_from_ticker(direct), direct), "alias", 1.0))
    parsed = parse_symbol(q)
    if parsed and parsed.is_fx:
        return [SymbolCandidate(parsed, "FX", 1.0)]

    try:
        import yfinance as yf

        res = yf.Search(q, max_results=limit, news_count=0)
        for item in getattr(res, "quotes", []) or []:
            tk = item.get("symbol", "")
            qtype = (item.get("quoteType") or "").upper()
            if qtype not in ("EQUITY", "ETF", "INDEX") or not tk:
                continue
            exch = item.get("exchange", "")
            mkt = market_from_ticker(tk)
            # Only keep US, NSE and BSE listings, the supported markets.
            if mkt == "US" and "." in tk:
                continue
            name = item.get("longname") or item.get("shortname") or tk
            cls = "index" if qtype == "INDEX" else "stock"
            score = float(item.get("score") or 0) + (5e5 if mkt == "NSE" else 0)
            if not any(c.symbol.ticker == tk for c in out):
                out.append(SymbolCandidate(Symbol(tk, cls, mkt, name), exch, score))
    except Exception as e:  # network or library change: fall back to the direct parse
        log.warning("Symbol search failed for %r: %s", q, e)

    if not out and parsed:
        out.append(SymbolCandidate(parsed, parsed.market, 0.5))
    return out[:limit]


def resolve(text: str) -> Symbol:
    """Best single match or raise ValueError."""
    t = (text or "").strip()
    sym = parse_symbol(t)
    if sym and (sym.is_fx or sym.asset_class == "index" or "." in sym.ticker or t.lower() in _aliases()):
        return sym
    if sym and t.isupper() and len(t) <= 6:  # typed like a ticker, e.g. "AAPL"
        return sym
    cands = search_symbols(t)
    if cands:
        return cands[0].symbol
    if sym:
        return sym
    raise ValueError(f"Could not resolve symbol '{text}'")
