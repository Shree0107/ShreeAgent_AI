"""ShreeAgent AI: Streamlit dashboard.   Run:  streamlit run ui/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make project packages importable

import pandas as pd
import streamlit as st

from config.logging_setup import setup_logging
from config.settings import get_settings
from data.symbols import resolve, search_symbols
from data.watchlist import Watchlist

setup_logging()
st.set_page_config(page_title="ShreeAgent AI", page_icon="📈", layout="wide")
S = get_settings()
wl = Watchlist()
TFS = ["1h", "4h", "1d", "1wk"]


# ---------------- cached loaders (keyed by ticker strings) ----------------
@st.cache_data(ttl=600, show_spinner=False)
def load_ohlcv(ticker: str, tf: str) -> pd.DataFrame:
    from data.service import get_data_service

    return get_data_service().get_ohlcv(resolve(ticker), tf)


@st.cache_data(ttl=600, show_spinner=False)
def load_quote(ticker: str) -> dict:
    from data.service import get_data_service

    return get_data_service().last_price(resolve(ticker))


@st.cache_data(ttl=600, show_spinner=False)
def load_technical(ticker: str) -> dict:
    from analysis.technical import analyse_symbol

    return analyse_symbol(resolve(ticker)).as_dict()


@st.cache_data(ttl=3600, show_spinner=False)
def load_fundamentals(ticker: str) -> dict:
    sym = resolve(ticker)
    if sym.is_fx:
        from analysis.macro_fx import analyse_fx

        return analyse_fx(sym).as_dict()
    from analysis.fundamental import analyse_stock

    return analyse_stock(sym).as_dict()


@st.cache_data(ttl=1800, show_spinner=False)
def load_news(ticker: str, days: int) -> dict:
    from analysis.sentiment import analyse_news

    return analyse_news(resolve(ticker), days=days).as_dict()


@st.cache_data(ttl=1800, show_spinner=False)
def load_forecast(ticker: str, tf: str, horizon: int, multivariate: bool) -> dict:
    from forecasting.service import forecast_symbol

    return forecast_symbol(resolve(ticker), tf, horizon, multivariate=multivariate).as_dict()


@st.cache_data(ttl=1800, show_spinner=False)
def load_full(ticker: str, tf: str, horizon: int, with_fc: bool) -> dict:
    from analysis.combined import full_analysis
    from signals.service import attach_signal

    sym = resolve(ticker)
    return attach_signal(sym, full_analysis(sym, tf, horizon, include_forecast=with_fc))


def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:,.{nd}f}" if isinstance(x, float) else str(x)


# ---------------- sidebar: search + watchlist ----------------
if "symbol" not in st.session_state:
    st.session_state.symbol = (wl.symbols() or ["EUR/USD"])[0]

with st.sidebar:
    st.title("📈 ShreeAgent AI")
    st.caption("Analysis & signals only. No trades are placed.")

    q = st.text_input("Search a stock or pair", placeholder="e.g. Tata Motors, Apple, GBP/USD")
    if q:
        with st.spinner("Searching…"):
            cands = search_symbols(q)
        if cands:
            labels = [f"{c.symbol.ticker} | {c.symbol.name} ({c.symbol.market})" for c in cands]
            pick = st.selectbox("Matches", range(len(cands)), format_func=lambda i: labels[i])
            c1, c2 = st.columns(2)
            if c1.button("Analyse", width="stretch"):
                st.session_state.symbol = cands[pick].symbol.ticker
                st.rerun()
            if c2.button("➕ Watchlist", width="stretch"):
                wl.add(cands[pick].symbol.ticker)
                st.rerun()
        else:
            st.warning("No matches. Try the exact ticker, e.g. RELIANCE.NS or AAPL.")

    st.subheader("Watchlist")
    for tk in wl.symbols():
        c1, c2 = st.columns([4, 1])
        if c1.button(("▶ " if tk == st.session_state.symbol else "") + tk, key=f"wl_{tk}", width="stretch"):
            st.session_state.symbol = tk
            st.rerun()
        if c2.button("✕", key=f"rm_{tk}", help=f"Remove {tk}"):
            wl.remove(tk)
            st.rerun()

    st.divider()
    tf = st.selectbox("Timeframe", TFS, index=2)
    with st.expander("Configuration status"):
        for label, ok in [("Claude API", bool(S.anthropic_api_key)), ("FRED (macro)", bool(S.fred_api_key)),
                          ("Finnhub (news/peers)", bool(S.finnhub_api_key)), ("Marketaux (news)", bool(S.marketaux_api_key)),
                          ("Twelve Data (fallback)", bool(S.twelvedata_api_key)),
                          ("WhatsApp alerts", S.whatsapp_backend != "none")]:
            st.write(("✅ " if ok else "⚪ ") + label)

ticker = st.session_state.symbol
try:
    sym = resolve(ticker)
except ValueError as e:
    st.error(str(e))
    st.stop()

# ---------------- header ----------------
try:
    qd = load_quote(ticker)
    h1, h2, h3, h4 = st.columns([3, 2, 2, 3])
    h1.markdown(f"## {sym.ticker}\n{sym.name if sym.name != sym.ticker else sym.asset_class.title()} · {sym.market}")
    h2.metric("Last close", fmt(qd["price"], 5 if qd["price"] < 20 else 2), f"{qd['change_pct']:+.2f}%")
    h3.metric("Data source", qd["source"] or "n/a")
    h4.markdown(f"[🔎 Cross-check on Investing.com]({sym.investing_url})")
except Exception as e:
    st.error(f"Could not load prices for {ticker}: {e}")
    st.stop()

tabs = st.tabs(["📈 Chart", "🧭 Signals", "🔮 Forecast", "🏦 Fundamentals", "📰 News", "🤖 Agent", "📄 Report", "📋 Watchlist scan"])

# ---------------- Chart ----------------
with tabs[0]:
    from ui.components.charts import price_chart

    c1, c2, c3 = st.columns(3)
    overlays = c1.multiselect("Overlays", ["ema_9", "ema_21", "ema_50", "ema_200", "sma_20", "sma_50", "sma_200"],
                              default=["ema_21", "ema_50", "ema_200"])
    panels = c2.multiselect("Panels", ["volume", "rsi", "macd", "stoch", "adx", "atr"],
                            default=(["volume"] if sym.has_real_volume else []) + ["rsi", "macd"])
    opts = c3.multiselect("Extras", ["Bollinger", "VWAP", "S/R levels"], default=["Bollinger", "S/R levels"])
    try:
        df = load_ohlcv(ticker, tf)
        levels = None
        if "S/R levels" in opts:
            t = load_technical(ticker)["timeframes"].get(tf, {})
            levels = {"supports": t.get("supports", []), "resistances": t.get("resistances", [])}
        st.plotly_chart(price_chart(df, f"{sym.ticker} · {tf}", overlays, "Bollinger" in opts,
                                    "VWAP" in opts and sym.has_real_volume, panels, levels, sym.has_real_volume),
                        width="stretch")
        if not sym.has_real_volume:
            st.caption("Spot FX has no centralised volume, so volume and VWAP are hidden for this symbol.")
    except Exception as e:
        st.error(f"Chart error: {e}")

# ---------------- Signals ----------------
with tabs[1]:
    from signals.history import SignalHistory
    from signals.service import sort_cards, watchlist_signals, with_sizing
    from ui.components.signal_card import (
        card_html, history_tables, inject_css, render_details, render_glossary,
    )

    inject_css()
    st.markdown("### Today's signals")
    st.caption("One card per symbol: what to do, why, and the exact prices. The full analysis runs in the background. "
               "Open **Show details** on a card to see the technical data behind it.")

    # ---- position size helper (remembered for this session) ----
    with st.container(border=True):
        st.markdown("**🧮 Position size helper**: how much to trade so a stop-loss hit costs only what you choose")
        p1, p2, p3 = st.columns(3)
        acct = p1.number_input("Account size", min_value=1.0, value=float(S.account_size), step=100.0, key="acct")
        risk = p2.number_input("Risk per trade (%)", min_value=0.1, max_value=10.0, step=0.25,
                               value=float(S.risk_per_trade_pct), key="riskpct",
                               help="Beginners usually risk 0.5–2% of the account on one trade.")
        ccys = ["EUR", "USD", "GBP", "INR", "CHF", "PLN"]
        default_ccy = S.account_currency.upper() if S.account_currency.upper() in ccys else "EUR"
        acct_ccy = p3.selectbox("Account currency", ccys, index=ccys.index(default_ccy), key="acctccy")
        st.caption(f"If the stop loss is hit you lose about **{acct * risk / 100:,.2f} {acct_ccy}**. "
                   f"Forex sizes follow XTB rules: 1 lot = 100,000 units, smallest trade {S.fx_min_lot} lots, "
                   f"margin at 1:{S.leverage:g}.")

    f1, f2 = st.columns([3, 1])
    st.session_state.setdefault("sig_refresh", 0)
    if f2.button("🔄 Refresh signals", width="stretch", help="Re-run the full analysis now (TimesFM takes a few seconds per symbol)"):
        st.session_state.sig_refresh += 1
        st.session_state["sig_force"] = True

    @st.cache_data(ttl=300, show_spinner=False)
    def load_signal_cards(symbols: tuple[str, ...], refresh: int, force: bool) -> list[dict]:
        return watchlist_signals(list(symbols), force=force)

    syms = list(wl.symbols())
    if ticker not in syms:
        syms.append(ticker)  # the symbol open in the sidebar gets a card too
    try:
        with st.spinner("Updating signals (first run loads the forecasting model, about 30 s)…"):
            cards = load_signal_cards(tuple(syms), st.session_state.sig_refresh, st.session_state.pop("sig_force", False))
    except Exception as e:
        cards = []
        st.error(f"Signals unavailable: {e}")

    counts = {k: sum(1 for c in cards if c.get("action") == k) for k in ("BUY", "SELL", "WAIT")}
    flt = f1.radio("Show", ["All", "Buy", "Sell", "Wait"], horizontal=True, key="sig_filter",
                   format_func=lambda x: x if x == "All" else f"{x} ({counts[x.upper()]})")
    shown = [c for c in sort_cards(cards) if flt == "All" or c.get("action") == flt.upper()]
    hist = SignalHistory()
    wins = hist.win_rates()
    if not shown:
        st.info("No signals match this filter." if cards else "Add symbols to your watchlist in the sidebar to see signals.")
    for i, c in enumerate(shown):
        if c.get("action") in ("BUY", "SELL"):
            try:
                c = with_sizing(c, acct, risk, acct_ccy)
            except Exception as e:
                st.caption(f"Position size unavailable: {e}")
        with st.container(border=True):
            if c["symbol"] not in wl.symbols():
                st.caption("Not in your watchlist: shown because it's open in the sidebar")
            st.markdown(card_html(c, wins.get(c["symbol"])), unsafe_allow_html=True)
            if c.get("action") != "ERROR":
                render_glossary(f"g{i}", c.get("is_fx", False))
                with st.expander("Show details"):
                    render_details(c, f"{i}_{c['symbol']}", load_ohlcv, load_forecast)

    # ---- history & win rate ----
    with st.expander("📊 Signal history & win rate"):
        rows = hist.history(limit=300)
        if not rows:
            st.caption("No BUY/SELL signals recorded yet. Every BUY/SELL card is saved automatically and checked against "
                       "later prices: hit target, hit stop or expired.")
        else:
            wr_df, hist_df = history_tables(rows, wins)
            st.markdown("**Win rate per symbol** (target hits ÷ (target hits + stop hits). Expired signals aren't counted.)")
            st.dataframe(wr_df, hide_index=True, width="stretch")
            st.markdown("**All signals**")
            st.dataframe(hist_df, hide_index=True, width="stretch")
            st.download_button("⬇ Download history (.csv)", hist_df.to_csv(index=False), file_name="signal_history.csv")

    # ---- the previous per-symbol technical view, unchanged ----
    with st.expander(f"🔬 Technical breakdown for {ticker} ({tf})"):
        try:
            t = load_technical(ticker)
            icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
            st.markdown(f"### {icon[t['bias']]} Multi-timeframe: **{t['bias'].upper()}** (score {t['score']:+.0f}, {t['alignment']})")
            rows = [{"Timeframe": k, "Bias": f"{icon[v['bias']]} {v['bias']}", "Score": v["score"],
                     "Trend": f"{v['trend']} ({v['trend_strength']})", "RSI": v["snapshot"]["rsi_14"],
                     "ADX": v["snapshot"]["adx"], "ATR %": v["snapshot"]["atr_pct"]} for k, v in t["timeframes"].items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            sel = t["timeframes"].get(tf) or next(iter(t["timeframes"].values()))
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Reasoning ({sel['timeframe']})**")
                for r in sel["reasons"]:
                    st.markdown(f"- {r}")
                if sel["patterns"]:
                    st.markdown("**Recent candlestick patterns**")
                    for p in sel["patterns"][-6:]:
                        st.markdown(f"- {p['date'][:16]} · {p['name']} ({p['direction']})")
            with c2:
                st.markdown("**Support / resistance**")
                st.dataframe(pd.DataFrame(
                    [{"Level": "R", **l} for l in reversed(sel["resistances"])] + [{"Level": "S", **l} for l in sel["supports"]]),
                    hide_index=True, width="stretch")
                st.markdown("**Indicator snapshot**")
                st.json(sel["snapshot"], expanded=False)
            if t.get("errors"):
                st.caption("Unavailable timeframes: " + "; ".join(f"{k}: {v}" for k, v in t["errors"].items()))
        except Exception as e:
            st.error(f"Technical analysis failed: {e}")

# ---------------- Forecast ----------------
with tabs[2]:
    from ui.components.charts import forecast_chart

    c1, c2, c3 = st.columns(3)
    horizon = c1.selectbox("Horizon (candles)", sorted(set(S.horizons + [5, 10, 30])), index=1)
    multivar = c2.checkbox("Multivariate (related assets + volume)", value=True,
                           help="Adds e.g. DXY for FX pairs or NIFTY/S&P 500 for stocks as extra series")
    st.caption(f"Model: {S.timesfm_checkpoint} · forecasting on **{tf}** candles · first run downloads the weights (~1.3 GB)")
    if c3.button("Run forecast", type="primary"):
        st.session_state["fc_req"] = (ticker, tf, horizon, multivar)
    req = st.session_state.get("fc_req")
    if req and req[0] == ticker:
        try:
            with st.spinner("Running TimesFM-3…"):
                fc = load_forecast(*req)
            st.plotly_chart(forecast_chart(load_ohlcv(ticker, req[1]), fc), width="stretch")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Median end price", fmt(fc["median"][-1], 5), f"{fc['expected_change_pct']:+.2f}%")
            m2.metric("10–90% range", f"{fc['q10'][-1]:.5g} – {fc['q90'][-1]:.5g}")
            m3.metric("P(finish higher)", f"{fc['prob_up']:.0%}")
            m4.metric("Variates", ", ".join(fc["variates"]))
            with st.expander("Forecast table"):
                st.dataframe(pd.DataFrame({k: fc[k] for k in ("dates", "q10", "q25", "median", "q75", "q90")}),
                             hide_index=True, width="stretch")
        except Exception as e:
            st.error(f"Forecast failed: {e}")

    st.divider()
    st.markdown("#### How much should I trust it? Backtest")
    b1, b2 = st.columns([3, 1])
    windows = b1.slider("Backtest windows", 10, 60, 30, help="More windows = more reliable metrics, slower")
    if b2.button("Run backtest"):
        from forecasting.service import backtest_symbol

        try:
            with st.spinner("Backtesting (about 1 minute on CPU)…"):
                bt = backtest_symbol(sym, tf, horizon, n_windows=windows, multivariate=multivar).as_dict()
            load_forecast.clear()
            st.session_state["bt"] = bt
        except Exception as e:
            st.error(f"Backtest failed: {e}")
    from forecasting.backtest import load_result

    bt = st.session_state.get("bt")
    if not bt or bt.get("symbol") != sym.ticker:
        r = load_result(sym.ticker, tf, horizon)
        bt = r.as_dict() if r else None
    if bt:
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("MAPE", f"{bt['mape']:.2f}%", f"naive {bt['naive_mape']:.2f}%", delta_color="off")
        k2.metric("MAE", f"{bt['mae']:.5g}", f"naive {bt['naive_mae']:.5g}", delta_color="off")
        k3.metric("Directional accuracy", f"{bt['directional_accuracy']:.0f}%", "50% = coin flip", delta_color="off")
        k4.metric("80% band coverage", f"{bt['coverage_80']:.0f}%", "ideal ≈ 80%", delta_color="off")
        k5.metric("Skill vs naive", f"{bt['skill_vs_naive']:+.3f}", "> 0 beats 'no change'", delta_color="off")
        st.info(f"Trust: **{bt['trust']}** · {bt['n_windows']} windows · {bt['timeframe']} h={bt['horizon']} · run {bt['run_at']}")
    else:
        st.caption("No backtest saved for this symbol, timeframe and horizon yet.")

# ---------------- Fundamentals ----------------
with tabs[3]:
    try:
        with st.spinner("Loading fundamentals…"):
            f = load_fundamentals(ticker)
        icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
        st.markdown(f"### {icon.get(f['bias'], '⚪')} Fundamental bias: **{f['bias']}** (score {f['score']:+.0f})")
        if "metrics" in f:
            m = f["metrics"]
            cols = st.columns(4)
            items = [("P/E (ttm)", m["pe_trailing"]), ("Forward P/E", m["pe_forward"]),
                     ("Sector P/E", f["valuation"].get("sector_pe")), ("EPS (ttm)", m["eps_trailing"]),
                     ("Revenue growth %", m["revenue_growth_pct"]), ("Earnings growth %", m["earnings_growth_pct"]),
                     ("Net margin %", m["profit_margin_pct"]), ("ROE %", m["roe_pct"]),
                     ("Debt/Equity", m["debt_to_equity"]), ("Analyst target", m["analyst_target"]),
                     ("Next earnings", m["next_earnings_date"]), ("Recommendation", m["recommendation"])]
            for i, (k, v) in enumerate(items):
                cols[i % 4].metric(k, fmt(v, 2) if isinstance(v, float) else (v or "n/a"))
            st.caption(f"{m.get('name') or ''} · {m.get('sector') or ''} / {m.get('industry') or ''} · "
                       f"benchmark: {f['valuation'].get('benchmark')}")
            c1, c2 = st.columns(2)
            c1.markdown("**Strengths**\n" + "\n".join(f"- {s}" for s in f["strengths"]) if f["strengths"] else "")
            c2.markdown("**Weaknesses**\n" + "\n".join(f"- {s}" for s in f["weaknesses"]) if f["weaknesses"] else "")
            for u in f.get("upcoming", []):
                st.warning(u)
        else:
            rows = []
            for k in ("base", "quote"):
                cm = f[k]
                rows.append({"Currency": cm["currency"], "Central bank": cm["central_bank"], "Policy rate %": cm["policy_rate"],
                             "Δ6m": cm["rate_change_6m"], "CPI YoY %": cm["inflation_yoy"], "Target %": cm["inflation_target"],
                             "10y %": cm["bond_10y"], "GDP YoY %": cm["gdp_growth_yoy"], "CB lean": cm["cb_lean"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.markdown("**Drivers**\n" + "\n".join(f"- {d}" for d in f["drivers"]))
            if f["events"]:
                st.markdown("**Upcoming events**")
                st.dataframe(pd.DataFrame(f["events"]), hide_index=True, width="stretch")
            missing = [m for k in ("base", "quote") for m in f[k].get("missing", [])]
            if missing:
                with st.expander("Data gaps"):
                    st.write(missing)
    except Exception as e:
        st.error(f"Fundamentals unavailable: {e}")

# ---------------- News ----------------
with tabs[4]:
    days = st.slider("Days of news", 1, 30, 7)
    try:
        with st.spinner("Scoring headlines…"):
            n = load_news(ticker, days)
        st.markdown(f"### Sentiment: **{n['label']}** ({n['score']:+.2f}) · {n['n_articles']} articles · method: {n['method']}")
        for h in n["headlines"]:
            dot = "🟢" if h["sentiment"] > 0.15 else "🔴" if h["sentiment"] < -0.15 else "⚪"
            st.markdown(f"{dot} [{h['title']}]({h['url']}): _{h['source']}, {h['date']}_ ({h['sentiment']:+.2f})")
    except Exception as e:
        st.error(f"News unavailable: {e}")

# ---------------- Agent chat ----------------
with tabs[5]:
    from agent.report import markdown_to_pdf

    if not S.anthropic_api_key and S.llm_provider == "anthropic":
        st.warning("Set ANTHROPIC_API_KEY in .env to use the agent (see SETUP.md).")
    st.session_state.setdefault("chat", [])
    c1, c2 = st.columns([3, 1])
    deep = c2.toggle("Deep mode", help=f"Use {S.llm_deep_model} instead of {S.llm_model}")
    if c1.button("🗑 Clear chat"):
        st.session_state.chat = []
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    prompt = st.chat_input(f"Ask, e.g. 'Analyse {ticker} for this week' or 'Is RELIANCE a buy right now?'")
    if prompt:
        st.session_state.chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            status = st.status("Thinking…", expanded=False)

            def on_event(kind, payload):
                if kind == "tool_start":
                    status.write(f"🔧 {payload['name']}({', '.join(f'{k}={v}' for k, v in payload['input'].items())})")

            try:
                from agent.agent import TradingAgent

                res = TradingAgent().ask(prompt, st.session_state.chat[:-1], deep=deep, on_event=on_event)
                status.update(label=f"Done · {len(res.tool_calls)} tool calls · {res.model}", state="complete")
                answer = res.text or "_(empty response)_"
            except Exception as e:
                status.update(label="Error", state="error")
                answer = f"⚠️ {e}"
            st.markdown(answer)
        st.session_state.chat.append({"role": "assistant", "content": answer})

    last = next((m["content"] for m in reversed(st.session_state.chat) if m["role"] == "assistant"), None)
    if last:
        d1, d2 = st.columns(2)
        d1.download_button("⬇ Last answer (.md)", last, file_name=f"{sym.plain}_agent.md")
        try:
            d2.download_button("⬇ Last answer (.pdf)", markdown_to_pdf(last), file_name=f"{sym.plain}_agent.pdf")
        except Exception as e:
            d2.caption(f"PDF export failed: {e}")

# ---------------- Report ----------------
with tabs[6]:
    from agent.report import analysis_to_markdown, markdown_to_pdf

    st.caption("A rule-based report with no LLM involved. Use the Agent tab for a written narrative.")
    c1, c2, c3 = st.columns(3)
    r_h = c1.selectbox("Forecast horizon", [5, 10, 30], index=1, key="rep_h")
    r_fc = c2.checkbox("Include TimesFM forecast", value=True)
    if c3.button("Generate report", type="primary"):
        try:
            with st.spinner("Running full analysis…"):
                st.session_state["report"] = (ticker, analysis_to_markdown(load_full(ticker, tf, r_h, r_fc)))
        except Exception as e:
            st.error(f"Report failed: {e}")
    rep = st.session_state.get("report")
    if rep and rep[0] == ticker:
        st.markdown(rep[1])
        d1, d2 = st.columns(2)
        d1.download_button("⬇ Markdown", rep[1], file_name=f"{sym.plain}_report.md")
        d2.download_button("⬇ PDF", markdown_to_pdf(rep[1]), file_name=f"{sym.plain}_report.pdf")

# ---------------- Watchlist scan ----------------
with tabs[7]:
    st.caption("Runs the rule-based analysis on every watchlist symbol (no LLM cost). The same scan the daily WhatsApp alert uses.")
    c1, c2 = st.columns(2)
    if c1.button("Scan watchlist now", type="primary"):
        from alerts.scanner import format_digest, scan

        with st.spinner("Scanning…"):
            rows = scan()
        st.session_state["scan"] = (rows, format_digest(rows))
    if "scan" in st.session_state:
        rows, digest = st.session_state["scan"]
        st.dataframe(pd.DataFrame([{"Symbol": r.symbol, "Price": r.price, "Bias": r.bias, "Score": r.score,
                                    "Confidence": r.confidence, "RSI(D)": r.rsi_d, "Flags": ", ".join(r.flags),
                                    "Error": r.error} for r in rows]), hide_index=True, width="stretch")
        st.code(digest, language=None)
        if c2.button("📲 Send to WhatsApp"):
            from alerts.whatsapp import get_notifier

            try:
                ok = get_notifier().send(digest)
                st.success("Sent") if ok else st.warning("Not sent. Set WHATSAPP_BACKEND in .env (see SETUP.md).")
            except Exception as e:
                st.error(f"WhatsApp error: {e}")

st.caption("⚠️ Not financial advice. ShreeAgent AI produces automated analysis only. You make the final decision.")
