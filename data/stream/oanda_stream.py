"""OANDA v20 pricing stream with automatic reconnect.

GET {stream}/v3/accounts/{id}/pricing/stream?instruments=EUR_USD,...  -> newline-delimited JSON:
  {"type":"PRICE","instrument":"EUR_USD","time":"...","bids":[{"price":"1.10275"}],"asks":[{"price":"1.10283"}],
   "tradeable":true}
  {"type":"HEARTBEAT","time":"..."}   (about every 5 s)
At most ~4 prices per second per instrument are sent. If nothing (not even a heartbeat) arrives for
READ_TIMEOUT seconds, the connection is considered dead and re-opened with exponential backoff.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from data.providers.oanda import OandaProvider, parse_time, ticker_from_instrument

log = logging.getLogger(__name__)
READ_TIMEOUT = 20.0


@dataclass
class Price:
    symbol: str      # 'EUR/USD'
    ts: float        # unix seconds
    bid: float
    ask: float
    tradeable: bool = True

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def parse_line(line: str | bytes) -> Price | str | None:
    """A PRICE message -> Price; a heartbeat -> 'heartbeat'; anything else -> None."""
    if not line:
        return None
    try:
        m = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if m.get("type") == "HEARTBEAT":
        return "heartbeat"
    if m.get("type") != "PRICE" or not m.get("bids") or not m.get("asks"):
        return None
    try:
        return Price(ticker_from_instrument(m["instrument"]), parse_time(m["time"]).timestamp(),
                     float(m["bids"][0]["price"]), float(m["asks"][0]["price"]), bool(m.get("tradeable", True)))
    except (KeyError, ValueError, IndexError):
        return None


def backoff_seconds(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    exp = min(cap, base * 2 ** attempt)
    return exp / 2 + random.random() * exp / 2


class OandaPriceStream:
    """Runs in its own thread. `on_price(Price)`; `on_status(state, detail)` with state in
    connecting | live | reconnecting | error. `open_lines` is injectable for tests."""

    def __init__(self, provider: OandaProvider, symbols: Iterable[str], on_price: Callable[[Price], None],
                 on_status: Callable[[str, str], None], open_lines: Callable[[list[str]], Iterable[str]] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.provider = provider
        self.symbols = sorted(set(symbols))
        self.on_price, self.on_status = on_price, on_status
        self._open = open_lines or self._http_lines
        self._sleep = sleep
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._thread: threading.Thread | None = None
        self.attempt = 0

    # ---------- transport ----------
    def _http_lines(self, instruments: list[str]) -> Iterable[str]:
        import httpx

        url = f"{self.provider.stream_host}/v3/accounts/{self.provider.account_id()}/pricing/stream"
        timeout = httpx.Timeout(connect=10.0, read=READ_TIMEOUT, write=10.0, pool=10.0)
        with httpx.Client(timeout=timeout) as client:
            with client.stream("GET", url, params={"instruments": ",".join(instruments)},
                               headers=self.provider.headers()) as r:
                if r.status_code in (401, 403):
                    raise PermissionError("OANDA rejected the token (check OANDA_API_TOKEN and OANDA_ENVIRONMENT)")
                r.raise_for_status()
                for line in r.iter_lines():
                    yield line

    # ---------- control ----------
    def set_symbols(self, symbols: Iterable[str]) -> None:
        new = sorted(set(symbols))
        if new != self.symbols:
            self.symbols = new
            self._restart.set()   # reconnect with the new instrument list

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="oanda-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._restart.set()

    def run(self) -> None:
        while not self._stop.is_set():
            if not self.symbols:
                self._sleep(1.0)
                continue
            self._restart.clear()
            self.on_status("connecting" if self.attempt == 0 else "reconnecting", "")
            try:
                got_data = False
                for line in self._open([s.replace("/", "_") for s in self.symbols]):
                    if self._stop.is_set() or self._restart.is_set():
                        break
                    p = parse_line(line)
                    if p is None:
                        continue
                    if not got_data:
                        got_data = True
                        self.attempt = 0
                        self.on_status("live", "")
                    if isinstance(p, Price):
                        self.on_price(p)
                if self._restart.is_set() and not self._stop.is_set():
                    continue          # symbol list changed: reconnect immediately
                raise ConnectionError("stream ended")
            except PermissionError as e:
                self.on_status("error", str(e))
                log.error("%s", e)
                self._sleep(300)      # a bad token won't fix itself quickly
            except Exception as e:  # network drop, timeout, server restart
                if self._stop.is_set():
                    break
                delay = backoff_seconds(self.attempt)
                self.attempt += 1
                self.on_status("reconnecting", f"{type(e).__name__}: {e}"[:200])
                log.warning("OANDA stream dropped (%s), reconnecting in %.1f s", e, delay)
                self._sleep(delay)
