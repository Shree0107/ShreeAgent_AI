"""LiveService: keeps prices and current candles up to date for every symbol someone is looking at.

Sources, per symbol:
  * forex/metals with OANDA_API_TOKEN -> OANDA pricing stream (real time, bid/ask, spread)   status "live"
  * everything else                   -> polling the 1-minute bars (Yahoo; often ~15 min late) status "delayed"
Events published on the bus:
  price:{SYM}          {symbol, bid, ask, mid, spread_pips, ts, source, status}
  candle:{SYM}:{TF}    {symbol, tf, bar, closed}            (updates throttled to 4/s per candle)
  candle_closed        {symbol, tf, bar}                    (for the analysis worker)
  resync:{SYM}         {symbol, reason}                     (after a reconnect: clients reload history)
  status               {feeds, symbols}                     (whenever a status changes)
Staleness: no price for STALE_AFTER_SECONDS while the market is open -> status "stale"; when the market is
closed -> "closed". Clients must never show a stale price as live.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field

import pandas as pd

from config.settings import get_settings
from data.providers.base import TF_SECONDS
from data.stream.aggregator import CandleAggregator, bucket_start
from data.stream.market_hours import market_open
from data.symbols import Symbol, parse_symbol
from signals.market import pip_size

log = logging.getLogger(__name__)
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d", "1wk")
THROTTLE_S = 0.25


@dataclass
class SymbolState:
    symbol: str
    source: str = ""
    status: str = "starting"   # starting | live | delayed | stale | closed | error
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    ts: float | None = None
    spread_pips: float | None = None
    detail: str = ""
    agg: CandleAggregator = field(default_factory=lambda: CandleAggregator(TIMEFRAMES), repr=False)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("agg", None)
        d["age_s"] = None if self.ts is None else round(time.time() - self.ts, 1)
        return d


def candles_from_minutes(m1: pd.DataFrame, tf: str, now_bucket_only: bool = True) -> dict | None:
    """Current candle of timeframe `tf` rebuilt from 1-minute bars (used by the polling feed)."""
    if m1 is None or m1.empty:
        return None
    last_ts = m1.index[-1].timestamp()
    start = bucket_start(last_ts, tf)
    part = m1[m1.index >= pd.Timestamp(start, unit="s", tz="UTC")]
    if part.empty:
        return None
    return {"time": start, "open": float(part["open"].iloc[0]), "high": float(part["high"].max()),
            "low": float(part["low"].min()), "close": float(part["close"].iloc[-1]),
            "volume": float(part["volume"].sum())}


class LiveService:
    def __init__(self, bus, data=None, oanda=None, clock=time.time):
        s = get_settings()
        self.bus = bus
        self._data = data
        self.clock = clock
        self.poll_seconds = s.live_poll_seconds
        self.stale_after = s.stale_after_seconds
        self.states: dict[str, SymbolState] = {}
        self.syms: dict[str, Symbol] = {}
        self.feeds: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._last_pub: dict[tuple[str, str], float] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.oanda = oanda
        if self.oanda is None and s.oanda_api_token:
            from data.providers.oanda import OandaProvider

            self.oanda = OandaProvider()
        self.stream = None

    @property
    def data(self):
        if self._data is None:
            from data.service import get_data_service

            self._data = get_data_service()
        return self._data

    # ---------- symbols ----------
    def streams(self, sym: Symbol) -> bool:
        return bool(self.oanda and self.oanda.configured and sym.is_fx)

    def ensure(self, ticker: str) -> SymbolState | None:
        """Start tracking a symbol (idempotent). Returns its state, or None for an unknown ticker."""
        sym = parse_symbol(ticker)
        if not sym:
            return None
        with self._lock:
            if sym.ticker in self.states:
                return self.states[sym.ticker]
            st = SymbolState(sym.ticker, source="oanda" if self.streams(sym) else "poll")
            self.states[sym.ticker] = st
            self.syms[sym.ticker] = sym
        self._seed(sym, st)
        if self.stream is not None and self.streams(sym):
            self.stream.set_symbols([t for t, s in self.syms.items() if self.streams(s)])
        self._publish_status()
        return st

    def _seed(self, sym: Symbol, st: SymbolState) -> None:
        """Start each timeframe's candle from the provider's latest bar, so live updates continue it."""
        for tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
            try:
                df = self.data.get_ohlcv(sym, tf)
                if len(df):
                    b = df.iloc[-1]
                    t = int(df.index[-1].timestamp())
                    if t == bucket_start(self.clock(), tf):   # only seed a candle that is still open
                        st.agg.seed(tf, {"time": t, "open": b.open, "high": b.high, "low": b.low,
                                         "close": b.close, "volume": b.volume})
            except Exception as e:
                log.debug("seed %s %s: %s", sym.ticker, tf, e)

    # ---------- price input ----------
    def on_price(self, symbol: str, ts: float, bid: float | None, ask: float | None, mid: float | None = None,
                 source: str = "oanda") -> None:
        with self._lock:
            st = self.states.get(symbol) or self.ensure(symbol)
            if st is None:
                return
            sym = self.syms[symbol]
            mid = mid if mid is not None else (bid + ask) / 2
            st.bid, st.ask, st.mid, st.ts, st.source = bid, ask, mid, ts, source
            pip = pip_size(sym)
            st.spread_pips = round((ask - bid) / pip, 2) if (pip and bid is not None and ask is not None) else None
            new_status = "live" if source == "oanda" else "delayed"
            changed = st.status != new_status
            st.status = new_status
            events = st.agg.on_tick(ts, mid)
        self.bus.publish(f"price:{symbol}", st.public())
        self._emit(symbol, events)
        if changed:
            self._publish_status()

    def on_bar(self, symbol: str, tf: str, bar: dict, source: str) -> None:
        """Polling path: the provider's current candle for a timeframe (already aggregated)."""
        self._throttled_candle(symbol, tf, bar, closed=False)

    def _emit(self, symbol: str, events: list[tuple[str, str, dict]]) -> None:
        for kind, tf, bar in events:
            if kind == "closed":
                self.bus.publish(f"candle:{symbol}:{tf}", {"symbol": symbol, "tf": tf, "bar": bar, "closed": True})
                self.bus.publish("candle_closed", {"symbol": symbol, "tf": tf, "bar": bar})
            else:
                self._throttled_candle(symbol, tf, bar, closed=False)

    def _throttled_candle(self, symbol: str, tf: str, bar: dict, closed: bool) -> None:
        now = time.monotonic()
        key = (symbol, tf)
        if not closed and now - self._last_pub.get(key, 0) < THROTTLE_S:
            return
        self._last_pub[key] = now
        self.bus.publish(f"candle:{symbol}:{tf}", {"symbol": symbol, "tf": tf, "bar": bar, "closed": closed})

    # ---------- status ----------
    def on_feed_status(self, feed: str, state: str, detail: str = "") -> None:
        prev = self.feeds.get(feed, {}).get("state")
        self.feeds[feed] = {"state": state, "detail": detail, "since": self.clock()}
        if prev in ("reconnecting", "connecting") and state == "live":
            # Back after a gap: tell clients to reload history so missed candles are filled in.
            for t, s in self.syms.items():
                if feed == "oanda" and self.streams(s):
                    self.bus.publish(f"resync:{t}", {"symbol": t, "reason": "reconnected"})
        self._publish_status()

    def check_staleness(self) -> None:
        now = self.clock()
        changed = False
        with self._lock:
            for t, st in self.states.items():
                sym = self.syms[t]
                is_open = market_open(sym.market, sym.is_fx, pd.Timestamp(now, unit="s", tz="UTC").to_pydatetime())
                if st.source == "oanda" and self.feeds.get("oanda", {}).get("state") == "error":
                    new = "error"
                elif is_open is False:
                    new = "closed"
                elif st.ts is None or now - st.ts > self.stale_after * (1 if st.source == "oanda" else 20):
                    # Polled prices are minutes old by nature; only call them stale when far behind.
                    new = "stale" if st.ts is not None else st.status
                else:
                    new = "live" if st.source == "oanda" else "delayed"
                if new != st.status:
                    st.status, changed = new, True
                for kind, tf, bar in st.agg.close_due(now):
                    self._emit(t, [(kind, tf, bar)])
        if changed:
            self._publish_status()

    def status(self) -> dict:
        with self._lock:
            return {"feeds": dict(self.feeds), "symbols": {t: s.public() for t, s in self.states.items()},
                    "oanda_configured": bool(self.oanda and self.oanda.configured)}

    def _publish_status(self) -> None:
        self.bus.publish("status", self.status())

    def current_bar(self, ticker: str, tf: str) -> dict | None:
        st = self.states.get(ticker)
        return st.agg.current(tf) if st else None

    # ---------- polling (symbols without a stream) ----------
    def poll_once(self) -> None:
        for t, sym in list(self.syms.items()):
            if self.streams(sym):
                continue
            try:
                m1 = self.data.get_ohlcv(sym, "1m")
            except Exception as e:
                st = self.states[t]
                st.detail = str(e)[:200]
                continue
            if m1 is None or m1.empty:
                continue
            last = m1.iloc[-1]
            ts = m1.index[-1].timestamp() + 59   # the 1m bar's close time
            st = self.states[t]
            fresh = st.ts is None or ts > st.ts
            with self._lock:
                st.mid, st.bid, st.ask, st.ts, st.source = float(last.close), None, None, ts, "yfinance"
                st.spread_pips = None
                if st.status in ("starting", "stale"):
                    st.status = "delayed"
            if fresh:
                self.bus.publish(f"price:{t}", st.public())
            for tf in TIMEFRAMES:
                bar = candles_from_minutes(m1, tf)
                if bar:
                    self.on_bar(t, tf, bar, "yfinance")

    # ---------- lifecycle ----------
    def start(self, symbols: list[str] = ()) -> None:
        for t in symbols:
            self.ensure(t)
        if self.oanda and self.oanda.configured:
            from data.stream.oanda_stream import OandaPriceStream

            fx = [t for t, s in self.syms.items() if self.streams(s)]
            self.stream = OandaPriceStream(
                self.oanda, fx,
                on_price=lambda p: self.on_price(p.symbol, p.ts, p.bid, p.ask, source="oanda"),
                on_status=lambda state, detail: self.on_feed_status("oanda", state, detail))
            self.stream.start()
        else:
            self.feeds["oanda"] = {"state": "off", "detail": "OANDA_API_TOKEN not set: forex prices are delayed",
                                   "since": self.clock()}
        self._spawn(self._poll_loop, "live-poll")
        self._spawn(self._watch_loop, "live-watch")

    def _spawn(self, fn, name: str) -> None:
        th = threading.Thread(target=fn, name=name, daemon=True)
        th.start()
        self._threads.append(th)

    def _poll_loop(self) -> None:
        self.feeds["poll"] = {"state": "live", "detail": f"every {self.poll_seconds}s", "since": self.clock()}
        try:
            self.poll_once()          # first prices right away, not after one interval
            self.check_staleness()
        except Exception:
            log.exception("first poll failed")
        while not self._stop.wait(self.poll_seconds):
            try:
                self.poll_once()
            except Exception:
                log.exception("poll failed")

    def _watch_loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.check_staleness()
            except Exception:
                log.exception("staleness check failed")

    def stop(self) -> None:
        self._stop.set()
        if self.stream:
            self.stream.stop()


_live: LiveService | None = None


def get_live() -> LiveService | None:
    return _live


def set_live(svc: LiveService | None) -> None:
    global _live
    _live = svc


def tf_seconds(tf: str) -> int:
    return TF_SECONDS[tf]
