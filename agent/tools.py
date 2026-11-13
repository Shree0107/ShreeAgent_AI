"""Analysis modules exposed to the LLM as tools. Every tool returns compact JSON."""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from agent.llm.base import ToolSpec
from data.symbols import Symbol, resolve, search_symbols

log = logging.getLogger(__name__)

MAX_TOOL_CHARS = 14000
TF_ENUM = ["1h", "4h", "1d", "1wk"]


def _default(o):
    if isinstance(o, (datetime, date, pd.Timestamp)):
        return o.isoformat()
    if isinstance(o, (np.floating,)):
        return None if math.isnan(o) else round(float(o), 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def to_json(obj) -> str:
    s = json.dumps(obj, default=_default, separators=(",", ":"))
    if len(s) > MAX_TOOL_CHARS:
        s = s[:MAX_TOOL_CHARS] + '..."(truncated)"'
    return s


def _sym(symbol: str) -> Symbol:
    return resolve(symbol)


# ---------------- tool functions ----------------
def t_resolve_symbol(query: str) -> dict:
    cands = search_symbols(query)
    return {"query": query, "candidates": [
        {"ticker": c.symbol.ticker, "name": c.symbol.name, "market": c.symbol.market, "type": c.symbol.asset_class}
        for c in cands]}


def t_get_quote(symbol: str) -> dict:
    from data.service import get_data_service

    return get_data_service().last_price(_sym(symbol))


def t_technical(symbol: str, timeframes: list[str] | None = None) -> dict:
    from analysis.technical import analyse_symbol

    tfs = tuple(t for t in (timeframes or TF_ENUM) if t in TF_ENUM) or tuple(TF_ENUM)
    return analyse_symbol(_sym(symbol), tfs).as_dict(compact=True)


def t_fundamental(symbol: str) -> dict:
    sym = _sym(symbol)
    if sym.is_fx:
        from analysis.macro_fx import analyse_fx

        return analyse_fx(sym).as_dict()
    from analysis.fundamental import analyse_stock

    return analyse_stock(sym).as_dict()


def t_news(symbol: str, days: int = 7) -> dict:
    from analysis.sentiment import analyse_news

    return analyse_news(_sym(symbol), days=int(days)).as_dict()


def t_forecast(symbol: str, timeframe: str = "1d", horizon: int = 10) -> dict:
    from forecasting.service import forecast_symbol

    return forecast_symbol(_sym(symbol), timeframe, int(horizon)).as_dict(compact=False)


def t_backtest(symbol: str, timeframe: str = "1d", horizon: int = 10, windows: int = 30) -> dict:
    from forecasting.service import backtest_symbol

    return backtest_symbol(_sym(symbol), timeframe, int(horizon), n_windows=min(int(windows), 60)).as_dict()


def t_calendar(currencies: list[str], days: int = 14) -> dict:
    from data.service import get_data_service

    evs = get_data_service().upcoming_events([c.upper() for c in currencies], int(days))
    return {"events": [{"date": e.date.date().isoformat(), "currency": e.currency, "title": e.title,
                        "impact": e.impact, "source": e.source} for e in evs],
            "note": "US releases from FRED; central-bank dates from config/events.yaml"}


def t_trade_plan(symbol: str, timeframe: str = "1d", bias: str | None = None) -> dict:
    from analysis.technical import analyse_frame
    from analysis.trade_plan import build_plan
    from data.service import get_data_service

    sym = _sym(symbol)
    df = get_data_service().get_ohlcv(sym, timeframe)
    sig = analyse_frame(df, timeframe, sym.has_real_volume)
    b = bias or sig.bias
    plan = build_plan(b, sig.snapshot["close"], sig.snapshot["atr_14"],
                      [l["price"] for l in sig.supports], [l["price"] for l in sig.resistances])
    return {"symbol": sym.ticker, "timeframe": timeframe, "bias_used": b, "price": sig.snapshot["close"],
            **plan.as_dict(), "supports": sig.supports, "resistances": sig.resistances}


def t_full(symbol: str, timeframe: str = "1d", horizon: int = 10, include_forecast: bool = True) -> dict:
    from analysis.combined import full_analysis

    return full_analysis(_sym(symbol), timeframe, int(horizon), include_forecast=bool(include_forecast))


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


SYM = {"type": "string", "description": "Ticker or name, e.g. 'EUR/USD', 'XAU/USD', 'AAPL', 'RELIANCE.NS', 'reliance'"}
TF = {"type": "string", "enum": TF_ENUM, "description": "Candle timeframe"}

TOOLS: list[ToolSpec] = [
    ToolSpec("full_analysis",
             "Run the complete pipeline for one symbol: multi-timeframe technicals, fundamentals (stock financials "
             "or FX macro), news sentiment, TimesFM-3 forecast (with backtest trust if available), combined score/"
             "confidence, key levels and an ATR-based trade plan. Best first call for 'analyse X' or 'is X a buy'.",
             _schema({"symbol": SYM, "timeframe": TF,
                      "horizon": {"type": "integer", "minimum": 1, "maximum": 128, "description": "Forecast candles"},
                      "include_forecast": {"type": "boolean"}}, ["symbol"]), t_full),
    ToolSpec("resolve_symbol", "Find ticker candidates for a company or instrument name (US, NSE, BSE, forex).",
             _schema({"query": {"type": "string"}}, ["query"]), t_resolve_symbol),
    ToolSpec("get_quote", "Latest daily close, % change, data source and Investing.com cross-check link.",
             _schema({"symbol": SYM}, ["symbol"]), t_get_quote),
    ToolSpec("technical_analysis", "Indicators, trend, support/resistance, candlestick patterns and a bullish/"
             "bearish/neutral score per timeframe plus a weighted multi-timeframe score.",
             _schema({"symbol": SYM, "timeframes": {"type": "array", "items": TF}}, ["symbol"]), t_technical),
    ToolSpec("fundamental_analysis", "Stocks: valuation vs sector, growth, margins, debt, earnings date. "
             "Forex/metals: rate & yield differentials, inflation, GDP, central-bank lean, upcoming events.",
             _schema({"symbol": SYM}, ["symbol"]), t_fundamental),
    ToolSpec("news_sentiment", "Recent headlines with sentiment scores (-1..1) and an average.",
             _schema({"symbol": SYM, "days": {"type": "integer", "minimum": 1, "maximum": 30}}, ["symbol"]), t_news),
    ToolSpec("price_forecast", "TimesFM-3 zero-shot forecast: median path with 10/25/75/90% quantile bands, "
             "expected % change, probability of finishing higher, and the latest backtest metrics if one exists.",
             _schema({"symbol": SYM, "timeframe": TF,
                      "horizon": {"type": "integer", "minimum": 1, "maximum": 128}}, ["symbol"]), t_forecast),
    ToolSpec("forecast_backtest", "Rolling backtest of TimesFM-3 vs a naive no-change baseline (MAE, MAPE, "
             "directional accuracy, interval coverage, trust label). Slow on CPU (about 1 minute).",
             _schema({"symbol": SYM, "timeframe": TF, "horizon": {"type": "integer", "minimum": 1, "maximum": 64},
                      "windows": {"type": "integer", "minimum": 5, "maximum": 60}}, ["symbol"]), t_backtest),
    ToolSpec("economic_calendar", "Upcoming high-impact events (US data releases, central bank decisions).",
             _schema({"currencies": {"type": "array", "items": {"type": "string"}},
                      "days": {"type": "integer", "minimum": 1, "maximum": 60}}, ["currencies"]), t_calendar),
    ToolSpec("trade_plan", "ATR + support/resistance based entry zone, stop-loss, take-profits and R:R for a "
             "given bias on one timeframe. Analysis only: no orders are ever placed.",
             _schema({"symbol": SYM, "timeframe": TF,
                      "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]}}, ["symbol"]), t_trade_plan),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def execute_tool(name: str, args: dict) -> tuple[str, bool]:
    """Run a tool. Errors come back as text so the model can recover (e.g. try another symbol)."""
    spec = TOOLS_BY_NAME.get(name)
    if not spec:
        return f"Unknown tool {name}", True
    allowed = set(spec.input_schema["properties"])
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    missing = [r for r in spec.input_schema.get("required", []) if r not in clean]
    if missing:
        return f"Missing required argument(s): {missing}", True
    try:
        return to_json(spec.func(**clean)), False
    except Exception as e:
        log.exception("Tool %s failed", name)
        return f"{type(e).__name__}: {e}", True
