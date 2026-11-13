"""Optional LLM wording polish for the explanation sentences, with the numbers locked.

The LLM receives only the finished template sentences and returns reworded ones. A sentence's
rewrite is accepted only if it contains exactly the same numbers (same values, same count) and no
technical jargon. Anything else falls back to the template text. Prices, stops and targets are never
sent through this step.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

JARGON = re.compile(r"\b(RSI|MACD|ATR|EMA|SMA|ADX|VWAP|Fibonacci|Bollinger|stochastic|oscillator|R:R)\b", re.I)
_NUM = re.compile(r"\d+(?:[.,]\d+)*")

SYSTEM = (
    "You rewrite short trading-analysis sentences for complete beginners. Make each one clearer and friendlier, "
    "at most 25 words. Rules: keep EVERY number exactly as written (same digits, same decimals); add no new "
    "numbers, dates or facts; don't use technical terms (RSI, MACD, ATR, moving average names, Fibonacci); don't "
    "give advice beyond what the sentence says. Reply with ONLY a JSON array of strings, same length and order."
)


def numbers(text: str) -> Counter:
    return Counter(n.replace(",", "") for n in _NUM.findall(text))


def accept(original: str, rewrite: object) -> bool:
    if not isinstance(rewrite, str) or not rewrite.strip():
        return False
    if numbers(original) != numbers(rewrite):
        return False
    if JARGON.search(rewrite) and not JARGON.search(original):
        return False
    return len(rewrite) <= max(220, 2 * len(original))


def guard(originals: list[str], rewrites: object) -> list[str]:
    """Per-sentence: the rewrite if it passes `accept`, else the original."""
    if not isinstance(rewrites, list) or len(rewrites) != len(originals):
        return list(originals)
    return [r.strip() if accept(o, r) else o for o, r in zip(originals, rewrites)]


def _parse(text: str) -> object:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def polish(texts: list[str], provider=None, model: str | None = None, cache=None) -> list[str]:
    """Return polished texts (or the originals on any failure). Results are cached for a week."""
    texts = [t for t in texts]
    if not texts:
        return texts
    from config.settings import get_settings

    s = get_settings()
    key = "polish:" + hashlib.sha256(json.dumps(texts).encode()).hexdigest()[:32]
    if cache is None:
        from data.cache import get_cache

        cache = get_cache()
    hit = cache.get(key)
    if hit is not None:
        return guard(texts, hit)
    try:
        if provider is None:
            from agent.agent import make_provider

            provider = make_provider()
        res = provider.run(SYSTEM, [{"role": "user", "content": json.dumps(texts, ensure_ascii=False)}], [],
                           lambda n, a: ("no tools", True), model=model or s.llm_model, max_steps=1)
        out = guard(texts, _parse(res.text))
        cache.set(key, out, 7 * 24 * 3600)
        return out
    except Exception as e:
        log.info("Wording polish skipped: %s", e)
        return texts
