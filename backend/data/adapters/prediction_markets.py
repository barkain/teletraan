"""Unified prediction market aggregator combining Polymarket + Kalshi.

Fetches from both platforms in parallel, merges and deduplicates results,
and provides a single interface for macro prediction data.  Gracefully
degrades when one (or both) sources are unavailable.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from data.adapters.kalshi import get_kalshi_adapter  # type: ignore[import-not-found]
from data.adapters.polymarket import get_polymarket_adapter  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Aggregator-level TTL cache (separate from individual adapter caches)
# ---------------------------------------------------------------------------
_agg_cache: dict[str, tuple[float, Any]] = {}
_AGG_CACHE_TTL = 1800  # 30 minutes


def _get_agg_cached(key: str) -> Any | None:
    """Return cached value if within TTL, else None."""
    if key in _agg_cache:
        ts, data = _agg_cache[key]
        if time.time() - ts < _AGG_CACHE_TTL:
            return data
        del _agg_cache[key]
    return None


def _set_agg_cache(key: str, data: Any) -> None:
    """Store a value in the aggregator TTL cache."""
    _agg_cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "fed": [
        "fed", "fomc", "rate decision", "rate cut", "rate hike",
        "basis point", "federal reserve", "interest rate",
        "fed rate cuts", "fed funds rate", "rate cuts in 202",
    ],
    "recession": [
        "recession", "economic downturn", "contraction",
        "us recession", "recession in 202",
    ],
    "inflation": [
        "inflation", "cpi", "consumer price", "price index",
        "cpi year", "cpi above", "inflation above", "inflation rate",
    ],
    "sp500": [
        "s&p 500", "s&p500", "sp500", "spy", "spx",
        "sp500 above", "sp500 below", "s&p above",
    ],
    "gdp": [
        "gdp", "gross domestic product", "economic growth",
        "gdp growth", "gdp above", "gdp below",
    ],
}


def _classify_polymarket_event(question: str) -> str | None:
    """Classify a Polymarket event question into a category.

    Returns one of the category keys or None if unclassifiable.
    """
    q_lower = question.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                return category
    return None


def _extract_probability_from_outcome_prices(market: dict[str, Any]) -> float | None:
    """Extract the 'Yes' probability from Polymarket outcome_prices.

    outcome_prices can be a JSON string like '["0.72","0.28"]' or a list.
    The first element corresponds to the 'Yes' outcome.
    """
    prices = market.get("outcome_prices")
    if prices is None:
        return None

    if isinstance(prices, str):
        # Parse JSON-ish string: '["0.72","0.28"]'
        try:
            import json
            prices = json.loads(prices)
        except (ValueError, TypeError):
            return None

    if isinstance(prices, list) and len(prices) > 0:
        try:
            return float(prices[0])
        except (TypeError, ValueError):
            return None

    return None


def _normalize_title(title: str) -> str:
    """Lowercase and strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9\s]", "", title.lower()).strip()


def _are_similar_events(title_a: str, title_b: str) -> bool:
    """Check whether two event titles are similar enough to be deduplicated.

    Uses token overlap: if >=60% of the shorter title's tokens appear in
    the longer title, consider them similar.
    """
    norm_a = set(_normalize_title(title_a).split())
    norm_b = set(_normalize_title(title_b).split())

    if not norm_a or not norm_b:
        return False

    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    overlap = len(shorter & longer)
    return overlap / len(shorter) >= 0.60


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class PredictionMarketAggregator:
    """Unified prediction market aggregator for Polymarket + Kalshi.

    Fetches from both platforms in parallel using ``asyncio.gather`` with
    ``return_exceptions=True`` so that one source failing does not prevent
    the other from returning data.
    """

    def __init__(self) -> None:
        self._polymarket = get_polymarket_adapter()
        self._kalshi = get_kalshi_adapter()

    # ------------------------------------------------------------------
    # Core fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_both(self) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        """Fetch data from both platforms in parallel.

        Returns:
            Tuple of (polymarket_data, kalshi_data).
            Either may be empty dicts/lists on failure.
        """
        poly_result, kalshi_result = await asyncio.gather(
            self._polymarket.get_relevant_predictions(),
            self._kalshi.get_all_economic_markets(),
            return_exceptions=True,
        )

        if isinstance(poly_result, BaseException):
            logger.error("Polymarket fetch failed: %s", poly_result)
            poly_result = {"finance": [], "economy": []}

        if isinstance(kalshi_result, BaseException):
            logger.error("Kalshi fetch failed: %s", kalshi_result)
            kalshi_result = {}

        return poly_result, kalshi_result

    # ------------------------------------------------------------------
    # Kalshi helpers — extract structured data from series markets
    # ------------------------------------------------------------------

    @staticmethod
    def _kalshi_fed_probabilities(fed_markets: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract Fed rate probabilities from Kalshi FED series markets.

        Attempts to find markets representing hold / cut / hike and
        organises them by meeting date.
        """
        if not fed_markets:
            return {}

        # Group by close_time (proxy for meeting date)
        by_date: dict[str, list[dict[str, Any]]] = {}
        for m in fed_markets:
            close = m.get("close_time", "unknown")
            by_date.setdefault(close, []).append(m)

        # Take the nearest meeting (earliest close_time)
        sorted_dates = sorted(by_date.keys())
        if not sorted_dates:
            return {}

        nearest_date = sorted_dates[0]
        nearest_markets = by_date[nearest_date]

        probabilities: dict[str, float] = {}
        for m in nearest_markets:
            title_lower = m["title"].lower()
            prob = m.get("probability", 0.0)
            if "hold" in title_lower or "unchanged" in title_lower or "no change" in title_lower:
                probabilities["hold"] = prob
            elif "cut" in title_lower or "decrease" in title_lower or "lower" in title_lower:
                # Try to find basis points
                bp_match = re.search(r"(\d+)\s*(?:bp|basis)", title_lower)
                key = f"cut_{bp_match.group(1)}bp" if bp_match else "cut_25bp"
                probabilities[key] = probabilities.get(key, 0.0) + prob
            elif "hike" in title_lower or "increase" in title_lower or "raise" in title_lower or "higher" in title_lower:
                bp_match = re.search(r"(\d+)\s*(?:bp|basis)", title_lower)
                key = f"hike_{bp_match.group(1)}bp" if bp_match else "hike_25bp"
                probabilities[key] = probabilities.get(key, 0.0) + prob
            else:
                # Generic entry using title fragment
                probabilities[m["ticker"]] = prob

        return {
            "next_meeting": {
                "date": nearest_date,
                "probabilities": probabilities,
            },
            "total_markets": len(fed_markets),
        }

    @staticmethod
    def _kalshi_sp500_targets(sp500_markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract S&P 500 target probabilities from Kalshi SP500 series."""
        targets: list[dict[str, Any]] = []
        for m in sp500_markets:
            level_match = re.search(r"(\d[,\d]*)", m.get("title", ""))
            level = int(level_match.group(1).replace(",", "")) if level_match else None
            targets.append({
                "level": level,
                "probability": m.get("probability", 0.0),
                "title": m.get("title", ""),
                "ticker": m.get("ticker", ""),
            })
        # Sort by level descending
        targets.sort(key=lambda t: t.get("level") or 0, reverse=True)
        return targets

    @staticmethod
    def _kalshi_category_probability(markets: list[dict[str, Any]], keywords: list[str] | None = None) -> float | None:
        """Average probability across a list of Kalshi markets, optionally filtered by keywords."""
        if not markets:
            return None
        subset = markets
        if keywords:
            subset = [m for m in markets if any(kw in m.get("title", "").lower() for kw in keywords)]
        if not subset:
            subset = markets
        probs = [m.get("probability", 0.0) for m in subset]
        return sum(probs) / len(probs) if probs else None

    # ------------------------------------------------------------------
    # Polymarket helpers
    # ------------------------------------------------------------------

    def _poly_events_by_category(self, poly_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Classify Polymarket events into categories.

        Returns a dict mapping category -> list of market dicts.
        """
        categorised: dict[str, list[dict[str, Any]]] = {}
        all_events = list(poly_data.get("finance", [])) + list(poly_data.get("economy", []))

        for event in all_events:
            question = event.get("question", "")
            cat = _classify_polymarket_event(question)
            if cat:
                categorised.setdefault(cat, []).append(event)

        return categorised

    @staticmethod
    def _poly_fed_probabilities(fed_events: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract Fed rate probabilities from Polymarket events."""
        if not fed_events:
            return {}

        probabilities: dict[str, float] = {}
        for event in fed_events:
            question_lower = event.get("question", "").lower()
            prob = _extract_probability_from_outcome_prices(event)
            if prob is None:
                continue
            if "hold" in question_lower or "unchanged" in question_lower:
                probabilities["hold"] = prob
            elif "cut" in question_lower or "lower" in question_lower:
                probabilities["cut_25bp"] = prob
            elif "hike" in question_lower or "raise" in question_lower:
                probabilities["hike_25bp"] = prob

        return {"probabilities": probabilities} if probabilities else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_macro_predictions(self) -> dict[str, Any]:
        """Get aggregated macro predictions from both platforms.

        Returns a dict with keys: fed_rates, recession, inflation, sp500, gdp.
        Each sub-dict includes source attribution and fetch timestamp.
        If both sources fail, returns an empty dict.
        """
        cached = _get_agg_cached("macro_predictions")
        if cached is not None:
            return cached

        poly_data, kalshi_data = await self._fetch_both()

        if not poly_data.get("finance") and not poly_data.get("economy") and not kalshi_data:
            return {}

        now_iso = datetime.now(timezone.utc).isoformat()
        poly_by_cat = self._poly_events_by_category(poly_data)

        # --- Fed rates ---
        kalshi_fed = self._kalshi_fed_probabilities(kalshi_data.get("fed", []))
        poly_fed = self._poly_fed_probabilities(poly_by_cat.get("fed", []))

        fed_rates: dict[str, Any] = {}
        if kalshi_fed and poly_fed.get("probabilities"):
            # Merge: average common keys
            merged_probs = dict(kalshi_fed.get("next_meeting", {}).get("probabilities", {}))
            for key, val in poly_fed.get("probabilities", {}).items():
                if key in merged_probs:
                    merged_probs[key] = (merged_probs[key] + val) / 2.0
                else:
                    merged_probs[key] = val
            fed_rates = {
                "next_meeting": {
                    "date": kalshi_fed.get("next_meeting", {}).get("date", ""),
                    "probabilities": merged_probs,
                },
                "source": "kalshi+polymarket",
                "fetched_at": now_iso,
            }
        elif kalshi_fed:
            fed_rates = {
                "next_meeting": kalshi_fed.get("next_meeting", {}),
                "source": "kalshi",
                "fetched_at": now_iso,
            }
        elif poly_fed.get("probabilities"):
            fed_rates = {
                "next_meeting": {"date": "", "probabilities": poly_fed["probabilities"]},
                "source": "polymarket",
                "fetched_at": now_iso,
            }

        # --- Recession ---
        recession: dict[str, Any] = {}
        poly_recession = poly_by_cat.get("recession", [])
        if poly_recession:
            probs = [_extract_probability_from_outcome_prices(e) for e in poly_recession]
            valid_probs = [p for p in probs if p is not None]
            if valid_probs:
                recession = {
                    "probability_2026": sum(valid_probs) / len(valid_probs),
                    "source": "polymarket",
                    "fetched_at": now_iso,
                }

        # --- Inflation ---
        inflation: dict[str, Any] = {}
        kalshi_cpi = kalshi_data.get("cpi", [])
        if kalshi_cpi:
            above_3_markets = [m for m in kalshi_cpi if "above" in m.get("title", "").lower() or "over" in m.get("title", "").lower() or "3" in m.get("title", "")]
            if above_3_markets:
                avg_prob = sum(m.get("probability", 0.0) for m in above_3_markets) / len(above_3_markets)
                inflation = {
                    "cpi_above_3pct": avg_prob,
                    "source": "kalshi",
                    "fetched_at": now_iso,
                }
            else:
                # Use general CPI probability
                avg_prob = sum(m.get("probability", 0.0) for m in kalshi_cpi) / len(kalshi_cpi)
                inflation = {
                    "cpi_average_probability": avg_prob,
                    "source": "kalshi",
                    "fetched_at": now_iso,
                }
        # Supplement with Polymarket if Kalshi has nothing
        if not inflation:
            poly_inflation = poly_by_cat.get("inflation", [])
            if poly_inflation:
                probs = [_extract_probability_from_outcome_prices(e) for e in poly_inflation]
                valid_probs = [p for p in probs if p is not None]
                if valid_probs:
                    inflation = {
                        "cpi_above_3pct": sum(valid_probs) / len(valid_probs),
                        "source": "polymarket",
                        "fetched_at": now_iso,
                    }

        # --- S&P 500 ---
        sp500: dict[str, Any] = {}
        kalshi_sp = kalshi_data.get("sp500", [])
        if kalshi_sp:
            sp500 = {
                "targets": self._kalshi_sp500_targets(kalshi_sp),
                "source": "kalshi",
                "fetched_at": now_iso,
            }

        # --- GDP ---
        gdp: dict[str, Any] = {}
        kalshi_gdp = kalshi_data.get("gdp", [])
        if kalshi_gdp:
            positive_markets = [m for m in kalshi_gdp if "positive" in m.get("title", "").lower() or "above" in m.get("title", "").lower() or "growth" in m.get("title", "").lower()]
            if positive_markets:
                avg_prob = sum(m.get("probability", 0.0) for m in positive_markets) / len(positive_markets)
            else:
                avg_prob = sum(m.get("probability", 0.0) for m in kalshi_gdp) / len(kalshi_gdp)
            gdp = {
                "q1_positive": avg_prob,
                "source": "kalshi",
                "fetched_at": now_iso,
            }

        result: dict[str, Any] = {}
        if fed_rates:
            result["fed_rates"] = fed_rates
        if recession:
            result["recession"] = recession
        if inflation:
            result["inflation"] = inflation
        if sp500:
            result["sp500"] = sp500
        if gdp:
            result["gdp"] = gdp

        if result:
            _set_agg_cache("macro_predictions", result)

        return result

    async def get_fed_consensus(self) -> dict[str, Any]:
        """Get combined Fed rate probabilities from both sources.

        When both sources provide Fed data, averages their probabilities.
        When only one provides data, uses it directly.

        Returns:
            Dict with 'probabilities', 'sources', 'fetched_at'.
            Empty dict if no Fed data available.
        """
        cached = _get_agg_cached("fed_consensus")
        if cached is not None:
            return cached

        kalshi_fed_task = self._kalshi.get_fed_markets()
        poly_search_task = self._polymarket.search_markets("Fed rate")

        kalshi_fed_raw, poly_fed_raw = await asyncio.gather(
            kalshi_fed_task,
            poly_search_task,
            return_exceptions=True,
        )

        if isinstance(kalshi_fed_raw, BaseException):
            logger.error("Kalshi Fed fetch failed: %s", kalshi_fed_raw)
            kalshi_fed_raw = []
        if isinstance(poly_fed_raw, BaseException):
            logger.error("Polymarket Fed search failed: %s", poly_fed_raw)
            poly_fed_raw = []

        kalshi_probs = self._kalshi_fed_probabilities(kalshi_fed_raw)
        poly_probs = self._poly_fed_probabilities(poly_fed_raw)

        now_iso = datetime.now(timezone.utc).isoformat()
        sources: list[str] = []
        merged: dict[str, float] = {}

        k_probs = kalshi_probs.get("next_meeting", {}).get("probabilities", {})
        p_probs = poly_probs.get("probabilities", {})

        if k_probs:
            sources.append("kalshi")
            merged.update(k_probs)
        if p_probs:
            sources.append("polymarket")
            for key, val in p_probs.items():
                if key in merged:
                    merged[key] = (merged[key] + val) / 2.0
                else:
                    merged[key] = val

        if not merged:
            return {}

        result = {
            "probabilities": merged,
            "next_meeting_date": kalshi_probs.get("next_meeting", {}).get("date", ""),
            "sources": sources,
            "fetched_at": now_iso,
        }

        _set_agg_cache("fed_consensus", result)
        return result

    async def get_event_probabilities(self, category: str) -> list[dict[str, Any]]:
        """Get event probabilities for a category, merged from both platforms.

        Merges results, deduplicates by similar event titles, and includes
        source attribution.

        Args:
            category: One of 'fed', 'recession', 'inflation', 'sp500', 'gdp'.

        Returns:
            List of event dicts with 'title', 'probability', 'source',
            'volume', and optional extra fields.  Empty list if nothing found.
        """
        cache_key = f"event_probabilities:{category}"
        cached = _get_agg_cached(cache_key)
        if cached is not None:
            return cached

        category_lower = category.lower().strip()

        # --- Kalshi ---
        kalshi_series_map = {
            "fed": "fed",
            "inflation": "cpi",
            "cpi": "cpi",
            "gdp": "gdp",
            "sp500": "sp500",
            "unemployment": "unemployment",
        }

        kalshi_events: list[dict[str, Any]] = []
        series_key = kalshi_series_map.get(category_lower)
        if series_key:
            kalshi_data = await self._kalshi.get_all_economic_markets()
            for m in kalshi_data.get(series_key, []):
                kalshi_events.append({
                    "title": m.get("title", ""),
                    "probability": m.get("probability", 0.0),
                    "volume": m.get("volume", 0),
                    "close_time": m.get("close_time", ""),
                    "ticker": m.get("ticker", ""),
                    "source": "kalshi",
                })

        # --- Polymarket ---
        poly_events: list[dict[str, Any]] = []
        search_terms = {
            "fed": "Federal Reserve rate",
            "recession": "recession",
            "inflation": "inflation CPI",
            "sp500": "S&P 500",
            "gdp": "GDP",
            "cpi": "CPI",
            "unemployment": "unemployment",
        }
        search_query = search_terms.get(category_lower, category)
        poly_raw = await self._polymarket.search_markets(search_query)
        if not isinstance(poly_raw, BaseException):
            for m in poly_raw:
                prob = _extract_probability_from_outcome_prices(m)
                poly_events.append({
                    "title": m.get("question", ""),
                    "probability": prob,
                    "volume": m.get("volume", 0),
                    "end_date": m.get("end_date", ""),
                    "url": m.get("url", ""),
                    "source": "polymarket",
                })

        # --- Merge & deduplicate ---
        merged: list[dict[str, Any]] = list(kalshi_events)

        for pe in poly_events:
            pe_title = pe.get("title", "")
            duplicate_found = False
            for existing in merged:
                if _are_similar_events(pe_title, existing.get("title", "")):
                    # Merge: average probabilities, note both sources
                    if pe.get("probability") is not None and existing.get("probability") is not None:
                        existing["probability"] = (existing["probability"] + pe["probability"]) / 2.0
                    elif pe.get("probability") is not None:
                        existing["probability"] = pe["probability"]
                    existing["source"] = "kalshi+polymarket"
                    existing["polymarket_url"] = pe.get("url", "")
                    duplicate_found = True
                    break
            if not duplicate_found:
                merged.append(pe)

        # Sort by volume descending
        merged.sort(key=lambda e: e.get("volume", 0) or 0, reverse=True)

        if merged:
            _set_agg_cache(cache_key, merged)

        return merged

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close underlying adapter connections."""
        await asyncio.gather(
            self._polymarket.close(),
            self._kalshi.close(),
            return_exceptions=True,
        )

    async def __aenter__(self) -> "PredictionMarketAggregator":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[PredictionMarketAggregator] = None


def get_prediction_market_aggregator() -> PredictionMarketAggregator:
    """Get or create the singleton PredictionMarketAggregator instance."""
    global _instance
    if _instance is None:
        _instance = PredictionMarketAggregator()
    return _instance
