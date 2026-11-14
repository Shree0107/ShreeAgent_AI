# Legacy Streamlit dashboard: the Signals tab

The original Streamlit dashboard still works (`streamlit run ui/app.py`, or `docker compose --profile legacy up -d`
→ http://localhost:8501). This page is the guide to its **🧭 Signals** tab. The new web app's **Trade Plan** tab
replaces it; see [SETUP.md](../SETUP.md).

The **🧭 Signals** tab now shows one simple card per watchlist symbol. Each card answers: *BUY, SELL or WAIT? Why?
What am I waiting for? Where do I enter? Where's my stop loss? Where do I take profit? What would cancel the trade?*
The technical analysis, fundamentals, news and the TimesFM-3 forecast all still run, but in the background.

### A1. Pull the latest code and install

```powershell
cd C:\path\to\ShreeAgent_AI          # the folder you cloned into
.venv\Scripts\activate
git pull
pip install -r requirements.txt      # no new packages this time, but this is always safe to run
python -m pytest                     # should end with "all tests passed"
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
  `user_data/watchlist.yaml` (see SETUP.md, “Adding symbols”). For EUR/USD only, keep just `- EUR/USD` in that file.
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
python -m pytest                               # everything (offline, no API keys needed): all tests passed
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
