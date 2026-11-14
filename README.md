# ShreeAgent AI

A personal trading-analysis platform in your browser for **forex, gold and global stocks**. It's built for
beginners: live charts, plain-language **BUY / SELL / WAIT** trade plans, fundamentals, **Google TimesFM-3**
forecasts and honest backtests. A **Claude**-powered assistant answers questions in plain words.

> **Analysis only.** ShreeAgent AI never places, modifies or cancels trades and has no broker connection.
> Nothing it produces is financial advice. You make the final decision.

## The five tabs
- **Chart.**
  - Live candles from 1 minute to weekly (OANDA demo feed for forex/gold, Yahoo for stocks, labelled
    *Live* / *Delayed*), drawn with TradingView Lightweight Charts.
  - Candles, line or Heikin Ashi, indicators, drawing tools saved per symbol, and screenshots.
  - An **AI analysis overlay** that draws trendlines, channels, support/resistance, market structure (BOS/CHoCH),
    Fibonacci, liquidity and stop hunts, order blocks, fair value gaps and supply/demand zones.
- **Trade Plan.**
  - One beginner card per watchlist symbol for intraday (15-minute) or swing (daily) trading. It gives the exact
    entry and order type, stop loss, two targets in pips and money, XTB lot size, break-even, close-by time and
    cancel conditions.
  - A live status line: Waiting → Ready → Entry triggered → In trade → result.
  - BUY/SELL only when daily/4H/1H agree, at least 3 confirmations line up, reward/risk is at least 1.5, no big news
    is within 30 minutes and the spread is normal. Otherwise WAIT, with what would change it.
- **Fundamentals.** Economic calendar with a countdown and what each release means for your pair, central banks, a
  28-pair currency strength meter, news with sentiment and AI one-liners, the fundamental bias, and company numbers
  in plain words.
- **Forecast.** TimesFM-3 for 15M/1H/4H/D with 50%/80% ranges. It is compared with simple guesses ("no change",
  drift, moving average), scored on its own past forecasts, and checked for agreement with the trade plan.
- **Performance.** Walk-forward backtests of the trade-plan engine (out-of-sample only, bid/ask fills, costs,
  look-ahead tests), live results vs the backtest's expected range, and setups switched off when they don't work.

Also included:
- **Alerts** on Telegram and as desktop notifications (Get ready, entry, target, stop, cancelled).
- An **Ask AI** chat, Markdown/PDF reports, and the daily WhatsApp watchlist digest.
- The classic Streamlit dashboard (`streamlit run ui/app.py`).

## Quick start
With Docker, one command:
```bash
copy .env.example .env            # optional keys: OANDA token for live forex, Claude key for Ask AI, Telegram ...
docker compose up -d --build      # then open http://localhost:8080
```
Without Docker:
```bash
python -m venv .venv && .venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m server                                          # backend on http://127.0.0.1:8000 (API docs at /docs)
cd web && npm install && npm run dev                      # app on http://localhost:5173
```

**Full step-by-step guide (OANDA demo token, .env, reading a Trade Plan card, alerts, backtests,
troubleshooting): [SETUP.md](SETUP.md).**

## Project layout
```
config/       settings (.env), symbol aliases + Investing.com links, FRED series, event calendar, default watchlist
data/         providers (yfinance, OANDA, Twelve Data, FRED, Finnhub, Marketaux, ForexFactory calendar), cache;
              stream/ (OANDA live stream, polling fallback, candle aggregator, market hours)
analysis/     indicators, levels, patterns, technical (multi-timeframe), fundamental, macro_fx, sentiment, combined;
              structure/ (swings, trendlines, zones, liquidity, chart patterns, AI overlay); fundtab/ (Fundamentals tab)
forecasting/  TimesFM-3 + baselines, input features, backtest, live forecasts + accuracy scoring, service
signals/      daily (swing) BUY/SELL/WAIT engine: levels, decision gates, sizing, events, plain-language templates
intraday/     15-minute trade-plan engine: sessions, multi-timeframe bias, setups, plan state machine, news filter,
              spread check, backtest + walk-forward + statistics, probability files

agent/        LLM providers (Claude, OpenAI-compatible), tools, prompt, agent loop, report export
alerts/       trade-plan alert dispatcher, Telegram, WhatsApp notifiers, watchlist scanner, scheduler
api/          FastAPI backend: REST + WebSocket hub, background jobs, event bus (python -m server)
web/          React + TypeScript frontend (Vite, Lightweight Charts, Tailwind); tests: npm test, npx playwright test
ui/           classic Streamlit dashboard + Plotly charts
scripts/      download_model.py, run_backtest.py, download_history.py, run_intraday_backtest.py
docs/         legacy-streamlit.md (guide to the classic dashboard's Signals tab)
tests/        offline unit tests (pytest)
```

## Tests
```bash
python -m pytest
```
All tests run offline: market APIs, the LLM and the forecaster are replaced with fakes.
Frontend: `cd web && npm test` (unit/component) and `npx playwright test` (browser smoke tests, starts both servers).

## Licences
Code: your own. **TimesFM-3 weights** are under Google's *TimesFM Non-Commercial License v1.0*, for personal,
non-commercial use only. Commercial use would need a forecaster adapter for an Apache-2.0 model such as TimesFM 2.5
or Chronos-2. Add a class with the same `forecast()` method in `forecasting/models.py`.
