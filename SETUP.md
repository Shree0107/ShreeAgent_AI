# ShreeAgent AI: Setup Guide

These are the steps you do yourself. Follow them in order. Commands are for **Windows (PowerShell)**. Linux/macOS
equivalents are shown where they differ.

> ShreeAgent AI only analyses. It never places trades. Nothing it shows is financial advice.

**Already installed ShreeAgent AI before?** Go straight to
[Part A: the new Signals section](#part-a-the-new-signals-section-upgrade-guide). **New install?** Do steps 1–10
first, then read Part A from step A3 on.

---

## Part A: the new Signals section (upgrade guide)

The **🧭 Signals** tab now shows one simple card per watchlist symbol. Each card answers: *BUY, SELL or WAIT? Why?
What am I waiting for? Where do I enter? Where's my stop loss? Where do I take profit? What would cancel the trade?*
The technical analysis, fundamentals, news and the TimesFM-3 forecast all still run, but in the background.

### A1. Pull the latest code and install

```powershell
cd C:\path\to\ShreeAgent_AI          # the folder you cloned into
.venv\Scripts\activate
git pull
pip install -r requirements.txt      # no new packages this time, but this is always safe to run
python -m pytest                     # should end with "109 passed"
```
With Docker: `git pull` then `docker compose up -d --build`.

### A2. New settings for `.env` (all optional)

**No new API keys are needed.** The new settings all have sensible defaults. Add only the ones you want to change.
The easiest way is to copy the whole `# ---- Signals tab ----` and `# ---- Position size helper ----` blocks from
`.env.example` to the end of your `.env`, then edit them. Most useful for an XTB EUR/USD trader:

| Setting | Default | What it does |
|---|---|---|
| `ACCOUNT_SIZE` | `1000` | Your account size (the starting value of the position size helper) |
| `ACCOUNT_CURRENCY` | `EUR` | Your XTB account currency |
| `RISK_PER_TRADE_PCT` | `1.0` | % of the account you're willing to lose on one trade |
| `SPREAD_PIPS` | `1.0` | Typical EUR/USD spread on your XTB account. It's added to the stop so the spread alone can't trigger it. Check it in xStation (the gap between the BUY and SELL price) |
| `LEVERAGE` | `30` | Used only to show the margin needed. 1:30 is the EU retail maximum for major pairs |
| `SIGNAL_MIN_RR` | `1.5` | BUY/SELL only when the possible gain is at least 1.5× the possible loss |
| `SIGNAL_MIN_CONFIDENCE` | `Medium` | `High` = fewer but stronger signals, `Low` = more signals |

`SIGNAL_LLM_POLISH=true` lets Claude reword the explanations (it uses your `ANTHROPIC_API_KEY`, a fraction of a cent
per card). The numbers can't change: any rewrite that alters a number is thrown away automatically.

Restart the app after editing `.env`.

### A3. Run the app and open the Signals section

```powershell
.venv\Scripts\activate
streamlit run ui/app.py
```
Open http://localhost:8501 and click the **🧭 Signals** tab.

- **The very first start takes 1–3 minutes.** The app loads the news model (FinBERT, ~50 s) and the forecasting
  model (TimesFM-3), then analyses each symbol. A spinner shows while it works.
- After that, cards are stored in `user_data/signals.sqlite` and reused for 60 minutes
  (`SIGNAL_REFRESH_MINUTES`), so the tab opens instantly. Click **🔄 Refresh signals** for a fresh analysis.
- Your watchlist symbols get a card. So does the symbol currently open in the sidebar, marked *"Not in your
  watchlist"* if it isn't in the list.
- Use the **Show: All / Buy / Sell / Wait** filter at the top. Cards are sorted strongest first.

### A4. How to read a signal card (example)

```
EUR/USD                                                1.1012
                                                (+0.15% today)
 ███ BUY ███   Confidence: MEDIUM
               the price trend and the forecast agree, but the news is mixed

WHY?
 • The price has been rising steadily for about 3 weeks
 • The price bounced off 1.0970, a level where buyers have stepped in before
 • Our forecasting model expects the price to rise a little over the next 10 trading days

WHEN SHOULD I ENTER?
 Buy between 1.0985 and 1.1012
 Only enter if a daily candle closes above 1.0985 – that shows buyers are defending the level at 1.0985

STOP LOSS   1.09308 (68 pips below your entry)
 Below the recent low of 1.0948 (Tue 10 Nov) plus a small safety margin, so a normal dip won't knock you out

TAKE PROFIT
 Target 1  1.11035  +0.95%  +€9.55     105 pips · just before 1.1110, where the price turned back before
 Target 2  1.11935  +1.77%  +€17.73    195 pips · just before 1.1200, where the price turned back before

RISK vs REWARD  You risk €1 to potentially make €1.55 at target 1 (or €2.88 at target 2)
POSITION SIZE   Buy 0.01 lots (1,000 units) – risk €6.16
                Margin needed ≈ €33 · 1 pip ≈ €0.09 at this size

WHAT WOULD CANCEL THIS TRADE?
 • If the price closes below 1.09308 before you enter, this idea is no longer valid – don't enter
 • If the price reaches 1.11035 before you enter, you've missed it – don't chase it
 • If you haven't entered by Wed 18 Nov 21:00 UTC, the signal has expired

⚠️ Upcoming: The US inflation report is Thu 19 Nov – expect big price moves
🕒 Generated Fri 13 Nov 09:12 UTC (5 min ago) · Expires Wed 18 Nov 21:00 UTC
📊 Past signals for EUR/USD: 3 wins / 2 losses (60% win rate)
This is analysis, not financial advice. Always use a stop loss.
```
*(Illustrative numbers for a €1,000 account risking 1%. Your card shows live prices. XTB shows EUR/USD with 5
decimals, so the app does too when the 5th digit matters.)*

How to use it on XTB (xStation):
1. **BUY / SELL / WAIT.** Green BUY = consider buying, red SELL = consider selling, amber WAIT = do nothing yet.
2. **Why?** The main facts behind the decision, in everyday words.
3. **What am I waiting for?** (WAIT cards only.) The exact conditions to watch. Example: *"Wait for a daily close
   above 1.1060"* means: wait until a daily candle *ends* above 1.1060 (the daily candle closes around 23:00 CET on
   XTB), not just touches it. When the condition is met, click **Refresh signals** to see whether it has turned into
   a BUY/SELL.
4. **When should I enter?** Only open the trade while the price is inside the entry zone, and only after the
   confirmation condition.
5. **Stop loss.** Type this exact price into the *Stop loss* field of the XTB order ticket **before** you open the
   trade.
6. **Take profit.** Put target 1 in the *Take profit* field. A common beginner approach: close half at target 1 and
   the rest at target 2, or simply use target 1.
7. **What would cancel this trade?** If any of these happens before you enter, skip the trade.
- **Confidence** shows how strongly the price trend, the economic background, the news and the forecast agree.
- **Risk vs reward:** *"You risk €1 to potentially make €1.55"* means the possible gain is 1.55× the possible loss.
- **Expires:** if you haven't entered by then, ignore the card and wait for a new one.
- **Words with ⓘ:** hover with the mouse to see a one-line explanation. On a phone, tap
  **📖 What do these words mean?** under the card.
- **Show details:** opens the technical data behind the signal: score per component, the exact levels, indicators
  per timeframe, support/resistance, the forecast, and (tick *Show charts*) a price chart with the entry zone, stop
  and targets drawn on, plus the TimesFM forecast chart.

**Why so many WAITs?** That's by design. The app says WAIT when the checks disagree, confidence is low, the possible
gain is less than 1.5× the risk, a level sits right in front of the price, the stop would have to be very far away,
or a major event (US inflation report, US jobs report, ECB / Fed decision) is today or tomorrow. Smaller releases
(producer prices, retail sales, GDP, PCE) only show a warning.

### A5. Position size helper

At the top of the Signals tab:
1. **Account size:** your XTB balance, e.g. `1000`.
2. **Risk per trade (%):** how much of the account you accept losing if the stop is hit. 0.5–2% is typical for
   beginners. 1% of €1,000 = €10.
3. **Account currency:** `EUR` for a euro XTB account.

Each BUY/SELL card then shows, for example (€1,000 at 1%, a 45-pip stop at 1.10),
**"Buy 0.02 lots (2,000 units) – risk €8.18"**:
- **Lots** is what you type into the *Volume* field in xStation. 1 lot = 100,000 EUR, 0.01 lots = 1,000 EUR,
  which is the smallest trade.
- The size is always **rounded down**, so the real risk is never more than you chose.
- **Margin needed** is the money XTB sets aside while the trade is open (at 1:30). **1 pip ≈ …** shows what each
  0.0001 move is worth at this size.
- If your risk amount is too small even for 0.01 lots, the card says so and shows what 0.01 lots would risk. Then
  either raise the risk %, or skip the trade.
- The money figures on targets 1 and 2 use this size.

The values reset when you restart the app. Set your usual values in `.env` (`ACCOUNT_SIZE`, `RISK_PER_TRADE_PCT`,
`ACCOUNT_CURRENCY`) so they're filled in automatically.

### A6. Changing settings (risk/reward, confidence, watchlist)

Edit `.env`, save, and restart the app (`Ctrl+C`, then `streamlit run ui/app.py`). Then click **🔄 Refresh signals**,
because stored cards keep their old settings until they're rebuilt.
- **Minimum risk/reward:** `SIGNAL_MIN_RR=2.0` gives fewer but better-paying trades. `1.5` is the default.
- **Confidence:** `SIGNAL_MIN_CONFIDENCE=High` gives only the strongest signals. `SIGNAL_MIN_SCORE` (default 25) is
  how strong the combined score must be to suggest any direction. `SIGNAL_HIGH_SCORE` (default 50) is the score
  needed for High confidence.
- **Events:** `SIGNAL_EVENT_BLACKOUT_DAYS=1` = WAIT if a major event is today or tomorrow. `0` = only on the day
  itself. `SIGNAL_EVENT_WARNING_DAYS=7` sets how far ahead warnings appear.
- **Expiry:** `SIGNAL_EXPIRY_BARS=3` trading days.
- **Watchlist:** add symbols with the sidebar search and **➕ Watchlist**, remove them with **✕**, or edit
  `user_data/watchlist.yaml` (see step 7). For EUR/USD only, keep just `- EUR/USD` in that file.
- Central-bank meeting dates come from `config/events.yaml`. Check them against the official calendars linked in
  that file every few months.

### A7. Signal history and win rate

- Every **BUY/SELL** card is saved automatically (WAIT cards aren't trades, so they aren't counted). The same idea is
  saved only once, even if you refresh many times.
- Each time signals refresh (and on the daily WhatsApp scan), saved signals are checked against the hourly prices
  that followed:
  - **Hit target 1 / Hit target 2:** a win
  - **Hit stop loss:** a loss. If the stop and the target were touched in the same hour, it counts as a loss (the
    cautious choice).
  - **Expired:** the price never came into the entry zone before the expiry
  - **Missed:** it reached target 1 without entering first
  - **Cancelled:** it closed beyond the stop before entering
  - **Replaced:** a newer signal with different levels replaced it before entry
- **Win rate = wins ÷ (wins + losses).** Expired, missed, cancelled and replaced signals aren't counted.
- To see it: Signals tab → **📊 Signal history & win rate** (bottom of the page). It shows a table per symbol and
  the full list, downloadable as CSV. Each card also shows its symbol's record (e.g. *"3 wins / 2 losses (60%)"*).
- The results assume you entered inside the zone and used the exact stop and target. Your real XTB results differ
  slightly because of spread and timing. A win rate means little until there are at least 20–30 results.
- The data lives in `user_data/signals.sqlite`. Delete that file to start the history from scratch.

### A8. Running the tests

```powershell
.venv\Scripts\activate
python -m pytest                               # everything (offline, no API keys needed): 109 passed
python -m pytest tests/test_signal_levels.py   # just the entry / stop / target maths
python -m pytest -k signal -v                  # all signal tests, one line each
```
The signal tests cover the entry/stop/target calculation, every WAIT condition, the risk/reward threshold,
position sizing (XTB lots, rounding down, accounts too small for 0.01 lots), events, the plain-language texts
(no jargon), the AI-wording number lock, and the history/win-rate tracking.

### A9. Troubleshooting the Signals tab

| Problem | Fix |
|---|---|
| Signals tab spins for a long time | Normal on the very first start (1–3 min: models loading). If it's always slow, set `SIGNAL_INCLUDE_FORECAST=false` (no TimesFM) or `SENTIMENT_MODEL=lexicon` (no FinBERT). |
| Every card says WAIT | Usually correct. Read *What am I waiting for?*. If you want more signals, lower `SIGNAL_MIN_CONFIDENCE` to `Low` or `SIGNAL_MIN_RR` to `1.2`, but more signals means weaker ones. |
| "Wait until after the … report" all week | Check `config/events.yaml` dates, or set `SIGNAL_EVENT_BLACKOUT_DAYS=0`. |
| Card shows "NO DATA" | The price download failed for that symbol. See the error text, check the ticker, wait a few minutes (Yahoo throttling), or add `TWELVEDATA_API_KEY`. |
| "Wait for fresh prices – the latest data is from …" | Prices are more than 4 days old: internet or data-provider problem. Delete `.cache/cache.sqlite` and refresh. |
| Settings changed but the cards didn't | Restart the app, then click **🔄 Refresh signals**. |
| Position size says "too small" | Your risk amount can't cover 0.01 lots at this stop distance. Raise the risk % or skip the trade. Never move the stop closer just to fit the size. |
| Money shows in USD with "no exchange rate found" | The currency conversion rate couldn't be downloaded. Try again later. Lots and prices are still correct. |
| Prices differ slightly from XTB | Yahoo and XTB quote slightly different prices (different liquidity providers, plus the spread). Differences of 1–3 pips are normal. Always place the order with the prices XTB shows. |
| History is empty | Only BUY/SELL signals are recorded. If you've only had WAITs, the history stays empty. |
| AI wording doesn't change | `SIGNAL_LLM_POLISH=true` needs `ANTHROPIC_API_KEY`. A rewrite that changes any number is rejected and the template wording is kept (that's intended). |

---

## 1. Prerequisites

| Item | Version | Why | Get it |
|---|---|---|---|
| Python | **3.11 or newer** (tested on 3.11.5) | runs the app | https://www.python.org/downloads/ (tick **"Add python.exe to PATH"**) |
| Git | any recent | clone/update the code | https://git-scm.com/downloads |
| Docker Desktop | optional | run everything in containers | https://www.docker.com/products/docker-desktop/ |
| Disk space | ~5 GB free | PyTorch (~1 GB), TimesFM-3 weights (~1.3 GB), FinBERT (~0.45 GB), Docker image | |
| RAM | 8 GB minimum, 16 GB recommended | TimesFM-3 (330M parameters) runs in memory | |
| NVIDIA GPU | optional | faster forecasts. CPU works fine (about 4 s per forecast after the first load) | driver from https://www.nvidia.com/Download/index.aspx |

Check what you have:
```powershell
python --version
git --version
docker --version      # only if you'll use Docker
nvidia-smi            # only if you have an NVIDIA GPU
```

---

## 2. Clone and install

```powershell
git clone https://github.com/Shree0107/ShreeAgent_AI.git
cd ShreeAgent_AI

python -m venv .venv
.venv\Scripts\activate                 # Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip

# Install PyTorch for your hardware FIRST
pip install torch --index-url https://download.pytorch.org/whl/cpu        # CPU (default)
# pip install torch --index-url https://download.pytorch.org/whl/cu128    # NVIDIA GPU instead

pip install -r requirements.txt
```

Check the install with the test suite. It runs offline and needs no API keys:
```powershell
python -m pytest
```
You should see something like `109 passed`.

> Each time you open a new terminal, run `.venv\Scripts\activate` again before using the app.

---

## 3. Download TimesFM-3

The model is **google/timesfm-3.0-pytorch** on Hugging Face: https://huggingface.co/google/timesfm-3.0-pytorch

```powershell
python scripts/download_model.py
```
This downloads ~1.3 GB into your Hugging Face cache (`C:\Users\<you>\.cache\huggingface\hub`) and runs a test forecast.
The first run takes a few minutes. It ends with `TimesFM-3 is ready.` and later loads take ~10 s.

- **Hugging Face account / token:** not needed. The model downloaded without login when this was set up. If the
  download ever fails with `401` or `gated repo`:
  1. Create a free account at https://huggingface.co/join.
  2. Open the model page and accept the licence if asked.
  3. Create a **Read** token at https://huggingface.co/settings/tokens.
  4. Put it in `.env` as `HF_TOKEN=hf_...`.
- **Licence:** the TimesFM *code* is Apache-2.0, but the **TimesFM-3 weights** are under Google's
  **TimesFM Non-Commercial License v1.0**. That allows personal, non-commercial, non-production use, which
  covers this personal assistant. Don't sell or offer forecasts from it as a service.
- **Windows "symlinks" warning:** harmless, it only uses a little more disk space. To silence it, turn on Windows
  *Developer Mode* (Settings → System → For developers) or set `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.
- The news-sentiment model (**FinBERT**, ~440 MB) downloads automatically the first time you open the News tab.

---

## 4. API keys: accounts to create

All of these have free tiers. Only the **Claude** key is needed for the agent chat. Everything else adds
features, and the app still works without them (it says what's missing).

| # | Service | Used for | Free tier | Sign up / get key |
|---|---|---|---|---|
| 1 | **Anthropic (Claude)** | the AI agent chat | pay-as-you-go (add credit) | https://console.anthropic.com → *Settings → API keys* |
| 2 | **FRED** (St. Louis Fed) | interest rates, CPI, GDP, US release calendar | free, 120 req/min | https://fredaccount.stlouisfed.org/login/secure/ → *My Account → API Keys* (info: https://fred.stlouisfed.org/docs/api/api_key.html) |
| 3 | **Finnhub** | company news, peers (sector P/E), earnings calendar | free, 60 req/min | https://finnhub.io/register → key on https://finnhub.io/dashboard |
| 4 | **Marketaux** | news with sentiment (covers Indian stocks) | free, 100 req/day | https://www.marketaux.com/register → key on the dashboard |
| 5 | **Twelve Data** | backup price source if Yahoo fails | free, 800 req/day (NSE/BSE needs a paid plan) | https://twelvedata.com/register → https://twelvedata.com/account/api-keys |
| 6 | Hugging Face | only if the model download asks (see step 3) | free | https://huggingface.co/settings/tokens |
| 7 | CallMeBot or Twilio | WhatsApp alerts (optional) | see step 9 | see step 9 |

**Yahoo Finance** (via `yfinance`) is the main price and fundamentals source. It needs **no account**.

### Getting the Claude API key step by step
1. Go to https://console.anthropic.com and sign up (it may redirect to platform.claude.com).
2. Go to **Billing** and add a small amount of credit (e.g. $5–10). The API is billed separately from a Claude.ai subscription.
3. Go to **Settings → API keys → Create Key**, name it "ShreeAgent", and copy the key (`sk-ant-...`). It's shown only once.
4. Optional: set a monthly spend limit under **Limits**.

Default models: `claude-sonnet-5-5` for chat (fast, cheaper). The **Deep mode** toggle uses `claude-opus-5-5`.
A full analysis is typically a few cents with Sonnet.

---

## 5. Fill in `.env`

```powershell
copy .env.example .env      # Linux/macOS: cp .env.example .env
notepad .env
```
Paste each key after the `=` with no quotes or spaces, e.g.:
```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx
FRED_API_KEY=abcd1234...
FINNHUB_API_KEY=...
MARKETAUX_API_KEY=...
TWELVEDATA_API_KEY=...
```
Every variable is described inside `.env.example`. Useful settings:
- `LLM_EFFORT`: `low` / `medium` (default) / `high`. Higher means more thorough answers and more tokens.
- `TIMESFM_DEVICE`: `auto` (uses the GPU if present), `cpu` or `cuda`.
- `SENTIMENT_MODEL=lexicon` skips the FinBERT download, at lower quality.

`.env` is in `.gitignore` and must **never** be committed or shared. If a key leaks, delete it on the provider's site
and create a new one.

The dashboard sidebar → **Configuration status** shows which keys were picked up. Restart the app after editing `.env`.

---

## 6. Run the app

### Locally
```powershell
.venv\Scripts\activate
streamlit run ui/app.py
```
Your browser opens at http://localhost:8501. Stop it with `Ctrl+C`.

### With Docker
Start Docker Desktop first, then:
```powershell
docker compose up -d --build              # first build takes ~5-10 min
```
Open http://localhost:8501. Other commands:
```powershell
docker compose logs -f app                # view logs
docker compose down                       # stop
docker compose up -d --build              # after pulling new code
# NVIDIA GPU:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```
Model weights and the data cache live in Docker volumes, so they download only once. Your watchlist is in
`./user_data/`.

### Using the dashboard
- **Sidebar:** search a stock or pair by name ("Tata Motors", "Apple", "GBP/USD"), then click **Analyse** or **➕ Watchlist**.
- **Chart:** candlesticks with indicator overlays and panels, plus S/R lines.
- **Signals:** one plain-language BUY / SELL / WAIT card per watchlist symbol, with entry, stop loss, targets,
  position size and history (see [Part A](#part-a-the-new-signals-section-upgrade-guide)). The old
  multi-timeframe table is under **🔬 Technical breakdown** at the bottom of the tab.
- **Forecast:** TimesFM-3 with confidence bands, and a backtest.
- **Fundamentals / News:** financial ratios or the FX macro picture, plus headline sentiment.
- **Agent:** chat in plain language, e.g. *"Analyse EUR/USD for this week"*, *"Is RELIANCE a buy right now?"*,
  *"Compare TCS and INFY fundamentals"*. Download any answer as .md or .pdf.
- **Report:** a rule-based full report with no LLM cost, downloadable as Markdown or PDF.
- **Watchlist scan:** scans every watchlist symbol and can send the result to WhatsApp.

Every report has a **"Cross-check on Investing.com"** link. Use it to compare the price and levels manually.

---

## 7. Adding symbols to the watchlist

**From the dashboard:** type a name in the sidebar search, pick the match, and click **➕ Watchlist**. Remove a symbol with **✕**.

**By editing the file** `user_data/watchlist.yaml` (created on first run):
```yaml
symbols:
  - EUR/USD
  - XAU/USD
  - RELIANCE.NS     # NSE stock: add .NS
  - 500325.BO       # BSE stock: add .BO (BSE code or symbol)
  - AAPL            # US stock: plain ticker
```
Symbol formats:
| Market | Format | Examples |
|---|---|---|
| Forex | `BASE/QUOTE` | `EUR/USD`, `GBP/USD`, `USD/JPY`, `USD/INR` |
| Gold / Silver | `XAU/USD`, `XAG/USD` | prices come from COMEX futures (GC=F / SI=F), which track spot closely |
| US stocks | ticker | `AAPL`, `MSFT`, `NVDA` |
| NSE | ticker + `.NS` | `TCS.NS`, `INFY.NS`, `HDFCBANK.NS` |
| BSE | ticker/code + `.BO` | `RELIANCE.BO`, `500325.BO` |

**Optional:** to get an exact Investing.com link instead of a search link, and short aliases, add the stock to
`config/symbols.yaml`:
```yaml
stocks:
  "ITC.NS": {investing: equities/itc, aliases: [itc]}
```
The `investing` value is the part of the Investing.com URL after `https://www.investing.com/`.

---

## 8. Forecast backtests: running them and reading the results

A backtest replays history. At each of N past dates it gives TimesFM-3 only the data up to that date, asks for the
next *h* candles, and compares the forecast with what really happened. It also scores a **naive baseline**
("price stays where it is"), which is surprisingly hard to beat in liquid markets.

**From the dashboard:** Forecast tab → pick the horizon → **Run backtest**.

**From the command line:**
```powershell
python scripts/run_backtest.py EUR/USD
python scripts/run_backtest.py RELIANCE.NS AAPL --timeframe 1d --horizons 5 10 30 --windows 40
python scripts/run_backtest.py --watchlist
python scripts/run_backtest.py EUR/USD --univariate      # price only, no related assets / volume
```
Each backtest takes ~30-60 s on CPU. Results are saved in `.cache/backtests/`, and the agent and reports use them
automatically to decide how much weight to give the forecast.

Example output:
```
symbol        tf      h  win   MAPE%  naive%   dir%  cov80%   skill  trust
EUR/USD       1d      5   30    0.38    0.38     57      82  -0.003  very low (no better than naive)
```
How to read it:
| Column | Meaning | Good value |
|---|---|---|
| `MAPE%` | average % error of the forecast path | lower than `naive%` |
| `naive%` | the same error for "no change" | the benchmark |
| `dir%` | % of windows where the up/down direction was right | **> 55%**. 50% is a coin flip |
| `cov80%` | % of actual prices inside the 10–90% band | **≈ 80%** (much lower means the bands are too narrow) |
| `skill` | `1 − MAE_model / MAE_naive` | **> 0** beats naive. 0.05+ is meaningful |
| `trust` | summary used by the agent | `moderate` > `low` > `very low` |

Be realistic. For major FX pairs, short-horizon forecasts are often no better than naive, as in the EUR/USD
example above. Treat the forecast as one input among many, and trust it only where its backtest says it has an edge.
Re-run backtests every few weeks, because market behaviour changes.

---

## 9. WhatsApp alerts (optional)

The scanner runs the rule-based analysis on your watchlist (no LLM cost) and sends a digest like:
```
🔴 EUR/USD 1.10534 | bearish -41 (Medium)
   ⚡ strong bearish, new SELL signal
   👉 *SELL* 1.10534-1.10728 · SL 1.11513 · TP1 1.09408 / TP2 1.08950 (risk 1 → make 1.62)
```
A WAIT shows its first condition instead, e.g. `👉 *WAIT*: Wait until after the US inflation report tomorrow (Thu 19 Nov)`.
A symbol is flagged when its combined score passes `ALERT_SCORE_THRESHOLD`, when its bias changed since the last
scan, when daily RSI is at an extreme, or when a new BUY/SELL signal appears. The scan uses the same cards as the
Signals tab and also updates the signal history.

### Option A: CallMeBot (free, easiest, for your own number)
1. Read the current instructions at https://www.callmebot.com/blog/free-api-whatsapp-messages/. It lists the
   CallMeBot phone number to use, which can change.
2. Save that number in your phone contacts.
3. Send it the WhatsApp message: `I allow callmebot to send me messages`
4. You'll receive your **API key** by WhatsApp within a couple of minutes.
5. In `.env`:
   ```
   WHATSAPP_BACKEND=callmebot
   CALLMEBOT_PHONE=+919876543210
   CALLMEBOT_API_KEY=123456
   ```

### Option B: Twilio (official WhatsApp API, paid after the trial credit)
1. Sign up at https://www.twilio.com/try-twilio.
2. In the Console go to **Messaging → Try it out → Send a WhatsApp message** and follow the steps to join the
   **sandbox**: send `join <your-code>` from your phone to the sandbox number.
3. Copy your **Account SID** and **Auth Token** from the Console home page.
4. In `.env`:
   ```
   WHATSAPP_BACKEND=twilio
   TWILIO_ACCOUNT_SID=ACxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxx
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   TWILIO_WHATSAPP_TO=whatsapp:+919876543210
   ```
   The sandbox session expires after 72 h of inactivity. Re-send the `join` message if alerts stop.

### Test and schedule
```powershell
python -m alerts.scheduler --now                 # scan once and send now
python -m alerts.scheduler                       # keep running; scans Mon-Fri at SCAN_TIME
python -m alerts.scheduler --only-flagged        # only send symbols with alerts
```
Set `SCAN_TIME=08:00` and `SCAN_TIMEZONE=Asia/Kolkata` in `.env`. Set `SCAN_INCLUDE_FORECAST=true` to add
TimesFM forecasts (slower).

**Keep it running:**
- **Docker:** `docker compose --profile alerts up -d` starts the scheduler container next to the app.
- **Windows Task Scheduler** (without Docker): create a daily task that runs
  `C:\path\to\ShreeAgent_AI\.venv\Scripts\python.exe -m alerts.scheduler --now` with
  *Start in* = `C:\path\to\ShreeAgent_AI`.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the venv (`.venv\Scripts\activate`) and run `pip install -r requirements.txt` again. |
| `python` not found / opens the Microsoft Store | Reinstall Python with "Add to PATH" ticked, or use `py -3.11` instead of `python`. |
| "Could not load prices … yfinance returned no data" | Check the ticker: NSE needs `.NS`, BSE `.BO`, and delisted or renamed tickers fail (e.g. Tata Motors is now `TMCV.NS` / `TMPV.NS`). Yahoo may also be throttling you, so wait a few minutes or add `TWELVEDATA_API_KEY` as a backup. |
| Yahoo `429 Too Many Requests` | Wait 5–10 minutes. Data is cached (`.cache/cache.sqlite`), so repeated views don't refetch. |
| "Macro data unavailable. Set FRED_API_KEY" | Add the FRED key to `.env` and restart. |
| One macro value shows `n/a` | FRED sometimes discontinues a series. Find a replacement ID on https://fred.stlouisfed.org and update `config/macro_series.yaml`. |
| Agent: "API key is invalid or missing" | Check `ANTHROPIC_API_KEY` in `.env` (no quotes or spaces), make sure you have credit, then restart the app. |
| Agent: "rate limit reached" | Wait a minute. New API accounts have low limits that rise with usage. |
| TimesFM download fails / `401` | See step 3 (HF token). Check your internet connection and that you have ~2 GB free disk. |
| Forecast is very slow | The first call loads the model (~10 s plus download). After that, forecasts take ~4 s on CPU. Set `TIMESFM_CONTEXT_LENGTH=512` for faster forecasts. |
| `CUDA out of memory` | Set `TIMESFM_BATCH_SIZE=2`, or `TIMESFM_DEVICE=cpu`. |
| GPU not used | `python -c "import torch; print(torch.cuda.is_available())"` must print `True`. Otherwise reinstall torch with the `cu128` index URL (step 2). |
| News tab slow the first time | FinBERT is downloading (~440 MB, one time only). Set `SENTIMENT_MODEL=lexicon` to skip it. |
| WhatsApp message not received | Run `python -m alerts.scheduler --now` and read the log. For CallMeBot, check the phone format (`+` and country code) and the API key. For Twilio, re-join the sandbox. |
| `UnicodeEncodeError` in a Windows terminal | Run `chcp 65001` first, or `set PYTHONIOENCODING=utf-8`. |
| Docker: `failed to connect to the docker API` | Start Docker Desktop and wait until it says *Running*. |
| Docker: `env file .env not found` | Create `.env` (step 5) before `docker compose up`. |
| Docker on Linux: permission denied writing `user_data` | `sudo chown -R 1000:1000 user_data` |
| Port 8501 already in use | `streamlit run ui/app.py --server.port 8502`, or change `"8501:8501"` to `"8502:8501"` in `docker-compose.yml`. |
| Stale data or odd results | Delete `.cache/cache.sqlite` (the cache rebuilds itself). Logs are in `.cache/logs/shreeagent.log`. |
| Central-bank dates wrong | Update `config/events.yaml` from the official calendars linked at the top of that file. |

Updating later:
```powershell
git pull
pip install -r requirements.txt
python -m pytest
```
