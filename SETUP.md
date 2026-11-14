# ShreeAgent AI: Setup Guide

ShreeAgent AI is a trading-analysis platform that runs in your browser. It has a live chart, beginner trade plans,
fundamentals, forecasts and backtests. Commands are for **Windows (PowerShell)**. Linux/macOS commands are shown
where they differ.

> ShreeAgent AI only analyses. It never places trades. Nothing it shows is financial advice. Always use a stop loss.

| # | Section |
|---|---|
| 1 | [Install](#1-install) |
| 2 | [OANDA demo account (live forex prices)](#2-oanda-demo-account-live-forex-prices) |
| 3 | [Fill in `.env`](#3-fill-in-env) |
| 4 | [Run it (Docker or without Docker)](#4-run-it) |
| 5 | [Tour of the five tabs](#5-tour-of-the-five-tabs) |
| 6 | [Reading a Trade Plan card (EUR/USD example)](#6-reading-a-trade-plan-card-eurusd-example) |
| 7 | [Drawing tools and the AI analysis overlay](#7-drawing-tools-and-the-ai-analysis-overlay) |
| 8 | [Alerts: Telegram, desktop, WhatsApp](#8-alerts-telegram-desktop-whatsapp) |
| 9 | [Backtests and tests](#9-backtests-and-tests) |
| 10 | [Troubleshooting](#10-troubleshooting) |

The old Streamlit dashboard still works. Its guide is in [docs/legacy-streamlit.md](docs/legacy-streamlit.md).

---

## 1. Install

### What you need
| Item | Version | Why | Get it |
|---|---|---|---|
| Python | **3.11 or newer** | the backend | https://www.python.org/downloads/ (tick **"Add python.exe to PATH"**) |
| Node.js | **22 LTS or newer** | builds and runs the web app (not needed with Docker) | https://nodejs.org |
| Git | any recent | download and update the code | https://git-scm.com/downloads |
| Docker Desktop | optional | one-command start | https://www.docker.com/products/docker-desktop/ |
| Disk | ~6 GB free | PyTorch (~1 GB), TimesFM-3 (~1.3 GB), FinBERT (~0.45 GB), web packages | |
| RAM | 8 GB minimum, 16 GB recommended | the forecasting model runs in memory | |
| NVIDIA GPU | optional | faster forecasts. A CPU works (about 4 s per forecast once loaded) | |

Check what you have:
```powershell
python --version; node --version; git --version
```

### Download and install
```powershell
git clone https://github.com/Shree0107/ShreeAgent_AI.git
cd ShreeAgent_AI

python -m venv .venv
.venv\Scripts\activate                 # Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu        # CPU (default)
# pip install torch --index-url https://download.pytorch.org/whl/cu128    # NVIDIA GPU instead
pip install -r requirements.txt

cd web
npm install                            # web app packages (~1 min)
cd ..
```

Download the forecasting model once (~1.3 GB; a test forecast at the end prints `TimesFM-3 is ready.`):
```powershell
python scripts/download_model.py
```
- No Hugging Face account is needed. If the download fails with `401` or `gated repo`, create a free **Read**
  token at https://huggingface.co/settings/tokens and put it in `.env` as `HF_TOKEN=hf_...`.
- **Licence:** the TimesFM-3 weights are under Google's *TimesFM Non-Commercial License*. Personal use is fine.
  Don't sell its forecasts as a service.
- The news model (FinBERT, ~440 MB) downloads by itself the first time news is analysed.

> Each time you open a new terminal, run `.venv\Scripts\activate` before the Python commands.

---

## 2. OANDA demo account (live forex prices)

XTB closed its API in 2025, so the app can't read prices from XTB. It uses a free **OANDA demo (practice)
account** instead. That gives real-time forex and gold prices, the live spread, and years of 1-minute history.
You keep trading on XTB as usual. OANDA is only the price feed, and the app never places orders anywhere.

**Without OANDA** everything still works, but forex prices come from Yahoo, are a little delayed, and the top bar
says **Delayed** instead of **Live**.

### Getting the token
1. Go to https://www.oanda.com and open a **demo / practice account** (free, no deposit, no ID check for a demo).
   If OANDA doesn't offer a demo in your country, skip this section.
2. Log in to the demo account on the OANDA website.
3. Open **My Account → Manage API Access** (on some versions: *Tools → API*) and click **Generate**.
4. Copy the token (a long string of letters and numbers with a dash in the middle). Treat it like a password.
5. In `.env`:
   ```
   OANDA_API_TOKEN=paste-your-token-here
   OANDA_ENVIRONMENT=practice
   ```
   `OANDA_ACCOUNT_ID` can stay empty: the app finds it from the token.
6. Restart the backend. The dot in the top bar turns green with **Live**, and the chart footer says *OANDA live*.

### Limits and cost
| | |
|---|---|
| Cost | Free. A demo account has no fees and no expiry while you use it. Inactive demo accounts may be closed after a while; just open a new one and make a new token |
| Price updates | Up to about 4 per second per symbol while the price moves. The app uses **one** price stream for all your symbols |
| History | Candles from 1 minute up, several years back |
| What's covered | Forex pairs, gold and silver, some indices. **Not** single stocks |
| Practice vs XTB prices | Very close but not identical (different liquidity providers). Differences of 0.1–0.3 pips on EUR/USD are normal. **Always place orders with the prices XTB shows** |
| Spread | OANDA's demo spread is shown in the top bar. Your XTB spread may be slightly different; set yours in `SPREAD_PIPS` |
| Token security | The token stays on your computer in `.env`. It is never sent to the browser. If it leaks, revoke it on the same OANDA page and generate a new one |

### Stocks ("all global stocks")
No free source streams every stock exchange in real time. Stocks come from **Yahoo**. The app checks every
15 seconds (`LIVE_POLL_SECONDS`), and the data is delayed up to about 15 minutes on many exchanges. Stock prices
are always labelled **Delayed**. Use exchange suffixes: `SAP.DE` (Xetra), `VOD.L` (London), `MC.PA` (Paris),
`ASML.AS`, `NESN.SW`, `7203.T` (Tokyo), `0700.HK`, `SHOP.TO`, `BHP.AX`, `RELIANCE.NS` (India NSE), and plain
tickers for the US (`AAPL`).

---

## 3. Fill in `.env`

```powershell
copy .env.example .env      # Linux/macOS: cp .env.example .env
notepad .env
```
Paste each value after the `=`, without quotes or spaces. **Every setting is optional.** A missing key turns off
only the feature that needs it, and the app tells you which one.

| Key | What it adds | Free? | Where |
|---|---|---|---|
| `OANDA_API_TOKEN` | live forex/gold prices and spread | free | section 2 |
| `ANTHROPIC_API_KEY` | **Ask AI** chat, AI news summaries, optional AI wording | pay-as-you-go | https://console.anthropic.com → *Settings → API keys* (add a few dollars of credit under *Billing*) |
| `FRED_API_KEY` | interest rates, inflation, the actual numbers of US releases | free | https://fredaccount.stlouisfed.org → *API Keys* |
| `FINNHUB_API_KEY` | company news, peers, earnings dates | free | https://finnhub.io/dashboard |
| `MARKETAUX_API_KEY` | more news with sentiment | free (100/day) | https://www.marketaux.com |
| `TWELVEDATA_API_KEY` | backup price source if Yahoo fails | free (800/day) | https://twelvedata.com/account/api-keys |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | trade alerts on your phone | free | section 8 |

Settings most useful for an XTB EUR/USD trader (defaults in brackets):
- `ACCOUNT_SIZE` (1000), `ACCOUNT_CURRENCY` (EUR), `RISK_PER_TRADE_PCT` (1.0): used for the lot size on every card.
- `SPREAD_PIPS` (1.0): your XTB EUR/USD spread. It's added to the stop so the spread alone can't hit it.
- `LEVERAGE` (30), `FX_LOT_SIZE` (100000), `FX_MIN_LOT` (0.01): XTB / EU retail rules. Leave them unless XTB changes them.
- `SIGNAL_MIN_RR` (1.5): only BUY/SELL when the possible gain is at least 1.5× the possible loss.
- `ALERT_EVENTS`: which trade-plan events alert you (section 8).

Every variable is explained inside `.env.example`. Restart the backend after editing `.env`.

`.env` is git-ignored and must **never** be committed or shared. If a key leaks, delete it on the provider's
site and create a new one.

---

## 4. Run it

### Option A: Docker (one command)
Start Docker Desktop and wait until it says *Running*. Then, in the project folder:
```powershell
docker compose up -d --build           # first build ~10 min, later starts take seconds
```
Open **http://localhost:8080**. That's it.

| Command | What it does |
|---|---|
| `docker compose logs -f backend` | watch the backend log |
| `docker compose down` | stop everything |
| `git pull; docker compose up -d --build` | update to the latest version |
| `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` | use an NVIDIA GPU |
| `docker compose --profile legacy up -d` | also start the old Streamlit dashboard on http://localhost:8501 |
| `docker compose --profile alerts up -d` | also start the daily WhatsApp watchlist scan |

Containers: `backend` (API, live prices, analysis, alerts; port 8000 on your computer only, API docs at
http://localhost:8000/docs) and `web` (the app, port 8080). Models and the data cache live in Docker volumes, so
they download once. Your watchlist, drawings and history are in `./user_data/`.

### Option B: without Docker (two terminals)
**Terminal 1, backend:**
```powershell
.venv\Scripts\activate
python -m server                       # http://localhost:8000 (API docs at /docs)
```
**Terminal 2, web app:**
```powershell
cd web
npm run dev                            # http://localhost:5173
```
Open **http://localhost:5173**. Stop either one with `Ctrl+C`.

- The first start takes 1–2 minutes while models load. After that the chart opens in under 2 seconds.
- The backend runs everything in one process: live prices, analysis at each candle close, forecasts, alerts.
  No Redis or extra services are needed.
- To serve a built version instead of the dev server: `cd web; npm run build`. The files land in `web/dist/`
  (Docker does this for you).

---

## 5. Tour of the five tabs

**Top bar (always visible):** symbol search (type a name, e.g. "Apple", "EUR/USD", "Siemens"), your watchlist,
live price and today's % change, the current spread, the trading session (Asia / London / New York / overlap), the
connection dot, the 🔔 alerts bell, the light/dark switch, and **Ask AI** (chat about any symbol).

| Dot | Meaning |
|---|---|
| 🟢 **Live** | real-time prices (OANDA) |
| 🟡 **Delayed** | Yahoo prices, up to ~15 min late |
| ⚪ **Market closed** | weekend or outside trading hours. Forex closes Friday 23:00 and reopens Sunday 23:00 (CET) |
| 🔴 **Offline** / **Stale** | no connection, or no new price for over a minute while the market is open. Cards and plans grey out so you never act on old prices. The app reconnects by itself and fills the gap |

1. **Chart.** Live candles from 1 minute to weekly. Candles, line or Heikin Ashi. **ƒx Indicators** adds EMA 21/50/200,
   SMA 20/50, Bollinger Bands, VWAP, volume, RSI, MACD, Stochastic and ATR. Hover for open/high/low/close, scroll to zoom, drag to
   move back in time. **✏ Draw** opens the drawing tools, **✨ AI analysis** shows the app's own lines and zones
   (section 7), and **📷 Screenshot** saves a PNG. The footer counts down to the next candle.
2. **Trade Plan.** One beginner card per watchlist symbol: BUY, SELL or WAIT, with the entry, stop loss, targets,
   lot size and what would cancel it. The card's status updates live. See section 6.
3. **Fundamentals.**
   - Economic calendar (today / this week) with a countdown to the next big event, and a plain line per event
     on what it usually means for your pair.
   - Central-bank rates and next meetings.
   - A currency strength meter (28 pairs).
   - News with sentiment and one-line AI summaries, and the overall fundamental bias.
   - For stocks: key company numbers in plain words, earnings date and analyst views.
4. **Forecast.**
   - The TimesFM-3 forecast for 15M / 1H / 4H / Daily, with 50% and 80% ranges.
   - A sentence like *"The model expects EUR/USD between 1.0990 and 1.1046 in the next 24 hours"*.
   - How the model scores against simple guesses ("price stays the same", "trend continues"), and its live
     accuracy on past forecasts.
   - Whether it agrees with the trade plan. **For major forex pairs the model is often no better than "price stays
     the same". The tab tells you when that's the case: then don't give the forecast much weight.**
5. **Performance.** How each setup did in backtests (out-of-sample) and live, in plain words and as tables. See
   section 9.

---

## 6. Reading a Trade Plan card (EUR/USD example)

At the top of the tab:
- **Intraday (15 min) / Swing (daily).** Intraday plans are same-day trades on the 15-minute chart. Swing shows
  the daily cards (several days per trade).
- **Filter:** All / Buy / Sell / Get ready / Wait. Cards are sorted strongest first.
- **Account size, Risk per trade %, Currency → Update sizes:** the lot size and euro amounts on every card use
  these. Defaults come from `.env` (`ACCOUNT_SIZE`, `RISK_PER_TRADE_PCT`, `ACCOUNT_CURRENCY`).

### A BUY card
```
EUR/USD  1.09440  Trending up · London session          Last updated 12:00:03 · next candle 04:12
██ BUY ██  Confidence MEDIUM – 4 checks agree · No backtest yet – treat as unproven
Waiting → Ready → Entry triggered → In trade → Result

Buy only if the price breaks above 1.0950.
WHY?
 • The bigger charts and today's 1-hour chart point up.
 • The 15-minute chart is making higher lows.
 • Buying pressure is building.

Entry       Buy only if the price breaks above 1.0950 (Buy Stop order) · 6 pips away
Stop loss   1.0931 (19 pips) · −€8.70
            Beyond the other side of the sideways range: then the breakout has failed.
Target 1    1.0981 (+31 pips) · +€14.20
Target 2    1.1002 (+52 pips) · +€23.80
Reward      You risk €8.70 to make €14.20 at target 1 (€23.80 at target 2)
Size        Buy 0.05 lots   If the stop loss is hit you lose about €8.70 (1% of €1,000).
Break-even  When the price reaches 1.0969 (+1 × your risk), move the stop loss to your entry 1.0950.
Close by    21:30 (Berlin time) at the latest. This is a same-day trade.
Cancel if   • a 15-minute candle closes below 1.0931 before you are in
            • the order hasn't filled by 15:00
When        likely within the next 1–3 hours (rough estimate)
⚠ CPI m/m (USD) at 14:30 – no new trades 14:00–15:00.
[mini 15-minute chart with the entry, stop and targets drawn in]          ▸ Show details
Analysis only, not financial advice. Always use a stop loss.
```
*(Illustrative numbers for a €1,000 account risking 1%. Your cards show live prices.)*

How to read it, top to bottom:
1. **The label.** **BUY** (green) / **SELL** (red): a trade idea with exact prices. **GET READY** (yellow): the
   price is close to the entry, so open XTB and prepare the order. **WAIT** (amber): no trade now (see below).
2. **Confidence** counts how many independent checks agree. The percentage next to it is **how often this kind of
   setup reached target 1 before the stop in past tests** (Performance tab). *"No backtest yet – treat as unproven"*
   means there's no test data yet.
3. **The status line** moves by itself as the price moves: *Waiting* (price not there yet) → *Ready* (close to the
   entry) → *Entry triggered* (the entry price traded) → *In trade* → the result (*Target 1 / Target 2 / Stop loss /
   Break-even / Time stop / Cancelled / Expired*). Each step can send an alert (section 8).
4. **Entry** and the order type:
   - **Buy Stop / Sell Stop** = buy only once the price rises *to* the level (a breakout). In xStation: *New
     order → Pending → Buy Stop*, price 1.0950.
   - **Buy Limit / Sell Limit** = buy when the price dips back *to* the level (a pullback).
   - *"6 pips away"* updates live.
5. **Stop loss:** type this exact price in the *Stop loss* field of the XTB order **before** you place it. The
   euro amount is what you lose if it's hit. The spread (`SPREAD_PIPS`) is already included.
6. **Targets:** put **Target 1** in the *Take profit* field. A common beginner approach: close half at target 1
   and let the rest run to target 2 with the stop moved to the entry.
7. **Size:** type the lots (e.g. `0.05`) in the *Volume* field. 0.01 lots = 1,000 EUR, the smallest trade. Sizes
   are always **rounded down**, so you never risk more than you chose. If even 0.01 lots is too much risk, the
   card says so: skip the trade rather than moving the stop.
8. **Break-even:** once the trade is up by as much as you risked, move the stop to your entry. From then on the
   trade can't lose money (apart from the spread).
9. **Close by:** intraday trades are closed by 21:30 Berlin time (`FLAT_BY`), so nothing stays open overnight.
   No new entries after 18:00 (`NO_NEW_ENTRIES_AFTER`).
10. **Cancel if:** if any of these happens before you're in, delete the pending order in XTB.
11. **⚠ News:** no new trades from 30 minutes before to 30 minutes after a big release (`NEWS_BLACKOUT_MINUTES`).
- **Grey card:** the prices are old (connection lost, or the market is closed). Don't act on a grey card.
- **Words with a dotted underline** (Sideways, Stop order, Lot, …): hover or tap for a one-line explanation.
- **▸ Show details:** the analysis behind the card: each timeframe's direction (daily, 4H, 1H, 15M, 5M), every
  confirmation, the checks that passed or failed, the spread, and the score.

### A WAIT card
WAIT is the normal state, and it's on purpose. A BUY/SELL needs **all** of these:
- the daily and 4-hour charts aren't against the trade, and the 1-hour chart agrees;
- a 15-minute setup and a 5-minute trigger;
- at least 3 independent confirmations;
- a possible gain of at least 1.5× the risk (`INTRADAY_MIN_RR`);
- no big news within 30 minutes, an allowed time of day, and a spread under the limit (`MAX_SPREAD_PIPS`, 2.0
  pips for EUR/USD);
- fewer than 2 stop losses today (`DAILY_LOSS_LIMIT`).

A WAIT card tells you what's missing and what would change it:
```
EUR/USD  1.09300  Sideways
██ WAIT ██
WAIT – stuck between 1.0912 and 1.0948.
WHAT I'M WAITING FOR
 • The 1-hour chart has no clear direction today.
 ┌ Buy if it breaks above 1.0950 ┐  ┌ Sell if it breaks below 1.0910 ┐
 │ 60% likely – the bigger charts │  │ 40% likely                     │
 │ are rising                     │  │                                │
 └────────────────────────────────┘  └────────────────────────────────┘
```
The two boxes are the two ways out of the range and which one is more likely. When one breaks, the card turns
into a GET READY / BUY / SELL plan by itself at the next 15-minute close.

**Swing (daily)** cards work the same way on the daily chart (entries valid for a few days, no close-by time).
They're explained in detail in [docs/legacy-streamlit.md](docs/legacy-streamlit.md).

---

## 7. Drawing tools and the AI analysis overlay

### Drawing tools
Click **✏ Draw** and pick a tool. A hint at the top of the chart says how many clicks are left. Press **Esc** to
cancel.

| Tool | Clicks |
|---|---|
| Trendline | start, then end |
| Horizontal line | the price level |
| Zone (rectangle) | one corner, then the opposite corner |
| Fibonacci | swing start, then swing end (shows 23.6 / 38.2 / 50 / 61.8 / 78.6 %) |
| Parallel channel | line start and end, then a point for the parallel line |
| Text note | where the note goes |

- **Select** a drawing by clicking it. Press **Delete** (or Backspace) to remove it.
- Drawings are **saved per symbol** on the backend (`user_data/`). They're still there after a restart, on
  every timeframe and on other devices that open the same app.

### AI analysis overlay
Click **✨ AI analysis** to let the app draw what its analysis engine sees. The **▾** next to it chooses the layers:

| Layer | What it shows |
|---|---|
| Trade plan | entry zone, stop loss and targets of the current plan |
| Trendlines & channels | lines through swing highs/lows that the price respected (with the number of touches) |
| Support & resistance | price areas touched several times. Darker = stronger |
| Market structure | higher highs / lower lows, **BOS** (break of structure: the trend continues) and **CHoCH** (change of character: the trend may be turning) |
| Fibonacci | retracement levels of the last big swing |
| Liquidity | previous day/week high and low, the Asian session range, equal highs/lows, round numbers, and stop hunts (a wick through a level that closes back inside) |
| Order blocks, gaps, supply/demand | where big orders probably sit |

The overlay is calculated from **completed candles only**, so it never uses future data. It refreshes at each
candle close. It's not "AI" in the chat sense: the same rules always give the same lines, which makes them easy to
check by eye.

---

## 8. Alerts: Telegram, desktop, WhatsApp

Alerts fire when a trade plan changes state:

| Event (`ALERT_EVENTS` name) | Example |
|---|---|
| `get_ready` | 🔔 Get ready: EUR/USD is 5 pips from the entry |
| `entry_triggered` | 🚀 Entry triggered: price broke above 1.0952, the BUY plan is active |
| `tp_hit` | ✅ Target 1 / Target 2 hit |
| `sl_hit` | ❌ Stop loss hit |
| `cancelled` | 🚫 Setup cancelled (and why) |
| `breakeven`, `time_stop`, `expired` | off by default. Add them, or use `all` |

The same alert isn't repeated for the same plan within `ALERT_DEDUPE_MINUTES` (30). Alerts are sent by the
backend, so they work while the app is closed, **as long as the backend is running**.

### Desktop notifications (no setup)
Click the 🔔 bell in the top bar → **Enable desktop alerts** → allow. The bell also keeps a list of recent alerts.
Desktop pop-ups need the app open in a browser tab, which can be in the background.

### Telegram (recommended for your phone, free)
1. In Telegram, open **@BotFather**, send `/newbot`, and pick a name and a username ending in `bot`.
2. BotFather replies with a token like `1234567890:AAH...`. Put it in `.env` as `TELEGRAM_BOT_TOKEN=...`.
3. Open your new bot in Telegram and send it any message (e.g. "hi"). A bot can only message you after you've
   written to it.
4. Get your chat id and test it:
   ```powershell
   python -m alerts.telegram --chat-id     # prints your chat id
   ```
   Put it in `.env` as `TELEGRAM_CHAT_ID=...`, then:
   ```powershell
   python -m alerts.telegram --test        # you should get a test message
   ```
5. Restart the backend.

### WhatsApp (optional)
Set up CallMeBot or Twilio as described in [docs/legacy-streamlit.md](docs/legacy-streamlit.md) and the WhatsApp
part of `.env.example`. Then set `ALERTS_WHATSAPP=true` to also send trade-plan alerts there. The daily watchlist
scan (`python -m alerts.scheduler`, or the Docker `alerts` profile) still sends its morning summary.

---

## 9. Backtests and tests

### What a backtest does
A backtest replays past prices candle by candle and runs **the same engine as the Trade Plan tab** on them. At each
15-minute close it only sees candles that had finished by then, then checks every 5-minute candle afterwards to see
whether the entry filled and whether the stop or a target was hit first. It's built to be cautious:
- Buys fill at the ask and sells at the bid. Without real bid/ask data, half the typical spread is added.
- Slippage (`BACKTEST_SLIPPAGE_PIPS`, 0.2) and commission (`BACKTEST_COMMISSION_PIPS`, 0) are charged.
- If the stop and a target are both touched in the same candle, it counts as the stop.
- The close-by time, the daily loss limit and the news blackout apply as in live trading.
- **Walk-forward:** settings are chosen on 12 months, then tested on the *next* 3 months the engine has never
  seen, then the window moves on. **Only those unseen test months are reported** (*out-of-sample*).

### Running one
**In the app:** Performance tab → **Run backtest**. A progress bar shows while it runs in the background (minutes
with Yahoo data, about an hour for 2 years of OANDA data).

**From the command line:**
```powershell
python scripts/download_history.py EUR/USD --years 2          # stores 5-minute to daily bars locally
python scripts/run_intraday_backtest.py EUR/USD                # prints the report, updates the cards
python scripts/run_intraday_backtest.py EUR/USD --setups trend_pullback squeeze_breakout --months 12
python scripts/run_intraday_backtest.py EUR/USD --no-write     # report only, don't change the cards
```

> **You need the OANDA token for a real backtest.** Yahoo only keeps about **60 days of 5-minute candles** and has
> no bid/ask prices. With Yahoo data the backtest can't do the 12 + 3 month walk-forward. It uses one split
> instead (settings chosen on the first 60%, tested on the last 40%) and labels the result
> **"a rough guide, not proof"**.

### Reading the Performance tab
- **The lines at the top** sum up each setup in plain words, e.g. *"Pullback in the trend reached target 1 in 58 of
  100 trades on EUR/USD (last 2 years, out-of-sample); on average +2.1 pips per trade after costs."*
- **The table** (click a column header to sort; it can be split by session). Hover a header for its meaning.

  | Column | Meaning | Good sign |
  |---|---|---|
  | Trades | number of test trades | 50+ before you trust the rest |
  | Target 1 first | % of trades that reached target 1 before the stop | well above 50% isn't needed: with targets further away than the stop, ~40% can be enough |
  | Profit factor | pips won ÷ pips lost | **at least 1.15**. Below 1 loses money |
  | Avg per trade | average pips per trade after spread and costs (*expectancy*) | above 0 |
  | Worst dip | the biggest drop of the running total from a high point (*max drawdown*), in pips | small compared with the total |
  | Time to target 1 | typical time from entry to target 1 | fits inside the trading day |
- **Live vs backtest:** your real plan results next to the range the backtest expected. *"Live results are inside
  the range the backtest expected"* is what you want. *"Below"* after 20+ trades means the market has changed:
  trade smaller or pause that setup.
- **Equity curve:** the running total in pips, for the backtest and for live plans.

### How results change the Trade Plan cards
- The card's percentage (*"~58% reached target 1 first (212 similar past setups)"*) comes from these results,
  for the same setup in similar conditions (session, trend, direction). Small groups are pulled toward the
  setup's average so a lucky streak doesn't look better than it is.
- **Switched off:** with at least 50 test trades (`BACKTEST_MIN_TRADES`), a setup whose profit factor is below
  1.15 or whose win rate could just be luck stops giving BUY/SELL plans. The tab lists it with the reason.
- **Unproven:** with fewer than 50 test trades (always the case with Yahoo data), the setup stays on. The card
  then says *"– too few tests to trust yet"*, and that number doesn't change the confidence.

### Running the tests
Everything runs offline with made-up data, no API keys needed.
```powershell
.venv\Scripts\activate
python -m pytest                          # all backend tests (~270)
python -m pytest -k intraday -v           # the Trade Plan engine and backtests, one line each
cd web
npm test                                  # web app tests (~65)
npx tsc -b                                # type check
npx playwright install chromium           # once
npx playwright test                       # opens the real app in a browser: chart loads in < 2 s, tabs, drawings, overlay
```
The backtest has three special tests against *look-ahead* (accidentally using the future):
- **Truncation:** cutting off the data after a point doesn't change any trade that closed before it.
- **Tampering:** changing future candles doesn't change earlier decisions.
- **Completed candles:** no card ever uses a candle that hadn't closed yet.

The daily TimesFM forecast backtests (the Forecast tab's "model vs simple guesses") also run from the command
line: `python scripts/run_backtest.py EUR/USD --timeframe 1d --horizons 5 10 30`.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| Page at localhost:8080 / 5173 doesn't load | Docker: `docker compose ps` must show both containers *running (healthy)*. Look at `docker compose logs backend`. Without Docker: both terminals (backend **and** `npm run dev`) must be running |
| Top bar says **Offline** | The backend isn't running or crashed. Check its terminal or `docker compose logs backend`. The app reconnects by itself once it's back |
| Says **Delayed** although I set OANDA | The token wasn't picked up: check `OANDA_API_TOKEN` (no quotes/spaces), `OANDA_ENVIRONMENT=practice` for a demo token, and restart the backend. The backend log says why OANDA was refused (`401` = wrong or revoked token) |
| **Market closed** at the weekend | Correct. Forex is closed from Friday 23:00 to Sunday 23:00 CET. Plans and forecasts use the last completed candle and are marked as such |
| Chart is empty for a stock | Check the ticker and suffix (`SAP.DE`, not `SAP`). Yahoo may be throttling: wait a few minutes or add `TWELVEDATA_API_KEY` |
| Everything says WAIT | Usually correct: the rules only allow a trade when several things agree. Read *What am I waiting for?* on the card |
| Alerts don't arrive on Telegram | Run `python -m alerts.telegram --test`. You must have sent your bot a message first. Check `ALERT_EVENTS` |
| Desktop alerts don't show | The bell says *Blocked in browser*: allow notifications for the site (lock icon in the address bar). Windows *Focus / Do not disturb* also hides them |
| Fundamentals strength meter slow the first time | It downloads 28 pairs (~30 s), then caches them for 5 minutes |
| "AI summaries unavailable (no credit)" | Add credit to your Anthropic account. Everything else works without it |
| Forecast says "Updating now…" for a minute | The first forecast per symbol and timeframe also checks the model against simple guesses: ~1 min on CPU. Later ones take seconds |
| Central-bank rate shows *old data* | That FRED series is stale. Update the series ID in `config/macro_series.yaml` |
| `npm` / `node` not found | Install Node.js 22 LTS (section 1) and open a new terminal |
| `ModuleNotFoundError` | `.venv\Scripts\activate`, then `pip install -r requirements.txt` |
| Port already in use | Backend: `python -m server --port 8001` (and change the port in `web/vite.config.ts`). Docker: change `"8080:80"` in `docker-compose.yml` |
| Docker: `failed to connect to the docker API` | Start Docker Desktop and wait for *Running* |
| Docker: `env file .env not found` | Create `.env` first (section 3) |
| `UnicodeEncodeError` in the terminal | Run `chcp 65001` first |
| Odd or old data | Delete `.cache/cache.sqlite` (it rebuilds itself). Logs: `.cache/logs/shreeagent.log` |

Updating later:
```powershell
git pull
.venv\Scripts\activate; pip install -r requirements.txt
cd web; npm install; cd ..
python -m pytest
```
