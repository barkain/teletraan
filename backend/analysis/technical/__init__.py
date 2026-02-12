"""Technical analysis package -- convenience API.

Provides :func:`compute_technical_analysis` which chains indicator computation
and scoring into a single call, plus re-exports of key building blocks.
"""

from __future__ import annotations

import logging

import pandas as pd  # type: ignore[import-untyped]

from .indicators import compute_batch, compute_indicators  # pyright: ignore[reportMissingImports]
from .scoring import TechnicalScorer, TechnicalSignalSummary, get_technical_scorer  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

__all__ = [
    "compute_technical_analysis",
    "compute_indicators",
    "compute_batch",
    "TechnicalScorer",
    "TechnicalSignalSummary",
    "get_technical_scorer",
]


def _flatten_indicators(raw: dict) -> dict:
    """Flatten the nested indicator dict into the flat-key format the scorer expects.

    The indicator module returns a nested structure like::

        {"trend": {"sma_20": 150.0, "macd": {"macd": 1.2, ...}}, ...}

    The scorer expects flat keys like ``sma_20``, ``macd_line``, ``bollinger_pct_b``, etc.
    """
    flat: dict = {}

    # --- Trend ---
    trend = raw.get("trend", {})
    for key in ("sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "psar"):
        if key in trend:
            flat[key] = trend[key]

    macd = trend.get("macd")
    if isinstance(macd, dict):
        flat["macd_line"] = macd.get("macd")
        flat["macd_signal"] = macd.get("signal")
        flat["macd_histogram"] = macd.get("histogram")

    adx = trend.get("adx")
    if isinstance(adx, dict):
        flat["adx"] = adx.get("adx")
        flat["plus_di"] = adx.get("plus_di")
        flat["minus_di"] = adx.get("minus_di")

    # --- Momentum ---
    momentum = raw.get("momentum", {})
    for key in ("rsi_14", "cci_20", "williams_r", "roc_12", "mfi_14"):
        if key in momentum:
            flat[key] = momentum[key]

    # Alias short names the scorer also checks
    if "rsi_14" in flat:
        flat["rsi"] = flat["rsi_14"]
    if "cci_20" in flat:
        flat["cci"] = flat["cci_20"]
    if "roc_12" in flat:
        flat["roc"] = flat["roc_12"]
    if "mfi_14" in flat:
        flat["mfi"] = flat["mfi_14"]

    stoch = momentum.get("stochastic")
    if isinstance(stoch, dict):
        flat["stoch_k"] = stoch.get("k")
        flat["stochastic_k"] = stoch.get("k")
        flat["stoch_d"] = stoch.get("d")
        flat["stochastic_d"] = stoch.get("d")

    # --- Volatility ---
    volatility = raw.get("volatility", {})

    bb = volatility.get("bollinger")
    if isinstance(bb, dict):
        flat["bollinger_upper"] = bb.get("upper")
        flat["bollinger_lower"] = bb.get("lower")
        flat["bollinger_pct_b"] = bb.get("percent_b")

    if "atr_14" in volatility:
        flat["atr"] = volatility["atr_14"]

    kc = volatility.get("keltner")
    if isinstance(kc, dict):
        flat["keltner_upper"] = kc.get("upper")
        flat["keltner_lower"] = kc.get("lower")

    # --- Volume ---
    volume = raw.get("volume", {})
    if "obv" in volume:
        flat["obv"] = volume["obv"]
    if "volume_sma_ratio" in volume:
        flat["volume_ratio"] = volume["volume_sma_ratio"]

    return flat


def compute_technical_analysis(
    symbol: str,
    ohlcv_df: pd.DataFrame,
) -> TechnicalSignalSummary | None:
    """Compute technical indicators and score them in one call.

    This is the main convenience entry-point for the technical analysis package.
    It chains :func:`compute_indicators` and :meth:`TechnicalScorer.compute_score`.

    Args:
        symbol: Ticker symbol (e.g. ``"AAPL"``).
        ohlcv_df: OHLCV DataFrame in standard yfinance format.

    Returns:
        A :class:`TechnicalSignalSummary` on success, or ``None`` if indicator
        computation fails or the DataFrame is empty/invalid.
    """
    try:
        raw_indicators = compute_indicators(symbol, ohlcv_df)
        if not raw_indicators:
            logger.warning(
                "No indicators computed for %s -- returning None", symbol
            )
            return None

        price = raw_indicators.get("latest_price")
        if price is None:
            logger.warning(
                "No latest_price in indicators for %s -- returning None", symbol
            )
            return None

        flat = _flatten_indicators(raw_indicators)
        scorer = get_technical_scorer()
        return scorer.compute_score(flat, price, symbol=symbol)

    except Exception:
        logger.warning(
            "Technical analysis failed for %s", symbol, exc_info=True
        )
        return None
