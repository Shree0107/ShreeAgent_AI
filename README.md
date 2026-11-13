# ShreeAgent AI

A personal AI trading-analysis assistant for **forex, gold, US stocks and Indian stocks (NSE/BSE)**.
It combines technical analysis, fundamental/macro analysis, news sentiment and **Google TimesFM-3** price forecasts,
and a **Claude**-powered agent explains everything in plain language.

> **Analysis only.** ShreeAgent AI never places, modifies or cancels trades and has no broker connection.
> Nothing it produces is financial advice. You make the final decision.

## Features
- **Technical:** SMA/EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, ADX, volume/OBV, VWAP, support/resistance,
  candlestick patterns, trend; multi-timeframe (1H / 4H / D / W) with an explained bullish/bearish/neutral score.
- **Fundamental:** stocks: P/E vs sector, EPS, growth, margins, ROE, debt, analyst target, earnings date.
  Forex: policy-rate & yield differentials, inflation, GDP, central-bank lean, upcoming events (FRED + curated calendar).
- **News sentiment:** Marketaux / Finnhub / Yahoo headlines scored with FinBERT.
- **Forecasting:** TimesFM-3 zero-shot, multivariate (related assets such as DXY/NIFTY, plus volume), quantile bands,
  and a rolling **backtest vs a naive baseline** (MAE, MAPE, directional accuracy, interval coverage) so you know how far to trust it.
- **Beginner signals:** one card per watchlist symbol with a clear **BUY / SELL / WAIT**, plain-language reasons,
  what to wait for, an exact entry zone, a structure-based stop loss, two targets with % and money, cancel conditions,
  confidence, event warnings, expiry, an XTB-style position-size helper (lots/shares) and a tracked win rate.
  BUY/SELL only when the checks agree, no major event is close and reward/risk ≥ 1.5 (configurable).
- **Agent:** ask *"Analyse EUR/USD for this week"* or *"Is RELIANCE a buy right now?"*. You get a structured report with
  bias, key levels, entry/SL/TP zones, R:R, risks and confidence. Levels are computed in code, not invented by the LLM.
- **Dashboard (Streamlit):** watchlist, interactive charts, forecast chart with bands, fundamentals, news, agent chat,
  Markdown/PDF export, watchlist scan.
- **Alerts:** daily WhatsApp digest (CallMeBot or Twilio).
- Every report links to the matching **Investing.com** page for a manual cross-check (no scraping).

## Quick start
```bash
python -m venv .venv && .venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
copy .env.example .env                                   # then add your API keys
streamlit run ui/app.py
```
Or with Docker: `docker compose up -d --build` and open http://localhost:8501.

**Full step-by-step instructions (API keys, model download, alerts, troubleshooting): [SETUP.md](SETUP.md).**

## Project layout
```
config/       settings (.env), symbol aliases + Investing.com links, FRED series, event calendar, default watchlist
data/         provider interfaces + yfinance / Twelve Data / FRED / Finnhub / Marketaux, SQLite cache, DataService
analysis/     indicators, levels, patterns, technical (multi-timeframe), fundamental, macro_fx, sentiment, trade_plan, combined
forecasting/  TimesFM-3 + naive models, input features, backtest, metrics, service
signals/      beginner BUY/SELL/WAIT engine: structure, levels, decision gates, sizing, events, plain-language
              templates, locked-number LLM polish, SQLite history + outcome tracking
agent/        LLM providers (Claude, OpenAI-compatible), tools, prompt, agent loop, report export
alerts/       WhatsApp notifiers, watchlist scanner, scheduler
ui/           Streamlit dashboard + Plotly charts
scripts/      download_model.py, run_backtest.py
tests/        offline unit tests (pytest)
```

## Tests
```bash
python -m pytest
```
All tests run offline: market APIs, the LLM and the forecaster are replaced with fakes.

## Licences
Code: your own. **TimesFM-3 weights** are under Google's *TimesFM Non-Commercial License v1.0*, for personal,
non-commercial use only. Commercial use would need a forecaster adapter for an Apache-2.0 model such as TimesFM 2.5
or Chronos-2. Add a class with the same `forecast()` method in `forecasting/models.py`.
