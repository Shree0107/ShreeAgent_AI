"""News sentiment. Uses provider sentiment when available (Marketaux), otherwise FinBERT, then a lexicon fallback."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from config.settings import get_settings
from data.providers.base import NewsItem
from data.symbols import Symbol

log = logging.getLogger(__name__)

_POS = {"beat", "beats", "surge", "surges", "rally", "rallies", "gain", "gains", "upgrade", "upgraded", "record", "strong",
        "growth", "bullish", "outperform", "profit", "rise", "rises", "jumps", "soar", "soars", "hawkish", "higher", "buy"}
_NEG = {"miss", "misses", "plunge", "plunges", "fall", "falls", "drop", "drops", "downgrade", "downgraded", "weak", "loss",
        "bearish", "underperform", "cut", "cuts", "lawsuit", "probe", "slump", "slumps", "decline", "declines", "dovish",
        "lower", "sell", "fraud", "default", "recession"}


@dataclass
class SentimentReport:
    symbol: str
    score: float  # -1..1
    label: str
    n_articles: int
    method: str
    headlines: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def lexicon_score(text: str) -> float:
    words = re.findall(r"[a-z]+", text.lower())
    p = sum(w in _POS for w in words)
    n = sum(w in _NEG for w in words)
    return 0.0 if p + n == 0 else (p - n) / (p + n)


@lru_cache(maxsize=1)
def _finbert():
    from transformers import pipeline

    return pipeline("text-classification", model="ProsusAI/finbert", truncation=True, top_k=None)


def finbert_scores(texts: list[str]) -> list[float]:
    clf = _finbert()
    out = []
    for res in clf(texts, batch_size=8):
        probs = {r["label"].lower(): r["score"] for r in res}
        out.append(probs.get("positive", 0) - probs.get("negative", 0))
    return out


def score_items(items: list[NewsItem]) -> tuple[list[float], str]:
    if not items:
        return [], "none"
    method = "provider"
    scores: list[float | None] = [i.sentiment for i in items]
    missing = [k for k, s in enumerate(scores) if s is None]
    if missing:
        texts = [f"{items[k].title}. {items[k].summary[:300]}" for k in missing]
        filled = None
        if get_settings().sentiment_model == "finbert":
            try:
                filled = finbert_scores(texts)
                method = "finbert" if len(missing) == len(items) else "provider+finbert"
            except Exception as e:
                log.info("FinBERT unavailable (%s), using lexicon", e)
        if filled is None:
            filled = [lexicon_score(t) for t in texts]
            method = "lexicon" if len(missing) == len(items) else "provider+lexicon"
        for k, v in zip(missing, filled):
            scores[k] = v
    return [float(s) for s in scores], method


def analyse_news(symbol: Symbol, days: int = 7, data=None) -> SentimentReport:
    from data.service import get_data_service

    data = data or get_data_service()
    try:
        items = data.get_news(symbol, days=days)
    except Exception as e:
        log.warning("News fetch failed: %s", e)
        items = []
    scores, method = score_items(items)
    avg = round(sum(scores) / len(scores), 3) if scores else 0.0
    label = "positive" if avg > 0.15 else "negative" if avg < -0.15 else "neutral"
    heads = [
        {"title": i.title, "source": i.source, "date": i.published.date().isoformat(), "url": i.url, "sentiment": round(s, 2)}
        for i, s in zip(items, scores)
    ]
    return SentimentReport(symbol.ticker, avg, label, len(items), method, heads[:12])
