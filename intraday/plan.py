"""The intraday decision: setups + confirmations + gates -> one BUY / SELL / WAIT card per symbol.

    card = build_card(ctx, losses_today=0, live_status=None)

BUY/SELL only when ALL gates pass:
  session      market open, before NO_NEW_ENTRIES_AFTER, London/New York session (EUR/USD)
  news         no high-impact news for the symbol's currencies within +-NEWS_BLACKOUT_MINUTES
  spread       live spread (OANDA) <= the symbol's MAX_SPREAD_PIPS (typical spread used, and said, when unknown)
  data         the latest 15M candle is not late
  loss limit   fewer than DAILY_LOSS_LIMIT stop-loss hits today
  setup        a setup was found and is enabled (settings and, once phase 7 ran, backtest results)
  MTF          see intraday/bias.py (daily + 4H not against, 1H with the trade)
  confirmations >= INTRADAY_MIN_CONFIRMATIONS independent ones agree
  stop width   the stop is not more than 3 x the normal 15-minute candle range away
  reward/risk  target 1 is at least INTRADAY_MIN_RR x the risk away, with no strong level in the way
Otherwise WAIT, with the failed gates in plain words, the range the price is stuck in and both scenarios.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from analysis import indicators as ind
from analysis.patterns import detect_at
from analysis.structure import liquidity as liq
from analysis.structure.swings import zigzag
from intraday import probability
from intraday.bias import all_biases, market_state, mtf, tf_bias
from intraday.context import Context
from intraday.explain import (DIR_WORD, DISCLAIMER, GLOSSARY, MARKET_TEXT, entry_text, rr_words, window_text)
from intraday.levels import key_levels, levels_beyond, nearest_label
from intraday.news import news_check
from intraday.sessions import (active_sessions, entries_allowed, entry_cutoff, flat_time, fmt_local, session_key,
                               session_label)
from intraday.setups import SETUP_NAME, Candidate, detect_all
from signals.market import fmt_distance, fmt_price, price_decimals

CARD_VERSION = 1
MAX_STOP_ATR = 3.0
TF_SECONDS_MAIN = 900


# ------------------------------------------------------------------ targets
def targets(ctx: Context, c: Candidate, min_rr: float) -> tuple[float, float, dict | None]:
    """(tp1, tp2, obstacle). TP1 = first level at >= min_rr x risk; a strong level closer than that is an obstacle."""
    R = c.risk
    s = c.sign
    if c.targets:
        return c.targets[0], c.targets[1], None
    lv = [l for l in levels_beyond(key_levels(ctx), c.entry, c.direction, 0.25 * R)]
    obstacle = next((l for l in lv if abs(l.price - c.entry) < min_rr * R and l.strength >= 1.5
                     and l.kind in ("pdh", "pdl", "asian_high", "asian_low", "zone_1h")), None)
    buf = ctx.spread_price + 0.05 * ctx.atr15
    tp1 = None
    for l in lv:
        d = abs(l.price - c.entry) - buf
        if min_rr * R <= d <= 3.5 * R:
            tp1 = l.price - s * buf
            break
    if tp1 is None:
        tp1 = c.entry + s * max(min_rr, 1.5) * R
    tp2 = None
    for l in lv:
        if (l.price - tp1) * s >= 0.75 * R and abs(l.price - c.entry) <= 5 * R:
            tp2 = l.price - s * buf
            break
    if tp2 is None:
        tp2 = c.entry + s * max(2.5 * R, abs(tp1 - c.entry) + R)
    ob = None
    if obstacle is not None:
        ob = obstacle.as_dict()
        tp1 = obstacle.price - s * buf
        if (tp2 - tp1) * s < 0.75 * R:
            tp2 = c.entry + s * max(2.5 * R, abs(tp1 - c.entry) + R)
    return float(tp1), float(tp2), ob


# ------------------------------------------------------------------ confirmations
def confirmations(ctx: Context, c: Candidate, m, market: dict) -> list[dict]:
    s = c.sign
    up = s > 0
    out: list[dict] = []
    b = all_biases(ctx)
    if m.allows(c.direction):
        out.append({"key": "trend", "tf": "1d/4h/1h", "plain": "The bigger charts and today's 1-hour chart point " +
                    ("up" if up else "down"), "detail": f"MTF: D {b['1d'].direction}, 4H {b['4h'].direction}, 1H {b['1h'].direction}"})
    if b["15m"].sign == s:
        out.append({"key": "structure", "tf": "15m", "plain": "The 15-minute chart is making " +
                    ("higher lows" if up else "lower highs"), "detail": "; ".join(b["15m"].details)})
    d = ctx.main
    if len(d) >= 40:
        r = ind.rsi(d["close"]).iloc[-1]
        mh = ind.macd(d["close"])["macd_hist"].iloc[-1]
        if np.isfinite(r) and np.isfinite(mh):
            ok = (50 < r < 72 and mh > 0) if up else (28 < r < 50 and mh < 0)
            if ok:
                out.append({"key": "momentum", "tf": "15m", "plain": ("Buying" if up else "Selling") +
                            " pressure is building", "detail": f"RSI14 {r:.0f}, MACD hist {mh:+.6f}"})
    lv = nearest_label(key_levels(ctx), c.entry, 0.3 * ctx.atr15)
    if lv is not None and c.entry_type == "limit":
        out.append({"key": "level", "tf": "1h/15m", "plain": f"The entry is at {lv.label}",
                    "detail": f"{lv.kind} {lv.price:.5g} (strength {lv.strength})"})
    elif c.entry_type == "stop" and c.rng:
        out.append({"key": "level", "tf": "15m", "plain": f"A clear line to break: {c.level_label}",
                    "detail": f"range {c.rng['low']:.5g}-{c.rng['high']:.5g}"})
    pats = []
    for i in range(max(0, len(d) - 3), len(d)):
        pats += [n for n, dd in detect_at(d, i) if dd == ("bullish" if up else "bearish")]
    if pats:
        out.append({"key": "candles", "tf": "15m", "plain": "Recent 15-minute candles show strong " +
                    ("buying" if up else "selling"), "detail": ", ".join(sorted(set(pats)))})
    if c.entry_type == "stop" and c.setup in ("squeeze_breakout", "asian_range_breakout"):
        out.append({"key": "volatility", "tf": "15m", "plain": "The price has been unusually quiet: a big move often follows",
                    "detail": c.setup})
    elif c.entry_type == "limit" and market["state"] == ("trending_up" if up else "trending_down"):
        out.append({"key": "volatility", "tf": "15m", "plain": "The market is moving steadily in one direction",
                    "detail": f"ADX {market.get('adx')}"})
    sess = active_sessions(ctx.now)
    if "London" in sess or "New York" in sess:
        out.append({"key": "session", "tf": "", "plain": "It's a busy, reliable time of the trading day (" +
                    session_label(ctx.now) + ")", "detail": ",".join(sess)})
    if len(d) >= 60:
        lvls = liq.session_levels(d) + liq.equal_levels(d, zigzag(d.tail(300), 2.0))
        sw = [x for x in liq.sweeps(d.tail(300), lvls, lookback=12) if x.direction == ("down" if up else "up")]
        if sw:
            out.append({"key": "sweep", "tf": "15m", "plain": "The price briefly " + ("dipped below an earlier low" if up else
                        "poked above an earlier high") + " and snapped back", "detail": f"liquidity sweep of {sw[-1].level_kind}"})
    out += c.extra_confirmations
    seen, uniq = set(), []
    for x in out:
        if x["key"] not in seen:
            seen.add(x["key"])
            uniq.append(x)
    return uniq


# ------------------------------------------------------------------ evaluation of one candidate
def evaluate(ctx: Context, c: Candidate, m, market: dict, cfg) -> dict:
    tp1, tp2, obstacle = targets(ctx, c, cfg.min_rr)
    R = c.risk
    rr1 = abs(tp1 - c.entry) / R if R else 0.0
    rr2 = abs(tp2 - c.entry) / R if R else 0.0
    conf = confirmations(ctx, c, m, market)
    gates: list[dict] = []
    if not m.allows(c.direction):
        gates.append({"code": "mtf", "text": m.conflict or ("The bigger charts point the other way: no " +
                                                            DIR_WORD[c.direction].lower() + " against them.")})
    if len(conf) < cfg.min_confirmations:
        gates.append({"code": "confirmations", "text": f"Only {len(conf)} of the {cfg.min_confirmations} checks needed agree."})
    if R > MAX_STOP_ATR * ctx.atr15:
        gates.append({"code": "stop_too_wide", "text": "A safe stop loss would be too far away for a same-day trade."})
    if rr1 < cfg.min_rr - 1e-9:
        txt = (f"There isn't enough room: {obstacle['label']} at {fmt_price(ctx.symbol, obstacle['price'])} is in the way."
               if obstacle else f"The possible gain is less than {cfg.min_rr:g} times the risk.")
        gates.append({"code": "rr_too_low", "text": txt})
    if c.setup not in cfg.setups_enabled:
        gates.append({"code": "setup_disabled", "text": "This kind of setup is switched off in the settings."})
    elif not probability.setup_enabled(c.setup, ctx.symbol.ticker):
        gates.append({"code": "setup_disabled", "text": "Past tests showed this setup doesn't work well on this market. "
                      + probability.disabled_reason(c.setup, ctx.symbol.ticker)})
    score = 10 * len(conf) + 0.2 * abs(all_biases(ctx)["1h"].score) + 5 * min(rr1, 3)
    return {"candidate": c, "tp1": tp1, "tp2": tp2, "rr1": rr1, "rr2": rr2, "confirmations": conf, "gates": gates,
            "obstacle": obstacle, "score": round(score, 1)}


# ------------------------------------------------------------------ helpers
def _stale_data(ctx: Context, live_status: str | None) -> str | None:
    lb = ctx.last_bar_time
    if lb is None:
        return "No 15-minute price data is available."
    age = (ctx.now - (lb + timedelta(seconds=TF_SECONDS_MAIN))).total_seconds()
    if age > 2 * TF_SECONDS_MAIN:
        return f"The latest 15-minute candle is {age / 60:.0f} minutes late – the numbers may be out of date."
    if live_status in ("stale", "error"):
        return "The live price feed has stopped updating."
    return None


def _spread_gate(ctx: Context) -> dict | None:
    sp = ctx.spread
    if sp.pips is None or not ctx.pip:
        return None
    mx = ctx.cfg.max_spread_for(ctx.symbol.ticker)
    if sp.pips > mx:
        return {"code": "spread", "text": f"The broker's fee (spread) is high right now: {sp.pips:.1f} pips (max {mx:g})."}
    return None


def _minutes_text(ctx: Context, dist: float, prob: dict | None) -> str:
    if prob and prob.get("p25_minutes_to_tp1") and prob.get("p75_minutes_to_tp1"):
        return window_text(prob["p25_minutes_to_tp1"], prob["p75_minutes_to_tp1"]) + " (from past similar setups)"
    bars = max(1.0, dist / ctx.atr15) if ctx.atr15 else 1.0
    return window_text(15 * bars, 15 * (3 * bars + 4)) + " (rough estimate)"


def _range(ctx: Context, market: dict) -> dict | None:
    if market.get("range"):
        return market["range"]
    t = ctx.main.tail(32)
    if len(t) < 8:
        return None
    return {"low": float(t.low.min()), "high": float(t.high.max())}


def _scenarios(ctx: Context, rng: dict | None, m) -> list[dict]:
    if not rng:
        return []
    sym = ctx.symbol
    buf = 0.1 * ctx.atr15 + ctx.spread_price
    w = {"1d": 0.3, "4h": 0.3, "1h": 0.4}
    lean = sum(w[k] * m.biases[k].score for k in w if k in m.biases)
    up = int(min(70, max(30, round(50 + lean / 4))))
    if up >= 55:
        why = "the bigger charts are rising"
    elif up <= 45:
        why = "the bigger charts are falling"
    else:
        why = "the bigger charts don't lean either way"
    hi, lo = rng["high"] + buf, rng["low"] - buf
    return [
        {"direction": "long", "price": hi, "likely_pct": up, "entry_type": "stop",
         "text": f"Buy if it breaks above {fmt_price(sym, hi)}", "why": f"Up is {'more' if up > 50 else 'less' if up < 50 else 'as'} likely ({up}/{100 - up}) because {why}." if up != 50 else f"Both directions are equally likely because {why}."},
        {"direction": "short", "price": lo, "likely_pct": 100 - up, "entry_type": "stop",
         "text": f"Sell if it breaks below {fmt_price(sym, lo)}", "why": ""},
    ]


def _confidence(n_conf: int, rr: float, prob: dict | None, cfg) -> str:
    wr = (prob or {}).get("win_rate")
    if n_conf >= cfg.min_confirmations + 2 and rr >= 2 and (wr is None or wr >= 0.55):
        return "High"
    if n_conf >= cfg.min_confirmations and (wr is None or wr >= 0.45):
        return "Medium"
    return "Low"


def _prob_text(prob: dict | None) -> str:
    if not prob:
        return "No backtest yet – treat as unproven"
    return f"~{prob['win_rate'] * 100:.0f}% reached target 1 first ({prob['n']} similar past setups)"


# ------------------------------------------------------------------ the card
def build_card(ctx: Context, losses_today: int = 0, live_status: str | None = None) -> dict:
    cfg, sym, now = ctx.cfg, ctx.symbol, ctx.now
    if len(ctx.main) < 60:
        return pending_card(sym.ticker, now, "Not enough 15-minute price history to analyse yet.", error=True)
    biases = all_biases(ctx)
    b5 = tf_bias(ctx.df("5m"), "5m")
    m = mtf(biases)
    market = market_state(ctx.main, direction=biases["15m"].direction)
    price = ctx.last
    pip = ctx.pip
    dec = price_decimals(sym, price)

    common: list[dict] = []
    allowed, code, why = entries_allowed(now, sym, cfg)
    if not allowed:
        common.append({"code": code, "text": why})
    news = news_check(ctx.events, sym, now, cfg)
    if news["blocked"]:
        common.append({"code": "news", "text": news["block_text"]})
    sg = _spread_gate(ctx)
    if sg:
        common.append(sg)
    stale = _stale_data(ctx, live_status) if allowed or code != "market_closed" else None
    if stale:
        common.append({"code": "stale_data", "text": stale})
    if losses_today >= cfg.daily_loss_limit:
        common.append({"code": "daily_loss_limit", "text": f"{losses_today} trades hit their stop loss today – that's the "
                       "daily limit. No new trades until tomorrow."})

    cands = detect_all(ctx, None)
    evals = [evaluate(ctx, c, m, market, cfg) for c in cands]
    for e in evals:
        e["all_gates"] = common + e["gates"]
    evals.sort(key=lambda e: (len(e["all_gates"]) == 0, len(e["gates"]) == 0, e["score"]), reverse=True)
    best = evals[0] if evals else None
    passing = best is not None and not best["all_gates"]

    rng = _range(ctx, market)
    scenarios = _scenarios(ctx, rng, m)
    expires = min(now + timedelta(minutes=15 * cfg.expiry_bars), entry_cutoff(now, cfg)) if passing else now + timedelta(minutes=15)
    flat_by = flat_time(now, cfg)
    sess_ctx = {"session": session_key(now), "market": market["state"]}

    card: dict = {
        "version": CARD_VERSION, "mode": "intraday", "symbol": sym.ticker, "name": _name(sym), "is_fx": sym.is_fx,
        "pip_size": pip, "decimals": dec, "price": price, "price_text": fmt_price(sym, price),
        "generated_at": now.isoformat(timespec="seconds"), "expires_at": expires.isoformat(timespec="seconds"),
        "flat_by": flat_by.isoformat(timespec="seconds"),
        "no_entry_after": entry_cutoff(now, cfg).isoformat(timespec="seconds"),
        "last_bar": ctx.last_bar_time.isoformat() if ctx.last_bar_time else None,
        "market": market["state"], "market_text": MARKET_TEXT[market["state"]],
        "session": session_key(now), "session_label": session_label(now),
        "market_open": code != "market_closed",
        "range": rng if (market["state"] == "sideways" or not passing) else None,
        "scenarios": [], "probability": None, "size": None, "stale": False, "plan_id": None, "plan_state": None,
        "timezone": cfg.tz,
    }

    action, state, setup, direction = "WAIT", "waiting", None, None
    entry = entry_low = entry_high = stop = tp1 = tp2 = None
    entry_type = None
    prob = None
    ex: dict = {"glossary": GLOSSARY, "disclaimer": DISCLAIMER, "news_warning": news["warning"],
                "headline": "", "why": [], "waiting_for": [], "entry_text": "", "order_text": "", "stop_text": "",
                "stop_reason": "", "targets": [], "rr_text": "", "breakeven_text": "", "cancel": [], "time_stop_text": "",
                "probability_text": "", "time_window_text": "", "confidence_text": "", "size_text": "", "size_note": ""}
    conf_label = "Low"

    if best is not None:
        c = best["candidate"]
        setup, direction = c.setup, c.direction
        prob = probability.lookup(c.setup, sym.ticker, {**sess_ctx, "direction": c.direction})
        conf_label = _confidence(len(best["confirmations"]), best["rr1"], prob, cfg)

    if passing:
        c = best["candidate"]
        action = "BUY" if c.direction == "long" else "SELL"
        entry, entry_low, entry_high, stop = c.entry, c.entry_low, c.entry_high, c.stop
        tp1, tp2, entry_type = best["tp1"], best["tp2"], c.entry_type
        dist = abs(price - entry)
        ready_d = ready_distance(ctx)
        state = "ready" if dist <= ready_d else "waiting"
        et, ot = entry_text(sym, c.direction, c.entry_type, entry, entry_low, entry_high)
        be = entry + c.sign * cfg.breakeven_at_r * c.risk
        ex.update({
            "headline": (f"Get ready: {sym.ticker} is close to the entry. {et}." if state == "ready" else f"{et}."),
            "why": [x["plain"] + "." for x in best["confirmations"][:4]],
            "entry_text": et, "order_text": ot,
            "stop_text": f"{fmt_price(sym, stop)} ({fmt_distance(sym, entry, stop)})",
            "stop_reason": c.stop_reason[:1].upper() + c.stop_reason[1:] + ".",
            "targets": [{"label": "Target 1", "price": tp1, "text": f"{fmt_price(sym, tp1)} (+{fmt_distance(sym, entry, tp1)})"},
                        {"label": "Target 2", "price": tp2, "text": f"{fmt_price(sym, tp2)} (+{fmt_distance(sym, entry, tp2)})"}],
            "rr_text": rr_words(best["rr1"]) + " at target 1",
            "breakeven_text": f"When the price reaches {fmt_price(sym, be)} (+{cfg.breakeven_at_r:g} × your risk), move "
                              f"the stop loss to your entry {fmt_price(sym, entry)} – then the trade can't lose.",
            "cancel": [f"Cancel if a 15-minute candle closes {'below' if c.sign > 0 else 'above'} {fmt_price(sym, stop)} before you are in.",
                       f"Cancel if the order hasn't filled by {fmt_local(expires, cfg)}."]
                      + (["Cancel the pending order before the news: " + news["warning"]] if news["warning"] else []),
            "time_stop_text": f"Close the trade by {fmt_local(flat_by, cfg)} ({cfg.tz.split('/')[-1]} time) at the latest – "
                              "before the New York session ends. This is a same-day trade.",
            "time_window_text": _minutes_text(ctx, dist, prob),
            "probability_text": _prob_text(prob),
            "confidence_text": f"Confidence {conf_label.upper()} – {len(best['confirmations'])} checks agree",
        })
        verb = {("limit", 1): "come down", ("limit", -1): "come up", ("stop", 1): "rise", ("stop", -1): "fall"}
        ex["waiting_for"] = ([f"The price to {verb[(c.entry_type, c.sign)]} to {fmt_price(sym, entry)} – it's "
                              f"{fmt_distance(sym, price, entry)} away."] if dist > 0 else [])
        card.update({"ready_distance": ready_d, "breakeven_price": be, "rr1": round(best["rr1"], 2),
                     "rr2": round(best["rr2"], 2)})
    else:
        state = "market_closed" if code == "market_closed" else "waiting"
        reasons = [g["text"] for g in (best["all_gates"] if best else common)]
        if best is None:
            reasons.append("No clear trade setup on the 15-minute chart right now.")
        if code == "market_closed":
            rest = why.removeprefix("The market is closed. ")
            ex["headline"] = f"Market closed – {rest[:1].lower() + rest[1:]}"
        elif market["state"] == "sideways" and rng:
            ex["headline"] = (f"WAIT – stuck between {fmt_price(sym, rng['low'])} and {fmt_price(sym, rng['high'])}.")
        else:
            ex["headline"] = "WAIT – " + (reasons[0] if reasons else "no clear trade right now.")
        ex["why"] = _wait_why(ctx, m, market, rng)
        ex["waiting_for"] = reasons[:4]
        card["scenarios"] = scenarios
        if best is not None:
            c = best["candidate"]
            et, ot = entry_text(sym, c.direction, c.entry_type, c.entry, c.entry_low, c.entry_high)
            ex["closest_idea"] = f"Closest idea: {SETUP_NAME[c.setup].lower()} – {et[0].lower() + et[1:]}."
        ex["confidence_text"] = "No trade right now"
        ex["probability_text"] = _prob_text(prob) if best else ""
        if scenarios:
            ex["time_window_text"] = _minutes_text(ctx, min(abs(price - s["price"]) for s in scenarios), None)

    card.update({
        "action": action, "state": state, "setup": setup, "setup_name": SETUP_NAME.get(setup) if setup else None,
        "direction": direction if action != "WAIT" else None, "lean": direction,
        "entry": entry, "entry_low": entry_low, "entry_high": entry_high, "entry_type": entry_type,
        "stop": stop, "target1": tp1, "target2": tp2,
        "confidence": conf_label if action != "WAIT" else "Low",
        "probability": prob, "explanation": ex,
        "strength": round((1000 if action != "WAIT" else 0) + (500 if state == "ready" else 0) + (best["score"] if best else 0), 1),
        "spread": ctx.spread.as_dict(),
        "details": {
            "mtf": [{"tf": k, **v.as_dict()} for k, v in {**biases, "5m": b5}.items()],
            "mtf_rule": m.as_dict() | {"timeframes": None},
            "market": market,
            "confirmations": best["confirmations"] if best else [],
            "gates": best["all_gates"] if best else common,
            "candidates": [{"setup": e["candidate"].setup, "direction": e["candidate"].direction,
                            "entry_type": e["candidate"].entry_type, "entry": e["candidate"].entry,
                            "stop": e["candidate"].stop, "tp1": e["tp1"], "tp2": e["tp2"], "rr1": round(e["rr1"], 2),
                            "confirmations": len(e["confirmations"]), "score": e["score"],
                            "gates": [g["code"] for g in e["all_gates"]]} for e in evals[:6]],
            "levels": [l.as_dict() for l in sorted(key_levels(ctx), key=lambda l: abs(l.price - price))[:12]],
            "spread": ctx.spread.as_dict() | {"max": ctx.cfg.max_spread_for(sym.ticker)},
            "atr15": ctx.atr15, "atr15_pips": (ctx.atr15 / pip) if pip else None,
            "score": best["score"] if best else 0, "news": news, "config": cfg.as_dict(),
            "losses_today": losses_today,
        },
    })
    return card


def ready_distance(ctx: Context) -> float:
    return max(0.5 * ctx.atr15, 2 * ctx.spread_price)


def _wait_why(ctx: Context, m, market: dict, rng: dict | None) -> list[str]:
    sym = ctx.symbol
    out = []
    word = {1: "rising", -1: "falling", 0: "without a clear direction"}
    out.append(f"The big picture (daily and 4-hour charts) is {word[m.big_picture]}; today's 1-hour chart is {word[m.today]}.")
    if market["state"] == "sideways" and rng:
        out.append(f"On the 15-minute chart the price is moving sideways between {fmt_price(sym, rng['low'])} and "
                   f"{fmt_price(sym, rng['high'])}.")
    elif market["state"] != "sideways":
        out.append(f"The 15-minute chart is {MARKET_TEXT[market['state']].lower()}, but there is no good entry yet.")
    if m.conflict:
        out.append(m.conflict)
    return out[:4]


def _name(sym) -> str:
    try:
        from signals.service import display_name

        return display_name(sym)
    except Exception:
        return sym.ticker


def pending_card(ticker: str, now, message: str, error: bool = False) -> dict:
    """Placeholder while the first analysis runs (or when it can't run). Same keys as a real card."""
    return {"version": CARD_VERSION, "mode": "intraday", "symbol": ticker, "name": ticker, "action": "WAIT",
            "state": "pending" if not error else "waiting", "setup": None, "setup_name": None, "direction": None,
            "entry": None, "entry_low": None, "entry_high": None, "entry_type": None, "stop": None, "target1": None,
            "target2": None, "generated_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(minutes=15)).isoformat(timespec="seconds"), "market": "sideways",
            "market_text": "Sideways", "range": None, "scenarios": [], "probability": None, "size": None,
            "explanation": {"headline": message, "why": [], "waiting_for": [message], "disclaimer": DISCLAIMER,
                            "glossary": GLOSSARY, "cancel": [], "targets": []},
            "details": {}, "stale": True, "strength": -1, "error": message if error else None, "price": None,
            "decimals": 5, "pip_size": None, "confidence": "Low", "plan_id": None, "plan_state": None}

