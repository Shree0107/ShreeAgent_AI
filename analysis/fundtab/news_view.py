"""News feed with sentiment dots and optional AI one-line summaries.

The LLM only rewords headlines. A summary is kept only if every number in it also appears in its headline
(the number-guard idea from signals/polish.py), it adds no jargon, and it is short. Anything else is dropped,
and the headline is shown on its own. Without a configured LLM there are no summaries, and the UI says so.
"""
from __future__ import annotations

import hashlib
import json
import logging

from signals.polish import JARGON, _parse, numbers

log = logging.getLogger(__name__)

SYSTEM = (
    "You explain financial news headlines to complete beginners. For each headline write ONE plain sentence "
    "(at most 22 words) saying what it is about and why it may matter for the given market. Rules: use NO "
    "numbers, dates or percentages that are not written in that headline; add no facts that are not in it; no "
    "jargon; no advice. Reply with ONLY a JSON array of strings, same length and order as the input."
)
CACHE_TTL = 24 * 3600


def llm_configured() -> bool:
    from config.settings import get_settings

    s = get_settings()
    if s.llm_provider == "anthropic":
        return bool(s.anthropic_api_key)
    if s.llm_provider == "openai_compat":
        return bool(s.openai_base_url or s.openai_api_key)
    return False


def summary_ok(headline: str, summary: object) -> bool:
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 200:
        return False
    have, used = numbers(headline), numbers(summary)
    if any(used[n] > have[n] for n in used):  # a number the headline doesn't contain
        return False
    return not (JARGON.search(summary) and not JARGON.search(headline))


def guard_summaries(headlines: list[str], summaries: object) -> list[str | None]:
    if not isinstance(summaries, list) or len(summaries) != len(headlines):
        return [None] * len(headlines)
    return [s.strip() if summary_ok(h, s) else None for h, s in zip(headlines, summaries)]


def summarise(symbol_ticker: str, headlines: list[str], provider=None, cache=None) -> dict:
    """{'enabled', 'summaries': [str|None per headline], 'note'}."""
    if not headlines:
        return {"enabled": llm_configured() or provider is not None, "summaries": [], "note": "No headlines."}
    if provider is None and not llm_configured():
        return {"enabled": False, "summaries": [None] * len(headlines),
                "note": "AI summaries are off (set ANTHROPIC_API_KEY in .env to turn them on). Headlines are shown as they are."}
    if cache is None:
        from data.cache import get_cache

        cache = get_cache()
    key = "fund:newssum:" + hashlib.sha256(json.dumps([symbol_ticker, headlines]).encode()).hexdigest()[:32]
    hit = cache.get(key)
    if hit is not None:
        return {"enabled": True, "summaries": guard_summaries(headlines, hit), "note": "", "cached": True}
    try:
        from config.settings import get_settings

        if provider is None:
            from agent.agent import make_provider

            provider = make_provider()
        msg = json.dumps({"market": symbol_ticker, "headlines": headlines}, ensure_ascii=False)
        res = provider.run(SYSTEM, [{"role": "user", "content": msg}], [], lambda n, a: ("no tools", True),
                           model=get_settings().llm_model, max_steps=1)
        out = guard_summaries(headlines, _parse(res.text))
        cache.set(key, out, CACHE_TTL)
        dropped = sum(s is None for s in out)
        note = f"{dropped} summary(ies) failed the number check and were hidden." if dropped else ""
        return {"enabled": True, "summaries": out, "note": note, "cached": False}
    except Exception as e:
        log.info("News summaries skipped: %s", e)
        return {"enabled": True, "summaries": [None] * len(headlines), "note": f"AI summaries unavailable right now ({e})."}


def news_feed(symbol, data, days: int = 7) -> dict:
    from analysis.sentiment import analyse_news

    rep = analyse_news(symbol, days=days, data=data)
    heads = []
    for h in rep.headlines:
        s = h["sentiment"]
        heads.append({**h, "label": "positive" if s > 0.15 else "negative" if s < -0.15 else "neutral"})
    return {"symbol": symbol.ticker, "label": rep.label, "score": rep.score, "n_articles": rep.n_articles,
            "method": rep.method, "headlines": heads}
