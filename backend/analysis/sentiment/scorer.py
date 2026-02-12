"""SentimentScorer - Score text sentiment using VADER/FinVADER and extract stock tickers.

This module provides:
1. Text sentiment scoring via FinVADER (preferred) or VADER (fallback)
2. Stock ticker extraction from Reddit-style text with false-positive filtering
3. Aggregated per-symbol sentiment computation across multiple posts

Uses a singleton pattern consistent with the rest of the codebase.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FinVADER / VADER import with graceful fallback
# ---------------------------------------------------------------------------
try:
    from finvader import finvader  # type: ignore[import-untyped]

    _HAS_FINVADER = True
    _HAS_VADER = True
    logger.info("Using FinVADER for sentiment analysis")
except ImportError:
    _HAS_FINVADER = False
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import-untyped]

        _HAS_VADER = True
        logger.info("FinVADER not available, falling back to VADER")
    except ImportError:
        _HAS_VADER = False
        logger.warning(
            "Neither finvader nor vaderSentiment installed; "
            "sentiment scoring will return 0.0"
        )

# ---------------------------------------------------------------------------
# Common Reddit / finance abbreviations that are NOT stock tickers.
# Comprehensive set (~140 entries) to reduce false positives when extracting
# tickers from social-media text.
# ---------------------------------------------------------------------------
_FALSE_POSITIVE_TICKERS: set[str] = {
    # Reddit / internet slang
    "DD", "YOLO", "HODL", "FOMO", "LMAO", "LMFAO", "TLDR", "IMO", "IMHO",
    "IIRC", "TIL", "FYI", "AMA", "NSFW", "OP", "TBH", "SMH", "WTF", "OMG",
    "LOL", "ROFL", "STFU", "GTFO", "BTW", "IDK", "IRL", "AFAIK", "NGL",
    "DM", "PM", "PSA", "ICYMI", "ITT", "OOTL", "NTA", "YTA", "ELI5",
    # WallStreetBets / trading slang
    "WSB", "FD", "FDS", "MEME", "MOON", "MOONING", "PUMP", "DUMP", "DIP",
    "DIPS", "RIP", "GG", "APE", "APES", "BULL", "BEAR", "CALLS", "PUTS",
    "LONG", "SHORT", "BUY", "SELL", "HOLD", "GAIN", "LOSS", "TENDIES",
    "TENDIE", "STONK", "STONKS", "BAGS", "BAG", "SQUEEZE", "GAMMA", "THETA",
    "DELTA", "VEGA", "RHO", "ITM", "OTM", "ATM", "LEAPS",
    "DIAMOND", "PAPER", "HANDS", "YEET", "LFG", "WAGMI", "NGMI",
    # C-suite / corporate titles
    "CEO", "CFO", "COO", "CTO", "CIO", "CMO", "CSO",
    # Financial instrument / entity types
    "IPO", "SPAC", "ETF", "ETFS", "ETN", "REIT", "REITS", "NFT", "NFTS",
    "DAO", "DAOS",
    # Regulatory / government bodies
    "SEC", "FINRA", "FDIC", "FED", "FOMC", "DOJ", "IRS", "FDA", "CDC",
    "WHO", "NIH", "CMS", "DTCC",
    # Macroeconomic indicators
    "GDP", "CPI", "PPI", "PCE", "NFP", "PMI", "ISM",
    # Financial metrics & ratios
    "EPS", "PE", "PB", "PS", "PEG", "ROE", "ROA", "ROI", "ROIC",
    "EBITDA", "EBIT", "FCF", "DCF", "NAV", "BV", "TBV",
    # Options / technical analysis terms
    "IV", "OI", "DTE", "VOL", "HV", "RSI", "MACD", "SMA", "EMA",
    "VWAP", "TWAP", "TA", "FA",
    # Market reference points
    "ATH", "ATL", "HOD", "LOD", "EOD", "AH",
    # Exchanges
    "OTC", "NYSE", "NASDAQ", "AMEX", "CBOE", "CME", "ICE",
    # Major indices (ticker-like abbreviations)
    "DJIA", "SPX", "NDX", "VIX", "RUT",
    # Trading terminology
    "PT", "TP", "SL", "BE", "PL", "PNL",
    # Time-period abbreviations
    "YOY", "QOQ", "MOM", "TTM", "FY", "CY",
    # Deal types
    "LBO", "MBO", "DPO",
    # Accounting / compliance
    "GAAP", "IFRS", "SOX", "KYC", "AML",
    # Common short English words that appear in all-caps
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "HAS", "HIS", "HOW", "ITS", "MAY", "NEW",
    "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "HIT", "LET", "SAY",
    "SHE", "TOO", "USE", "DAD", "MOM", "RUN", "BIG", "TOP", "LOW", "HIGH",
    "UP", "SO", "IF", "OR", "NO", "GO", "DO", "MY", "AN", "AT", "BY", "IS",
    "IT", "OF", "ON", "TO", "WE", "HE", "IN", "BE", "AS", "AI", "ML", "US",
    "UK", "EU", "UN", "YES", "OK",
    "JUST", "LIKE", "NEXT", "LAST", "EDIT", "POST", "LINK", "DONE", "GOOD",
    "BEST", "REAL", "HUGE", "MEGA", "RISK", "FREE", "SAFE", "EASY", "HARD",
    "MOVE", "PLAY", "CALL", "PUT", "WAIT", "WEEK", "YEAR", "ZERO", "HALF",
    "BOTH", "EACH", "MANY", "MUCH", "SOME", "THAN", "THEM", "THEN", "THIS",
    "THAT", "VERY", "WHAT", "WHEN", "WILL", "WITH", "ALSO", "BACK", "BEEN",
    "COME", "EVEN", "FIND", "FROM", "GIVE", "HAVE", "HERE", "KNOW", "LOOK",
    "MAKE", "MORE", "MOST", "ONLY", "OVER", "SAME", "TAKE", "TELL", "WANT",
    "WELL", "WERE", "WORK", "STILL", "SUCH", "DOWN", "AFTER", "THINK",
    # Misc
    "TBA", "TBD", "ASAP", "FAQ", "DIY", "API", "ETA", "GM", "GN",
}

# ---------------------------------------------------------------------------
# Ticker regex patterns
# ---------------------------------------------------------------------------
_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_BARE_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")


# =============================================================================
# SentimentScorer
# =============================================================================


class SentimentScorer:
    """Score text sentiment using FinVADER (preferred) or VADER (fallback).

    Also provides ticker extraction from Reddit-style text and aggregated
    per-symbol sentiment computation.
    """

    def __init__(self) -> None:
        self._vader_analyzer: Optional[object] = None
        if not _HAS_FINVADER and _HAS_VADER:
            self._vader_analyzer = SentimentIntensityAnalyzer()  # type: ignore[name-defined]

    # ------------------------------------------------------------------
    # Sentiment scoring
    # ------------------------------------------------------------------

    def score_text(self, text: str) -> float:
        """Return compound sentiment score in [-1.0, +1.0].

        Uses FinVADER with SentiBigNomics + Henry lexicons when available,
        otherwise falls back to standard VADER.  Returns 0.0 if neither
        library is installed.
        """
        if not text or not text.strip():
            return 0.0

        try:
            if _HAS_FINVADER:
                return float(
                    finvader(text, use_sentibignomics=True, use_henry=True)  # type: ignore[name-defined]
                )
            if _HAS_VADER and self._vader_analyzer is not None:
                scores = self._vader_analyzer.polarity_scores(text)  # type: ignore[union-attr]
                return float(scores["compound"])
        except Exception:
            logger.exception("Sentiment scoring failed for text: %.80s...", text)

        return 0.0

    def score_batch(self, texts: list[str]) -> list[float]:
        """Score multiple texts efficiently.

        Returns a list of compound sentiment scores, one per input text.
        """
        return [self.score_text(t) for t in texts]

    # ------------------------------------------------------------------
    # Ticker extraction
    # ------------------------------------------------------------------

    def extract_tickers(self, text: str) -> list[str]:
        """Extract stock tickers from Reddit-style text.

        Two patterns are recognised (in priority order):
        1. **High confidence** -- ``$AAPL`` (dollar-sign prefix)
        2. **Medium confidence** -- ``AAPL`` (bare all-caps 2-5 letter word)

        Common Reddit/finance abbreviations are filtered out to reduce
        false positives.  Results are deduplicated and returned in the
        order they first appear.
        """
        seen: set[str] = set()
        tickers: list[str] = []

        # High-confidence: $TICKER
        for match in _DOLLAR_TICKER_RE.finditer(text):
            ticker = match.group(1)
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

        # Medium-confidence: bare ALL-CAPS words (filtered)
        for match in _BARE_TICKER_RE.finditer(text):
            candidate = match.group(1)
            if candidate not in seen and candidate not in _FALSE_POSITIVE_TICKERS:
                seen.add(candidate)
                tickers.append(candidate)

        return tickers

    # ------------------------------------------------------------------
    # Aggregated symbol sentiment
    # ------------------------------------------------------------------

    def compute_symbol_sentiment(
        self,
        symbol: str,
        posts: list[dict],
        trending_rank: Optional[int] = None,
    ) -> dict:
        """Aggregate sentiment for *symbol* across a list of posts.

        Each post dict should contain at least a ``"text"`` or ``"body"``
        key.  An optional ``"score"`` key (e.g. Reddit upvotes) is used as
        a weight when computing the weighted average sentiment.

        Parameters
        ----------
        symbol:
            The stock ticker to compute sentiment for.
        posts:
            List of post dicts.  Recognised text keys: ``title``, ``text``,
            ``body``, ``selftext``.  Weight key: ``score``.
        trending_rank:
            Optional rank from ApeWisdom or similar trending source.

        Returns
        -------
        dict
            Keys: symbol, sentiment_score, post_count, bullish_count,
            bearish_count, neutral_count, confidence, trending_rank.
        """
        empty_result: dict = {
            "symbol": symbol,
            "sentiment_score": 0.0,
            "post_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "confidence": 0.0,
            "trending_rank": trending_rank,
        }

        if not posts:
            return empty_result

        scores: list[float] = []
        weights: list[float] = []
        bullish = 0
        bearish = 0
        neutral = 0

        for post in posts:
            # Combine all available text fields
            parts: list[str] = []
            for key in ("title", "text", "body", "selftext"):
                val = post.get(key)
                if val and isinstance(val, str):
                    parts.append(val)
            combined_text = " ".join(parts)
            if not combined_text.strip():
                continue

            score = self.score_text(combined_text)
            scores.append(score)

            # Use Reddit score (upvotes) as weight; floor at 1
            weight = max(float(post.get("score", 1) or 1), 1.0)
            weights.append(weight)

            # Classify post direction
            if score > 0.05:
                bullish += 1
            elif score < -0.05:
                bearish += 1
            else:
                neutral += 1

        post_count = len(scores)
        if post_count == 0:
            return empty_result

        # Weighted average sentiment
        total_weight = sum(weights)
        weighted_sentiment = (
            sum(s * w for s, w in zip(scores, weights)) / total_weight
            if total_weight > 0
            else 0.0
        )

        # Confidence = proportion of posts agreeing with majority direction
        majority = max(bullish, bearish, neutral)
        confidence = majority / post_count

        return {
            "symbol": symbol,
            "sentiment_score": round(weighted_sentiment, 4),
            "post_count": post_count,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "confidence": round(confidence, 4),
            "trending_rank": trending_rank,
        }


# =============================================================================
# Singleton
# =============================================================================

_scorer_instance: Optional[SentimentScorer] = None


def get_sentiment_scorer() -> SentimentScorer:
    """Return the module-level ``SentimentScorer`` singleton."""
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = SentimentScorer()
    return _scorer_instance
