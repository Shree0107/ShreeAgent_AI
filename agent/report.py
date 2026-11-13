"""Report export: Markdown (from full_analysis output or agent text) and PDF (reportlab)."""
from __future__ import annotations

import io
import re

from analysis.combined import DISCLAIMER


def _f(x, nd=None):
    """Format numbers. Without nd, precision follows the price (EUR/USD 1.10534, stocks 446.05)."""
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        x = float(x)
        if nd is None:
            ax = abs(x)
            nd = 2 if ax >= 20 else 5 if ax >= 1 else 6
        return f"{x:,.{nd}f}".rstrip("0").rstrip(".") if abs(x) < 1e6 else f"{x:,.0f}"
    return str(x)


def analysis_to_markdown(a: dict) -> str:
    """Deterministic report built from analysis.combined.full_analysis(). No LLM needed."""
    c = a.get("combined", {})
    tp = a.get("trade_plan", {})
    L = [
        f"# {a['symbol']} | {c.get('bias', 'n/a').title()} ({c.get('confidence', 'n/a')} confidence)",
        f"_Generated {a.get('generated_at', '')}_ · **Price** {_f(a.get('price'))} · "
        f"[Cross-check on Investing.com]({a.get('investing_url', '')})",
        "",
        f"**Combined score** {c.get('score')} (range -100..100) · components: "
        + ", ".join(f"{k} {v}" for k, v in (c.get("components") or {}).items()),
        "",
        "## Technical",
        "| Timeframe | Bias | Score | Trend | RSI | ADX |",
        "|---|---|---|---|---|---|",
    ]
    for tf, s in (a.get("technical", {}).get("timeframes") or {}).items():
        snap = s.get("snapshot", {})
        L.append(f"| {tf} | {s['bias']} | {s['score']} | {s['trend']} ({s['trend_strength']}) | "
                 f"{_f(snap.get('rsi_14'), 1)} | {_f(snap.get('adx'), 1)} |")
    d1 = (a.get("technical", {}).get("timeframes") or {}).get(tp.get("timeframe", "1d"), {})
    if d1.get("reasons"):
        L += ["", "Key signals:"] + [f"- {r}" for r in d1["reasons"][:6]]

    f = a.get("fundamental")
    if f:
        L += ["", "## Fundamental / Macro"]
        if "metrics" in f:
            m = f["metrics"]
            v = f.get("valuation", {})
            L.append(f"- {m.get('name') or ''} · {m.get('sector') or ''} / {m.get('industry') or ''}")
            L.append(f"- P/E {_f(m.get('pe_trailing'), 1)} (fwd {_f(m.get('pe_forward'), 1)}) vs sector "
                     f"{_f(v.get('sector_pe'), 1)} [{v.get('benchmark')}]")
            L.append(f"- Revenue growth {_f(m.get('revenue_growth_pct'), 1)}% · Earnings growth "
                     f"{_f(m.get('earnings_growth_pct'), 1)}% · Net margin {_f(m.get('profit_margin_pct'), 1)}% · "
                     f"ROE {_f(m.get('roe_pct'), 1)}%")
            L.append(f"- Debt/Equity {_f(m.get('debt_to_equity'), 1)} · Next earnings {m.get('next_earnings_date') or 'n/a'}")
            L += [f"- ✅ {s}" for s in f.get("strengths", [])] + [f"- ⚠️ {w}" for w in f.get("weaknesses", [])]
        else:
            for k in ("base", "quote"):
                cm = f.get(k) or {}
                if cm.get("policy_rate") is not None or cm.get("inflation_yoy") is not None:
                    L.append(f"- **{cm.get('currency')}** rate {_f(cm.get('policy_rate'), 2)}% · CPI "
                             f"{_f(cm.get('inflation_yoy'), 2)}% · 10y {_f(cm.get('bond_10y'), 2)}% · "
                             f"GDP {_f(cm.get('gdp_growth_yoy'), 2)}% · CB lean {cm.get('cb_lean')}")
            L += [f"- {d}" for d in f.get("drivers", [])]
        for e in (f.get("events") or [])[:8]:
            L.append(f"- 📅 {e['date']} {e['currency']}: {e['title']}")
        for u in f.get("upcoming") or []:
            L.append(f"- 📅 {u}")

    s = a.get("sentiment")
    if s:
        L += ["", "## News sentiment", f"{s['label']} ({s['score']:+.2f}, {s['n_articles']} articles, {s['method']})"]
        L += [f"- [{h['title']}]({h['url']}) ({h['source']}, {h['sentiment']:+.2f})" for h in s.get("headlines", [])[:5]]

    fc = a.get("forecast")
    if fc:
        L += ["", f"## Forecast (TimesFM-3, {fc['horizon']} × {fc['timeframe']})",
              f"- Median end price {_f(fc['median'][-1])} ({fc['expected_change_pct']:+.2f}%) · "
              f"10-90% range {_f(fc['q10'][-1])} to {_f(fc['q90'][-1])} · P(up) {fc['prob_up']:.0%}"]
        bt = fc.get("backtest")
        if bt:
            L.append(f"- Backtest ({bt['n_windows']} windows): MAPE {bt['mape']}% · directional accuracy "
                     f"{bt['directional_accuracy']}% · 80% band coverage {bt['coverage_80']}% · skill vs naive "
                     f"{bt['skill_vs_naive']:+.3f} → trust **{bt['trust']}**")
        else:
            L.append("- No backtest yet. Treat the forecast as indicative only.")

    kl = a.get("key_levels", {})
    L += ["", "## Key levels",
          "- Resistance: " + (", ".join(_f(l["price"]) for l in kl.get("resistances", [])) or "n/a"),
          "- Support: " + (", ".join(_f(l["price"]) for l in kl.get("supports", [])) or "n/a")]

    sig = a.get("signal")
    if sig and sig.get("action") in ("BUY", "SELL", "WAIT"):
        L += ["", f"## Signal: {sig['action']} (daily chart, not advice)", f"**Confidence:** {sig['confidence']}"]
        L += ["", "Why:"] + [f"- {r}" for r in sig.get("reasons", [])]
        if sig["action"] == "WAIT":
            L += ["", "What to wait for:"] + [f"- {w}" for w in sig.get("waiting_for", [])]
        else:
            L += ["", f"- **Entry:** {sig['entry']}. {sig['entry_condition']}",
                  f"- **Stop loss:** {_f(sig['stop_loss'])}: {sig['stop_why']}",
                  f"- **Target 1:** {_f(sig['target1'])} · **Target 2:** {_f(sig['target2'])} · reward-to-risk "
                  f"{sig['reward_to_risk'][0]} / {sig['reward_to_risk'][1]}"]
            L += ["", "Cancel if:"] + [f"- {x}" for x in sig.get("cancel_if", [])]
        if sig.get("event_warning"):
            L.append(f"- ⚠️ {sig['event_warning']}")
        L.append(f"- Valid until {sig['expires_at'][:16].replace('T', ' ')} UTC")
        tp = {**tp, "direction": "none", "notes": []}   # the signal replaces the older ATR plan below
    L += ["", f"## Trade idea ({tp.get('timeframe')}, not advice)"] if not sig else []
    if tp.get("direction") in ("long", "short"):
        L += [f"- **{tp['direction'].upper()}** entry {_f(tp['entry_zone'][0])} – {_f(tp['entry_zone'][1])}",
              f"- Stop-loss {_f(tp['stop_loss'])} · TP1 {_f(tp['take_profits'][0])} (R:R {tp['risk_reward'][0]}) · "
              f"TP2 {_f(tp['take_profits'][1])} (R:R {tp['risk_reward'][1]})",
              f"- {tp.get('invalidation', '')}"]
    L += [f"- {n}" for n in tp.get("notes", [])]
    L += ["", "## Confidence", f"**{c.get('confidence')}**: " + "; ".join(c.get("confidence_reasons", []))]
    if a.get("errors"):
        L += ["", "_Data gaps: " + "; ".join(f"{k}: {v}" for k, v in a["errors"].items()) + "_"]
    L += ["", f"> {DISCLAIMER}"]
    return "\n".join(L)


def markdown_to_pdf(md: str, title: str = "ShreeAgent AI Report") -> bytes:
    """Minimal Markdown to PDF conversion: headings, bullets, bold/italic/links, tables as monospace text."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)

    def inline(t: str) -> str:
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="blue">\1</link>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", t)
        # Built-in PDF fonts lack emoji glyphs, so strip anything outside the BMP plus common symbols.
        return re.sub(r"[\U00010000-\U0010ffff☀-➿️]", "", t)

    flow = []
    table: list[str] = []
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            if not re.fullmatch(r"\|[\s\-|:]+\|?", line):
                table.append("  ".join(c.strip().ljust(14) for c in line.strip("|").split("|")))
            continue
        if table:
            flow.append(Preformatted("\n".join(table), styles["Code"]))
            table = []
        if line.startswith("# "):
            flow.append(Paragraph(inline(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            flow.append(Paragraph(inline(line[3:]), styles["Heading2"]))
        elif line.startswith("### "):
            flow.append(Paragraph(inline(line[4:]), styles["Heading3"]))
        elif line.startswith(("- ", "* ")):
            flow.append(Paragraph("• " + inline(line[2:]), styles["BodyText"]))
        elif line.startswith("> "):
            flow.append(Paragraph(f"<i>{inline(line[2:])}</i>", styles["BodyText"]))
        elif line.strip():
            flow.append(Paragraph(inline(line), styles["BodyText"]))
        else:
            flow.append(Spacer(1, 4))
    doc.build(flow)
    return buf.getvalue()
