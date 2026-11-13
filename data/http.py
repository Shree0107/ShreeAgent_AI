"""Shared HTTP helper: per-provider rate limiting + retry with exponential backoff."""
from __future__ import annotations

import logging
import threading
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Non-retryable provider failure (bad key, unknown symbol, plan limits)."""


class TransientProviderError(ProviderError):
    """Retryable failure (HTTP 429/5xx, timeouts)."""


class RateLimiter:
    """Minimum spacing between calls, per provider."""

    def __init__(self, calls_per_minute: float):
        self.interval = 60.0 / calls_per_minute if calls_per_minute > 0 else 0
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


_limiters: dict[str, RateLimiter] = {}
_session = requests.Session()
_session.headers["User-Agent"] = "ShreeAgentAI/1.0"


def limiter(provider: str, calls_per_minute: float) -> RateLimiter:
    if provider not in _limiters:
        _limiters[provider] = RateLimiter(calls_per_minute)
    return _limiters[provider]


@retry(
    retry=retry_if_exception_type(TransientProviderError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def get_json(url: str, params: dict | None = None, provider: str = "http", cpm: float = 60, timeout: float = 20):
    limiter(provider, cpm).wait()
    try:
        r = _session.get(url, params=params, timeout=timeout)
    except (requests.Timeout, requests.ConnectionError) as e:
        raise TransientProviderError(f"{provider}: network error {e}") from e
    if r.status_code == 429 or r.status_code >= 500:
        log.warning("%s returned HTTP %s, retrying", provider, r.status_code)
        raise TransientProviderError(f"{provider}: HTTP {r.status_code}")
    if r.status_code in (401, 403):
        raise ProviderError(f"{provider}: unauthorized (HTTP {r.status_code}), check the API key in .env")
    if r.status_code >= 400:
        raise ProviderError(f"{provider}: HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as e:
        raise ProviderError(f"{provider}: invalid JSON response") from e
