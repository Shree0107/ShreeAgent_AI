"""PlanService: runs the engine for symbols, keeps each plan's state up to date, stores and publishes the cards.

  refresh(symbols)        fetch data -> engine -> reconcile with the open plan -> store -> publish plan:{SYM}
  on_price(ticker, t, p)  live price -> state machine of the open plan -> publish plan:{SYM} + plan_event
  cards(symbols)          stored cards (instant), each flagged `stale` when older than one 15M candle

Bus topics: plan:{SYM} (the full card) and plan_event {kind, symbol, setup, direction, state, price, entry, stop,
target1, target2, plan_id, at, message} for kind in get_ready, entry_triggered, breakeven_set, tp_hit, sl_hit,
breakeven, time_stop, cancelled, expired (phase 10 turns these into alerts).
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone

import pandas as pd

from data.symbols import Symbol, parse_symbol, resolve
from intraday.config import IntradayConfig, from_settings
from intraday.context import TFS, Spread, build_context
from intraday.history import PlanStore
from intraday.news import load_events
from intraday.plan import build_card, pending_card
from intraday.state import ACTIVE_STATES, STATE_TEXT, Bar, Event, PlanState, advance, from_dict, tick
from signals.market import fmt_distance, fmt_price, pip_size

log = logging.getLogger(__name__)
STALE_AFTER_S = 15 * 60 + 60          # one 15M candle (+1 min for the refresh to finish)


def _sym(t: str) -> Symbol:
    return parse_symbol(t) or resolve(t)


def is_stale(card: dict | None, now: datetime) -> bool:
    if not card or not card.get("generated_at"):
        return True
    try:
        gen = datetime.fromisoformat(card["generated_at"])
    except ValueError:
        return True
    return (now - gen).total_seconds() > STALE_AFTER_S


def event_message(card: dict, ev: Event, sym: Symbol) -> str:
    t = card["symbol"]
    p = lambda x: fmt_price(sym, x)  # noqa: E731
    w = "Buy" if card.get("direction") == "long" else "Sell"
    return {
        "get_ready": f"Get ready: {t} is close to the entry. {card['explanation'].get('entry_text', '')}.",
        "entry_triggered": f"{t}: entry triggered at {p(ev.price)} ({w}). Stop loss {p(card.get('stop'))}, "
                           f"target 1 {p(card.get('target1'))}.",
        "breakeven_set": f"{t}: the trade is up {card.get('details', {}).get('config', {}).get('breakeven_at_r', 1):g}× the "
                         f"risk – move your stop loss to the entry {p(ev.price)} (break-even).",
        "tp_hit": f"{t}: target {ev.target} reached at {p(ev.price)}.",
        "sl_hit": f"{t}: stop loss hit at {p(ev.price)}. The trade is closed.",
        "breakeven": f"{t}: closed at break-even ({p(ev.price)}).",
        "time_stop": f"{t}: time stop – close the trade now ({p(ev.price)}), the trading day is ending.",
        "cancelled": f"{t}: the plan is cancelled – {ev.reason or 'conditions changed'}. Delete any pending order.",
        "expired": f"{t}: the plan expired without an entry – delete any pending order.",
    }.get(ev.kind, f"{t}: {ev.kind}")


def plan_state_from_card(card: dict) -> PlanState:
    return PlanState(card["direction"], card["entry_type"], card["entry"], card["stop"], card["target1"], card["target2"],
                     datetime.fromisoformat(card["expires_at"]), datetime.fromisoformat(card["flat_by"]),
                     card.get("ready_distance") or 0.0,
                     (card.get("details") or {}).get("config", {}).get("breakeven_at_r", 1.0),
                     state="waiting", history=[("waiting", card["generated_at"])])


HEADLINE = {
    "triggered": "Entry triggered – you're in the trade.",
    "in_trade": "In trade.",
    "tp1_hit": "Target 1 reached – the rest runs to target 2 with the stop at the entry.",
    "tp2_hit": "Target 2 reached – trade finished. ✅",
    "sl_hit": "Stop loss hit – trade closed. Losses are part of trading; stick to the plan.",
    "breakeven": "Closed at break-even – no loss.",
    "time_stop": "Closed by the time stop at the end of the trading day.",
    "cancelled": "Plan cancelled – delete any pending order.",
    "expired": "Plan expired without an entry – delete any pending order.",
}


def apply_state(card: dict, ps: PlanState, plan_id: int | None, sym: Symbol) -> dict:
    c = copy.deepcopy(card)
    c["state"] = ps.state
    c["state_text"] = STATE_TEXT.get(ps.state, ps.state)
    c["plan_id"] = plan_id
    c["plan_state"] = ps.as_dict()
    if ps.closed:
        c["closed"] = True
    ex = c["explanation"]
    if ps.state in HEADLINE and not (ps.state == "tp1_hit" and ps.closed):
        ex["headline"] = HEADLINE[ps.state]
    elif ps.state == "tp1_hit":
        ex["headline"] = "Target 1 reached, then the rest closed at break-even. ✅"
    if ps.state == "ready" and "Get ready" not in ex.get("headline", ""):
        ex["headline"] = f"Get ready: {c['symbol']} is close to the entry. {ex.get('entry_text', '')}."
    if ps.be_moved and not ps.closed:
        ex["stop_text"] = f"{fmt_price(sym, ps.stop_now)} (moved to your entry: break-even)"
    if ps.state in ACTIVE_STATES and ps.fill is not None:
        ex["waiting_for"] = [f"In the trade since {ps.triggered_at:%H:%M} UTC at {fmt_price(sym, ps.fill)}."]
    if ps.state in ("ready",):
        c["strength"] = max(c.get("strength") or 0, 1500)
    if ps.state in ACTIVE_STATES:
        c["strength"] = 2000 + (c.get("strength") or 0) % 1000
    return c


class PlanService:
    def __init__(self, data=None, store: PlanStore | None = None, cfg: IntradayConfig | None = None,
                 events_fn=None, live_fn=None, bus=None, clock=None):
        self._data = data
        self.store = store or PlanStore()
        self.cfg = cfg or from_settings()
        self.events_fn = events_fn          # (symbol, now) -> [CalendarEvent]; default: data/providers/calendar
        self.live_fn = live_fn              # () -> LiveService | None
        self.bus = bus
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_run: dict[str, dict] = {}   # ticker -> {"price", "atr", "at"} (big-move trigger)

    @property
    def data(self):
        if self._data is None:
            from data.service import get_data_service

            self._data = get_data_service()
        return self._data

    def live(self):
        if self.live_fn is not None:
            return self.live_fn()
        from data.stream.live import get_live

        return get_live()

    # ---------- inputs ----------
    def frames(self, sym: Symbol) -> dict[str, pd.DataFrame]:
        out = {}
        for tf in TFS:
            try:
                out[tf] = self.data.get_ohlcv(sym, tf)
            except Exception as e:
                log.info("No %s data for %s: %s", tf, sym.ticker, e)
        return out

    def live_state(self, sym: Symbol):
        lv = self.live()
        if not lv:
            return None
        try:
            return lv.states.get(sym.ticker)
        except Exception:
            return None

    def spread(self, sym: Symbol) -> Spread:
        if not pip_size(sym):
            return Spread(None, False, "Stocks: no spread check (the spread is part of the share price)")
        st = self.live_state(sym)
        if st is not None and st.spread_pips is not None and st.source == "oanda":
            return Spread(float(st.spread_pips), True, "live spread from OANDA")
        typ = self.cfg.typical_spread_for(sym.ticker)
        return Spread(typ, False, f"No live spread available – using the typical {typ:g} pips (set TYPICAL_SPREAD_PIPS)")

    def events(self, sym: Symbol, now: datetime) -> list:
        if self.events_fn is not None:
            return self.events_fn(sym, now)
        return load_events(sym, now, self.data)

    # ---------- analysis ----------
    def analyse(self, sym: Symbol, now: datetime | None = None, frames: dict | None = None) -> dict:
        now = now or self.clock()
        frames = frames if frames is not None else self.frames(sym)
        st = self.live_state(sym)
        price = st.mid if (st is not None and st.mid and st.status in ("live", "delayed")) else None
        ctx = build_context(sym, frames, now, self.cfg, self.spread(sym), self.events(sym, now), price)
        if len(ctx.main) < 60:
            return pending_card(sym.ticker, now, "Not enough 15-minute price history to analyse this market.", error=True)
        card = build_card(ctx, self.store.losses_today(now, self.cfg.tz), st.status if st is not None else None)
        card["data_status"] = st.status if st is not None else None
        card["price_source"] = (st.source if st is not None and price is not None else "last 15-minute close")
        self.last_run[sym.ticker] = {"price": ctx.last, "atr": ctx.atr15, "at": now}
        return card

    def refresh(self, symbols: list[str], now: datetime | None = None) -> list[dict]:
        out = []
        for tk in symbols:
            try:
                out.append(self.refresh_one(_sym(tk), now))
            except Exception as e:
                log.warning("Plan for %s failed: %s", tk, e)
                out.append(pending_card(tk, now or self.clock(), f"Analysis failed: {e}", error=True))
        return out

    def refresh_one(self, sym: Symbol, now: datetime | None = None) -> dict:
        now = now or self.clock()
        frames = self.frames(sym)
        self.catch_up(sym, frames.get("5m"), now)
        card = self.analyse(sym, now, frames)
        card = self.reconcile(sym, card, now)
        self.store.save_latest(card)
        self._publish_card(card)
        return card

    # ---------- plans ----------
    def catch_up(self, sym: Symbol, m5: pd.DataFrame | None, now: datetime) -> None:
        """Replay completed 5M bars the open plan hasn't seen (e.g. when no live price feed was running)."""
        op = self.store.open_plan(sym.ticker)
        if not op or m5 is None or m5.empty:
            return
        ps = from_dict(op["state_json"])
        since = ps.checked_at or datetime.fromisoformat(op["created_at"])
        idx = m5.index if m5.index.tz is not None else m5.index.tz_localize("UTC")
        ends = idx + pd.Timedelta(minutes=5)
        sel = m5[(ends > pd.Timestamp(since)) & (ends <= pd.Timestamp(now))]
        evs: list[Event] = []
        for ts, r in sel.iterrows():
            t_close = (ts + pd.Timedelta(minutes=5)).to_pydatetime()
            # cancel rule is about 15M closes: only bars that end a 15M candle count as closed bars for it
            evs += advance(ps, Bar(t_close, r.open, r.high, r.low, r.close, closed_bar=t_close.minute % 15 == 0))
            if ps.closed:
                break
        if evs:
            self._apply(op, ps, evs, sym)

    def reconcile(self, sym: Symbol, card: dict, now: datetime) -> dict:
        op = self.store.open_plan(sym.ticker)
        if op:
            ps = from_dict(op["state_json"])
            if ps.state in ACTIVE_STATES:          # in a trade: keep showing the trade, with fresh market info
                base = op["card"] or card
                merged = copy.deepcopy(base)
                for k in ("generated_at", "price", "price_text", "market", "market_text", "session", "session_label",
                          "data_status", "price_source", "market_open", "spread"):
                    if k in card:
                        merged[k] = card[k]
                merged["explanation"]["news_warning"] = card["explanation"].get("news_warning")
                merged["analysis_now"] = {"action": card["action"], "headline": card["explanation"]["headline"]}
                return apply_state(merged, ps, op["id"], sym)
            same = (card["action"] in ("BUY", "SELL") and card["setup"] == op["setup_type"]
                    and card["direction"] == op["direction"]
                    and abs(card["entry"] - op["entry"]) <= 0.25 * ((card.get("details") or {}).get("atr15") or 0))
            if same:                               # same idea, levels refreshed; keep its state and history
                for k, ck in (("entry", "entry"), ("stop", "stop"), ("tp1", "target1"), ("tp2", "target2")):
                    setattr(ps, k, card[ck])
                ps.expires_at = datetime.fromisoformat(card["expires_at"])
                ps.ready_distance = card.get("ready_distance") or ps.ready_distance
                self.store.update(op["id"], ps, pip_size(sym), card)
                self._tick_now(op["id"], ps, card, sym, now)
                return apply_state(card, ps, op["id"], sym)
            reason = ("a newer plan replaced it" if card["action"] in ("BUY", "SELL") else
                      ((card["details"].get("gates") or [{}])[0].get("text") or "conditions changed").rstrip("."))
            ps.state, ps.closed_at, ps.done = "cancelled", now, True
            ps.history.append(("cancelled", now.isoformat()))
            ev = Event("cancelled", "cancelled", now, card.get("price"), reason=reason)
            self._apply(op, ps, [ev], sym)
        if card["action"] in ("BUY", "SELL"):
            ps = plan_state_from_card(card)
            pid = self.store.create(card, ps, (card.get("spread") or {}).get("pips"))
            card = apply_state(card, ps, pid, sym)
            self.store.update(pid, ps, pip_size(sym), card)
            return self._tick_now(pid, ps, card, sym, now) or card
        return card

    def _tick_now(self, pid: int, ps: PlanState, card: dict, sym: Symbol, now: datetime) -> dict | None:
        """Apply the current price at once (a new plan may already be 'ready')."""
        price = card.get("price")
        if price is None:
            return None
        evs = tick(ps, now, price)
        if not evs:
            return None
        op = self.store.get(pid)
        op["card"] = card
        return self._apply(op, ps, evs, sym)

    def _apply(self, op: dict, ps: PlanState, evs: list[Event], sym: Symbol) -> dict:
        card = apply_state(op["card"], ps, op["id"], sym) if op.get("card") else None
        spread = None
        if any(e.kind == "entry_triggered" for e in evs):
            spread = self.spread(sym).pips
        self.store.update(op["id"], ps, pip_size(sym), card, spread_at_entry=spread)
        if card is not None:
            latest = self.store.latest(sym.ticker)
            if latest is None or latest.get("plan_id") in (None, op["id"]):
                self.store.save_latest(card)
                self._publish_card(card)
        for e in evs:
            payload = {"kind": e.kind, "symbol": sym.ticker, "setup": op.get("setup_type"), "direction": op.get("direction"),
                       "state": e.state, "price": e.price, "target": e.target, "entry": ps.entry, "stop": ps.stop,
                       "target1": ps.tp1, "target2": ps.tp2, "plan_id": op["id"], "at": e.at.isoformat(),
                       "message": event_message(card or {"symbol": sym.ticker, "explanation": {}, "direction": op.get("direction"),
                                                         "stop": ps.stop, "target1": ps.tp1}, e, sym)}
            if e.kind == "get_ready" and card is not None:
                payload["distance"] = fmt_distance(sym, e.price or ps.entry, ps.entry)
            self.store.add_event(op["id"], sym.ticker, e.kind, payload["at"], payload)
            if self.bus:
                self.bus.publish("plan_event", payload)
        return card or {}

    def on_price(self, ticker: str, t: datetime, price: float) -> list[Event]:
        op = self.store.open_plan(ticker)
        if not op:
            return []
        ps = from_dict(op["state_json"])
        evs = tick(ps, t, price)
        if evs:
            self._apply(op, ps, evs, _sym(ticker))
        return evs

    def big_move(self, ticker: str, price: float) -> bool:
        lr = self.last_run.get(ticker)
        return bool(lr and lr.get("atr") and abs(price - lr["price"]) > lr["atr"])

    # ---------- reading ----------
    def cards(self, symbols: list[str], now: datetime | None = None) -> tuple[list[dict], list[str]]:
        """(cards, tickers needing a refresh). Never runs the engine."""
        now = now or self.clock()
        out, todo = [], []
        for tk in symbols:
            c = self.store.latest(tk)
            if c is None:
                out.append(pending_card(tk, now, "Analysing for the first time…"))
                todo.append(tk)
                continue
            c["stale"] = is_stale(c, now)
            if c["stale"]:
                todo.append(tk)
            out.append(c)
        return out, todo

    def _publish_card(self, card: dict) -> None:
        if self.bus:
            from api.serialize import clean

            self.bus.publish(f"plan:{card['symbol']}", clean(card))
