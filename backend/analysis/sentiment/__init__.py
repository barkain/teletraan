"""Sentiment analysis package for market intelligence.

Provides text sentiment scoring via FinVADER/VADER, stock ticker extraction,
and aggregated per-symbol and market-wide sentiment computation.

Usage::

    from analysis.sentiment import get_symbol_sentiment, get_market_sentiment

    result = get_symbol_sentiment("AAPL", posts)
    market = get_market_sentiment(trending, posts_by_sub)
"""

from __future__ import annotations

import logging
from typing import Optional

from .scorer import SentimentScorer, get_sentiment_scorer

logger = logging.getLogger(__name__)

__all__ = [
    "SentimentScorer",
    "get_sentiment_scorer",
    "get_symbol_sentiment",
    "get_market_sentiment",
]


# =============================================================================
# Convenience functions
# =============================================================================


def get_symbol_sentiment(
    symbol: str,
    posts: list[dict],
    trending_rank: Optional[int] = None,
) -> dict:
    """Compute aggregated sentiment for a single symbol across posts.

    Delegates to :meth:`SentimentScorer.compute_symbol_sentiment` on the
    module-level singleton.

    Parameters
    ----------
    symbol:
        Stock ticker (e.g. ``"AAPL"``).
    posts:
        List of post dicts with text keys (``title``, ``text``, ``body``,
        ``selftext``) and optional ``score`` weight.
    trending_rank:
        Optional rank from ApeWisdom or similar trending source.

    Returns
    -------
    dict
        Keys: symbol, sentiment_score, post_count, bullish_count,
        bearish_count, neutral_count, confidence, trending_rank.
    """
    scorer = get_sentiment_scorer()
    return scorer.compute_symbol_sentiment(symbol, posts, trending_rank=trending_rank)


def get_market_sentiment(
    trending: list[dict],
    posts_by_sub: dict[str, list[dict]],
) -> dict:
    """Compute overall market mood from trending tickers and subreddit posts.

    Aggregates sentiment across all subreddits and trending tickers to
    produce a single market-level sentiment summary.

    Parameters
    ----------
    trending:
        List of trending ticker dicts.  Each should have at least a
        ``"ticker"`` or ``"symbol"`` key and optionally ``"rank"``.
    posts_by_sub:
        Mapping of subreddit name to list of post dicts (same format as
        accepted by :func:`get_symbol_sentiment`).

    Returns
    -------
    dict
        Keys: overall_score, overall_label, subreddit_scores,
        symbol_sentiments, post_count, bullish_pct, bearish_pct,
        neutral_pct.
    """
    scorer = get_sentiment_scorer()

    # ------------------------------------------------------------------
    # 1. Per-subreddit sentiment
    # ------------------------------------------------------------------
    subreddit_scores: dict[str, float] = {}
    all_scores: list[float] = []
    total_posts = 0

    for sub_name, posts in posts_by_sub.items():
        if not posts:
            continue
        batch_texts: list[str] = []
        for post in posts:
            parts: list[str] = []
            for key in ("title", "text", "body", "selftext"):
                val = post.get(key)
                if val and isinstance(val, str):
                    parts.append(val)
            combined = " ".join(parts)
            if combined.strip():
                batch_texts.append(combined)

        if not batch_texts:
            continue

        scores = scorer.score_batch(batch_texts)
        avg = sum(scores) / len(scores) if scores else 0.0
        subreddit_scores[sub_name] = round(avg, 4)
        all_scores.extend(scores)
        total_posts += len(scores)

    # ------------------------------------------------------------------
    # 2. Per-symbol sentiment for trending tickers
    # ------------------------------------------------------------------
    # Flatten all posts across subreddits for ticker matching
    all_posts: list[dict] = []
    for posts in posts_by_sub.values():
        all_posts.extend(posts)

    symbol_sentiments: list[dict] = []
    for item in trending:
        symbol = item.get("ticker") or item.get("symbol") or ""
        if not symbol:
            continue
        rank = item.get("rank")

        # Find posts mentioning this symbol
        matching_posts: list[dict] = []
        for post in all_posts:
            combined = " ".join(
                str(post.get(k, ""))
                for k in ("title", "text", "body", "selftext")
            )
            if symbol in combined or f"${symbol}" in combined:
                matching_posts.append(post)

        if matching_posts:
            sym_result = scorer.compute_symbol_sentiment(
                symbol, matching_posts, trending_rank=rank,
            )
            symbol_sentiments.append(sym_result)

    # ------------------------------------------------------------------
    # 3. Overall market aggregation
    # ------------------------------------------------------------------
    if all_scores:
        overall_score = round(sum(all_scores) / len(all_scores), 4)
    else:
        overall_score = 0.0

    bullish_count = sum(1 for s in all_scores if s > 0.05)
    bearish_count = sum(1 for s in all_scores if s < -0.05)
    neutral_count = len(all_scores) - bullish_count - bearish_count

    if total_posts > 0:
        bullish_pct = round(bullish_count / total_posts, 4)
        bearish_pct = round(bearish_count / total_posts, 4)
        neutral_pct = round(neutral_count / total_posts, 4)
    else:
        bullish_pct = 0.0
        bearish_pct = 0.0
        neutral_pct = 0.0

    # Assign a human-readable label
    if overall_score > 0.15:
        overall_label = "bullish"
    elif overall_score > 0.05:
        overall_label = "slightly_bullish"
    elif overall_score < -0.15:
        overall_label = "bearish"
    elif overall_score < -0.05:
        overall_label = "slightly_bearish"
    else:
        overall_label = "neutral"

    return {
        "overall_score": overall_score,
        "overall_label": overall_label,
        "subreddit_scores": subreddit_scores,
        "symbol_sentiments": symbol_sentiments,
        "post_count": total_posts,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "neutral_pct": neutral_pct,
    }
