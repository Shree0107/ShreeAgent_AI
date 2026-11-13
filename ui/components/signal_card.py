"""Beginner signal card for the Streamlit Signals tab.

The main card is plain HTML (large text, colour-coded, phone-friendly). Technical data sits in a
collapsed "Show details" expander. Glossary terms get a hover tooltip plus a tap-friendly popover.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from signals.explain import GLOSSARY
from signals.history import STATUS_TEXT

CSS = """
<style>
.sa-card{font-size:1.05rem;line-height:1.5}
.sa-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.sa-sym{font-size:1.6rem;font-weight:700;line-height:1.2}
.sa-sub{opacity:.75;font-size:.95rem}
.sa-price{font-size:1.3rem;font-weight:600;text-align:right}
.sa-decision{display:flex;align-items:center;gap:16px;margin:14px 0 6px;flex-wrap:wrap}
.sa-badge{font-size:2.1rem;font-weight:800;letter-spacing:.06em;color:#fff;padding:6px 26px;border-radius:12px;min-width:150px;text-align:center}
.sa-BUY{background:#1a7f37}.sa-SELL{background:#c62828}.sa-WAIT{background:#b26a00}.sa-ERROR{background:#6b6b6b}
.sa-conf{flex:1;min-width:200px}
.sa-conf b{font-size:1.1rem}
.sa-sec{margin-top:14px}
.sa-sec h4{margin:0 0 4px;font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;opacity:.7}
.sa-sec ul{margin:0;padding-left:1.2em}
.sa-sec li{margin:2px 0}
.sa-big{font-size:1.3rem;font-weight:700}
.sa-box{border-radius:10px;padding:10px 14px;margin-top:6px}
.sa-wait{background:rgba(178,106,0,.12);border-left:5px solid #b26a00}
.sa-stop{background:rgba(198,40,40,.10);border-left:5px solid #c62828}
.sa-tp{background:rgba(26,127,55,.10);border-left:5px solid #1a7f37}
.sa-entry{background:rgba(42,120,214,.10);border-left:5px solid #2a78d6}
.sa-cancel{background:rgba(128,128,128,.10);border-left:5px solid #888}
.sa-tp table{width:100%;border-collapse:collapse}
.sa-tp td{padding:2px 6px 2px 0;vertical-align:top}
.sa-tp td.n{font-weight:700;white-space:nowrap}
.sa-why{opacity:.75;font-size:.92rem}
.sa-warn{background:rgba(237,161,0,.18);border-radius:10px;padding:8px 12px;margin-top:12px;font-weight:600}
.sa-meta{opacity:.7;font-size:.88rem;margin-top:12px}
.sa-disc{opacity:.65;font-size:.85rem;font-style:italic;margin-top:8px;border-top:1px solid rgba(128,128,128,.3);padding-top:6px}
.sa-term{border-bottom:1px dotted currentColor;cursor:help}
@media (max-width:640px){.sa-badge{font-size:1.7rem;min-width:120px;padding:4px 18px}.sa-sym{font-size:1.35rem}.sa-price{text-align:left}}
</style>
"""

ACTION_LABEL = {"BUY": "BUY", "SELL": "SELL", "WAIT": "WAIT", "ERROR": "ERROR"}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def e(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def term(word: str, label: str | None = None) -> str:
    tip = GLOSSARY.get(word, "")
    return f'<span class="sa-term" title="{e(tip)}">{e(label or word)} ⓘ</span>' if tip else e(label or word)


def _when(iso: str) -> str:
    try:
        t = datetime.fromisoformat(iso).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return iso or ""
    return t.strftime("%a %d %b %H:%M UTC").replace(" 0", " ")


def _ago(iso: str) -> str:
    try:
        mins = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return ""
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins:.0f} min ago"
    if mins < 48 * 60:
        return f"{mins / 60:.0f} h ago"
    return f"{mins / 1440:.0f} days ago"


def card_html(c: dict, win: dict | None = None) -> str:
    if c.get("action") == "ERROR":
        return (f'<div class="sa-card"><div class="sa-sym">{e(c["symbol"])}</div>'
                f'<div class="sa-decision"><span class="sa-badge sa-ERROR">NO DATA</span>'
                f'<div class="sa-conf">Couldn\'t build a signal: {e(c.get("error", ""))[:300]}</div></div></div>')
    ex = c["explanation"]
    a = c["action"]
    name = c.get("name") if c.get("name") and c.get("name") != c["symbol"] else c.get("asset_class", "").title()
    chg = c.get("change_pct")
    chg_txt = f" ({chg:+.2f}% today)" if isinstance(chg, (int, float)) else ""
    conf_label, _, conf_reason = ex["confidence_text"].partition(" – ")

    h = [f'<div class="sa-card"><div class="sa-top"><div><div class="sa-sym">{e(c["symbol"])}</div>'
         f'<div class="sa-sub">{e(name)} · {e(c.get("market", ""))}</div></div>'
         f'<div class="sa-price">{e(c["price_text"])}<div class="sa-sub">{e(chg_txt)}</div></div></div>',
         f'<div class="sa-decision"><span class="sa-badge sa-{a}">{ACTION_LABEL[a]}</span>'
         f'<div class="sa-conf"><b>{term("Confidence")}: {e(conf_label.upper())}</b><br>{e(conf_reason)}</div></div>']

    if ex["reasons"]:
        h.append('<div class="sa-sec"><h4>Why?</h4><ul>' + "".join(f"<li>{e(r)}</li>" for r in ex["reasons"]) + "</ul></div>")

    if a == "WAIT":
        h.append('<div class="sa-sec"><h4>What am I waiting for?</h4><div class="sa-box sa-wait"><ul>'
                 + "".join(f"<li>{e(w)}</li>" for w in ex["waiting_for"]) + "</ul></div></div>")
    elif a in ("BUY", "SELL"):
        h.append(f'<div class="sa-sec"><h4>When should I enter? ({term("Entry zone", "entry zone")})</h4>'
                 f'<div class="sa-box sa-entry"><div class="sa-big">{e(ex["entry_text"])}</div>{e(ex["entry_confirm"])}</div></div>')
        h.append(f'<div class="sa-sec"><h4>{term("Stop loss")}</h4><div class="sa-box sa-stop">'
                 f'<div class="sa-big">{e(ex["stop_text"])}</div><span class="sa-why">{e(ex["stop_why"])}</span></div></div>')
        rows = "".join(
            f'<tr><td class="n">{e(t["label"])}</td><td class="n">{e(t["price_text"])}</td>'
            f'<td class="n">+{t["pct"]:.2f}%</td><td class="n">{e(t["money"] or "")}</td></tr>'
            f'<tr><td></td><td colspan="3" class="sa-why">{e(t["distance"])} · {e(t["why"])}</td></tr>'
            for t in ex["targets"])
        h.append(f'<div class="sa-sec"><h4>{term("Take profit")}</h4><div class="sa-box sa-tp"><table>{rows}</table></div></div>')
        h.append(f'<div class="sa-sec"><h4>{term("Risk vs reward")}</h4><div class="sa-big">{e(ex["rr_text"])}</div></div>')
        if ex.get("size_text"):
            unit = term("Lot", "Position size") if c.get("is_fx") else term("Shares", "Position size")
            h.append(f'<div class="sa-sec"><h4>{unit}</h4><div class="sa-big">{e(ex["size_text"])}</div>'
                     f'<span class="sa-why">{e(ex.get("size_note", ""))}</span></div>')
        h.append('<div class="sa-sec"><h4>What would cancel this trade?</h4><div class="sa-box sa-cancel"><ul>'
                 + "".join(f"<li>{e(x)}</li>" for x in ex["cancel"]) + "</ul></div></div>")

    if ex.get("event_warning"):
        h.append(f'<div class="sa-warn">⚠️ Upcoming: {e(ex["event_warning"])}</div>')
    others = [ev for ev in ex.get("events", [])[1:4]]
    if others:
        h.append('<div class="sa-meta">Also coming up: ' + "; ".join(
            f'{e(ev["plain"])} ({e(ev["date"][5:])})' for ev in others) + "</div>")

    meta = f'🕒 Generated {_when(c["generated_at"])} ({_ago(c["generated_at"])}) · {term("Expiry", "Expires")} {_when(c["expires_at"])}'
    if win and (win.get("wins") or win.get("losses")):
        meta += (f'<br>📊 Past signals for {e(c["symbol"])}: {win["wins"]} win{"s" if win["wins"] != 1 else ""} / '
                 f'{win["losses"]} loss{"es" if win["losses"] != 1 else ""} ({win["win_rate"]:.0f}% win rate)')
    elif win and win.get("open"):
        meta += f"<br>📊 {win['open']} signal(s) for {e(c['symbol'])} still being tracked, no results yet"
    h.append(f'<div class="sa-meta">{meta}</div>')
    if c.get("polished"):
        h.append('<div class="sa-meta">✏️ Wording polished by AI · numbers are computed and locked</div>')
    h.append(f'<div class="sa-disc">{e(c["disclaimer"])}</div></div>')
    return "".join(h)


def render_glossary(key: str, is_fx: bool) -> None:
    words = ["Stop loss", "Take profit", "Entry zone", "Risk vs reward", "Confidence", "Expiry", "Daily candle"]
    words += ["Lot", "Pip", "Spread", "Margin"] if is_fx else ["Shares"]
    with st.popover("📖 What do these words mean?"):
        for w in words:
            st.markdown(f"**{w}**: {GLOSSARY[w]}")


def render_details(c: dict, key: str, load_ohlcv=None, load_forecast=None) -> None:
    """The technical data behind the signal (hidden by default)."""
    from ui.components.charts import forecast_chart, score_bar, signal_chart

    d = c.get("details") or {}
    lv = c.get("levels") or {}
    st.markdown("**How the decision was scored** (each part from −100 to +100; the overall score needs "
                "≥ the minimum to suggest a direction)")
    comps = d.get("components") or {}
    if comps:
        st.plotly_chart(score_bar(comps), width="stretch", key=f"sb_{key}")
    st.caption(f"Overall score {c['score']:+.0f} · weights used: "
               + ", ".join(f"{k} {v:.2f}" for k, v in (d.get("weights") or {}).items())
               + f" · decision checks that said WAIT: {', '.join(c['decision']['wait_codes']) or 'none'}")

    if lv:
        st.markdown("**Levels (daily chart)**")
        rows = [("Entry zone", f"{lv['entry_low']} – {lv['entry_high']} ({lv['entry_kind']})"),
                ("Stop loss", f"{lv['stop']} ({lv['stop_kind']}, anchor {lv.get('stop_anchor')} {lv.get('stop_anchor_date') or ''})"),
                ("Target 1", f"{lv['target1']} ({lv['target1_kind']}, R:R {lv['rr1']})"),
                ("Target 2", f"{lv['target2']} ({lv['target2_kind']}, R:R {lv['rr2']})"),
                ("Daily range (ATR 14)", f"{(d.get('facts') or {}).get('atr', 0):.5g}"),
                ("Level checks", ", ".join(lv.get("problems") or []) or "ok")]
        st.dataframe(pd.DataFrame(rows, columns=["", "Value"]), hide_index=True, width="stretch")

    tfs = d.get("timeframes") or {}
    if tfs:
        st.markdown("**Indicators per timeframe**")
        st.dataframe(pd.DataFrame([{
            "Timeframe": k, "Bias": v.get("bias"), "Score": v.get("score"),
            "Trend": f"{v.get('trend')} ({v.get('trend_strength')})", "RSI": (v.get("snapshot") or {}).get("rsi_14"),
            "ADX": (v.get("snapshot") or {}).get("adx"), "ATR %": (v.get("snapshot") or {}).get("atr_pct"),
        } for k, v in tfs.items()]), hide_index=True, width="stretch")
        tf = tfs.get(c.get("timeframe")) or {}
        if tf.get("reasons"):
            st.markdown("**Technical signals (daily)**\n" + "\n".join(f"- {r}" for r in tf["reasons"]))
    sr = (d.get("resistances") or [])[::-1] + (d.get("supports") or [])
    if sr:
        st.markdown("**Support / resistance**")
        st.dataframe(pd.DataFrame(sr), hide_index=True, width="stretch")
    fc = d.get("forecast")
    if fc:
        bt = fc.get("backtest") or {}
        st.markdown(f"**TimesFM-3 forecast** ({fc['horizon']} × {fc['timeframe']}): median end "
                    f"{fc['median'][-1]:.5g} ({fc['expected_change_pct']:+.2f}%), chance of finishing higher "
                    f"{fc['prob_up']:.0%}, backtest trust: {bt.get('trust', 'not backtested yet')}")
    sent = d.get("sentiment") or {}
    if sent.get("label"):
        st.caption(f"News: {sent['label']} ({sent.get('score', 0):+.2f}, {sent.get('n_articles')} articles, {sent.get('method')}) · "
                   f"Fundamentals: {d.get('fundamental_bias') or 'n/a'}")
    if c.get("errors"):
        st.caption("Data gaps: " + "; ".join(f"{k}: {v}" for k, v in c["errors"].items()))

    if load_ohlcv and st.checkbox("Show charts (price with levels + forecast)", key=f"ch_{key}"):
        try:
            df = load_ohlcv(c["symbol"], c.get("timeframe", "1d"))
            st.plotly_chart(signal_chart(df, c), width="stretch", key=f"sc_{key}")
            if load_forecast and fc:
                full = load_forecast(c["symbol"], fc["timeframe"], fc["horizon"], True)
                st.plotly_chart(forecast_chart(df, full), width="stretch", key=f"fc_{key}")
        except Exception as ex:
            st.error(f"Chart unavailable: {ex}")


def history_tables(history_rows: list[dict], win_rates: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    wr = pd.DataFrame([{
        "Symbol": s, "Wins": w["wins"], "Losses": w["losses"],
        "Win rate": f"{w['win_rate']:.0f}%" if w["win_rate"] is not None else "–",
        "Expired": w["expired"], "Still open": w["open"], "Other": w["other"],
    } for s, w in sorted(win_rates.items())])
    hist = pd.DataFrame([{
        "Generated": _when(r["generated_at"]), "Symbol": r["symbol"], "Action": r["action"],
        "Entry": f"{r['entry_low']} – {r['entry_high']}", "Stop": r["stop"], "Target 1": r["target1"],
        "Target 2": r["target2"], "Confidence": r["confidence"], "Result": STATUS_TEXT.get(r["status"], r["status"]),
        "Closed": _when(r["resolved_at"]) if r["resolved_at"] else "",
    } for r in history_rows])
    return wr, hist
