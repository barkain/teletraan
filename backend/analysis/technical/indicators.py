"""Core technical analysis indicator computation module.

Computes 30+ technical indicators from OHLCV pandas DataFrames using pandas_ta.
Results are cached with a 5-minute TTL keyed on (symbol, latest_date_in_df).

All indicator values are taken from the latest row (iloc[-1]) and rounded to
4 decimal places. Individual indicator failures are caught and logged without
blocking other computations.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional pandas_ta import — graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    import pandas_ta as ta  # type: ignore[import-untyped]

    _HAS_PANDAS_TA = True
except ImportError:
    ta = None  # type: ignore[assignment]
    _HAS_PANDAS_TA = False
    logger.warning(
        "pandas_ta is not installed — technical indicator computation will "
        "return empty dicts. Install with: pip install pandas_ta"
    )

if TYPE_CHECKING:
    import pandas_ta as ta  # type: ignore[import-untyped,no-redef]  # noqa: F811


# ---------------------------------------------------------------------------
# Module-level indicator cache (5-minute TTL)
# ---------------------------------------------------------------------------
_indicator_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cached(key: str) -> dict | None:
    """Get cached indicator data if within TTL."""
    if key in _indicator_cache:
        ts, data = _indicator_cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _indicator_cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    """Cache indicator data with current timestamp."""
    _indicator_cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round_val(value: Any, decimals: int = 4) -> float | None:
    """Round a numeric value, returning None for NaN/None."""
    if value is None:
        return None
    try:
        fval = float(value)
        if pd.isna(fval):
            return None
        return round(fval, decimals)
    except (ValueError, TypeError):
        return None


def _safe_last(series: pd.Series | None) -> float | None:
    """Safely get the last value from a pandas Series."""
    if series is None or series.empty:
        return None
    val = series.iloc[-1]
    return _round_val(val)


# ---------------------------------------------------------------------------
# Individual indicator computations
# ---------------------------------------------------------------------------

def _compute_trend(df: pd.DataFrame) -> dict[str, Any]:
    """Compute trend indicators: SMA, EMA, MACD, ADX, Parabolic SAR."""
    if ta is None:
        return {}
    result: dict[str, Any] = {}

    # --- SMA ---
    for period in (20, 50, 200):
        try:
            if len(df) >= period:
                sma = ta.sma(df["Close"], length=period)
                result[f"sma_{period}"] = _safe_last(sma)
            else:
                result[f"sma_{period}"] = None
        except Exception as e:
            logger.debug("SMA(%d) failed: %s", period, e)
            result[f"sma_{period}"] = None

    # --- EMA ---
    for period in (12, 26):
        try:
            if len(df) >= period:
                ema = ta.ema(df["Close"], length=period)
                result[f"ema_{period}"] = _safe_last(ema)
            else:
                result[f"ema_{period}"] = None
        except Exception as e:
            logger.debug("EMA(%d) failed: %s", period, e)
            result[f"ema_{period}"] = None

    # --- MACD ---
    try:
        if len(df) >= 35:  # Need at least 26 + 9 periods
            macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
            if macd_df is not None and not macd_df.empty:
                result["macd"] = {
                    "macd": _safe_last(macd_df.iloc[:, 0]),
                    "signal": _safe_last(macd_df.iloc[:, 2]),
                    "histogram": _safe_last(macd_df.iloc[:, 1]),
                }
            else:
                result["macd"] = {"macd": None, "signal": None, "histogram": None}
        else:
            result["macd"] = {"macd": None, "signal": None, "histogram": None}
    except Exception as e:
        logger.debug("MACD failed: %s", e)
        result["macd"] = {"macd": None, "signal": None, "histogram": None}

    # --- ADX ---
    try:
        if len(df) >= 28:  # ADX(14) needs ~2x the period
            adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
            if adx_df is not None and not adx_df.empty:
                # pandas_ta returns columns: ADX_14, DMP_14, DMN_14
                cols = adx_df.columns.tolist()
                adx_val = _safe_last(adx_df[cols[0]]) if len(cols) > 0 else None
                plus_di = _safe_last(adx_df[cols[1]]) if len(cols) > 1 else None
                minus_di = _safe_last(adx_df[cols[2]]) if len(cols) > 2 else None
                result["adx"] = {
                    "adx": adx_val,
                    "plus_di": plus_di,
                    "minus_di": minus_di,
                }
            else:
                result["adx"] = {"adx": None, "plus_di": None, "minus_di": None}
        else:
            result["adx"] = {"adx": None, "plus_di": None, "minus_di": None}
    except Exception as e:
        logger.debug("ADX failed: %s", e)
        result["adx"] = {"adx": None, "plus_di": None, "minus_di": None}

    # --- Parabolic SAR ---
    try:
        if len(df) >= 14:
            psar_df = ta.psar(df["High"], df["Low"], df["Close"])
            if psar_df is not None and not psar_df.empty:
                # psar returns multiple columns; long/short SAR values
                # Get the combined SAR value: use long if available, else short
                psar_long_col = [c for c in psar_df.columns if "PSARl" in c]
                psar_short_col = [c for c in psar_df.columns if "PSARs" in c]
                psar_val = None
                if psar_long_col:
                    psar_val = _safe_last(psar_df[psar_long_col[0]])
                if psar_val is None and psar_short_col:
                    psar_val = _safe_last(psar_df[psar_short_col[0]])
                result["psar"] = psar_val
            else:
                result["psar"] = None
        else:
            result["psar"] = None
    except Exception as e:
        logger.debug("Parabolic SAR failed: %s", e)
        result["psar"] = None

    return result


def _compute_momentum(df: pd.DataFrame) -> dict[str, Any]:
    """Compute momentum indicators: RSI, Stochastic, CCI, Williams %R, ROC, MFI."""
    if ta is None:
        return {}
    result: dict[str, Any] = {}

    # --- RSI ---
    try:
        if len(df) >= 15:
            rsi = ta.rsi(df["Close"], length=14)
            result["rsi_14"] = _safe_last(rsi)
        else:
            result["rsi_14"] = None
    except Exception as e:
        logger.debug("RSI failed: %s", e)
        result["rsi_14"] = None

    # --- Stochastic ---
    try:
        if len(df) >= 17:  # 14 + 3 for smoothing
            stoch_df = ta.stoch(
                df["High"], df["Low"], df["Close"],
                k=14, d=3, smooth_k=3,
            )
            if stoch_df is not None and not stoch_df.empty:
                cols = stoch_df.columns.tolist()
                k_val = _safe_last(stoch_df[cols[0]]) if len(cols) > 0 else None
                d_val = _safe_last(stoch_df[cols[1]]) if len(cols) > 1 else None
                result["stochastic"] = {"k": k_val, "d": d_val}
            else:
                result["stochastic"] = {"k": None, "d": None}
        else:
            result["stochastic"] = {"k": None, "d": None}
    except Exception as e:
        logger.debug("Stochastic failed: %s", e)
        result["stochastic"] = {"k": None, "d": None}

    # --- CCI ---
    try:
        if len(df) >= 21:
            cci = ta.cci(df["High"], df["Low"], df["Close"], length=20)
            result["cci_20"] = _safe_last(cci)
        else:
            result["cci_20"] = None
    except Exception as e:
        logger.debug("CCI failed: %s", e)
        result["cci_20"] = None

    # --- Williams %R ---
    try:
        if len(df) >= 15:
            willr = ta.willr(df["High"], df["Low"], df["Close"], length=14)
            result["williams_r"] = _safe_last(willr)
        else:
            result["williams_r"] = None
    except Exception as e:
        logger.debug("Williams %%R failed: %s", e)
        result["williams_r"] = None

    # --- ROC ---
    try:
        if len(df) >= 13:
            roc = ta.roc(df["Close"], length=12)
            result["roc_12"] = _safe_last(roc)
        else:
            result["roc_12"] = None
    except Exception as e:
        logger.debug("ROC failed: %s", e)
        result["roc_12"] = None

    # --- MFI ---
    try:
        if len(df) >= 15 and "Volume" in df.columns:
            mfi = ta.mfi(df["High"], df["Low"], df["Close"], df["Volume"], length=14)
            result["mfi_14"] = _safe_last(mfi)
        else:
            result["mfi_14"] = None
    except Exception as e:
        logger.debug("MFI failed: %s", e)
        result["mfi_14"] = None

    return result


def _compute_volatility(df: pd.DataFrame) -> dict[str, Any]:
    """Compute volatility indicators: Bollinger Bands, ATR, Keltner Channels."""
    if ta is None:
        return {}
    result: dict[str, Any] = {}

    # --- Bollinger Bands ---
    try:
        if len(df) >= 21:
            bbands_df = ta.bbands(df["Close"], length=20, std=2)
            if bbands_df is not None and not bbands_df.empty:
                cols = bbands_df.columns.tolist()
                # pandas_ta bbands returns: BBL, BBM, BBU, BBB, BBP
                lower = _safe_last(bbands_df[cols[0]]) if len(cols) > 0 else None
                mid = _safe_last(bbands_df[cols[1]]) if len(cols) > 1 else None
                upper = _safe_last(bbands_df[cols[2]]) if len(cols) > 2 else None
                bandwidth = _safe_last(bbands_df[cols[3]]) if len(cols) > 3 else None
                percent_b = _safe_last(bbands_df[cols[4]]) if len(cols) > 4 else None
                result["bollinger"] = {
                    "upper": upper,
                    "middle": mid,
                    "lower": lower,
                    "bandwidth": bandwidth,
                    "percent_b": percent_b,
                }
            else:
                result["bollinger"] = {
                    "upper": None, "middle": None, "lower": None,
                    "bandwidth": None, "percent_b": None,
                }
        else:
            result["bollinger"] = {
                "upper": None, "middle": None, "lower": None,
                "bandwidth": None, "percent_b": None,
            }
    except Exception as e:
        logger.debug("Bollinger Bands failed: %s", e)
        result["bollinger"] = {
            "upper": None, "middle": None, "lower": None,
            "bandwidth": None, "percent_b": None,
        }

    # --- ATR ---
    try:
        if len(df) >= 15:
            atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
            result["atr_14"] = _safe_last(atr)
        else:
            result["atr_14"] = None
    except Exception as e:
        logger.debug("ATR failed: %s", e)
        result["atr_14"] = None

    # --- Keltner Channels ---
    try:
        if len(df) >= 21:
            kc_df = ta.kc(df["High"], df["Low"], df["Close"], length=20, scalar=2)
            if kc_df is not None and not kc_df.empty:
                cols = kc_df.columns.tolist()
                # pandas_ta kc returns: KCLe, KCBe, KCUe
                kc_lower = _safe_last(kc_df[cols[0]]) if len(cols) > 0 else None
                kc_mid = _safe_last(kc_df[cols[1]]) if len(cols) > 1 else None
                kc_upper = _safe_last(kc_df[cols[2]]) if len(cols) > 2 else None
                result["keltner"] = {
                    "upper": kc_upper,
                    "middle": kc_mid,
                    "lower": kc_lower,
                }
            else:
                result["keltner"] = {"upper": None, "middle": None, "lower": None}
        else:
            result["keltner"] = {"upper": None, "middle": None, "lower": None}
    except Exception as e:
        logger.debug("Keltner Channels failed: %s", e)
        result["keltner"] = {"upper": None, "middle": None, "lower": None}

    return result


def _compute_volume(df: pd.DataFrame) -> dict[str, Any]:
    """Compute volume indicators: OBV, VWAP, A/D Line, Volume SMA ratio."""
    if ta is None:
        return {}
    result: dict[str, Any] = {}
    has_volume = "Volume" in df.columns and df["Volume"].sum() > 0

    # --- OBV ---
    try:
        if has_volume and len(df) >= 2:
            obv = ta.obv(df["Close"], df["Volume"])
            result["obv"] = _safe_last(obv)
        else:
            result["obv"] = None
    except Exception as e:
        logger.debug("OBV failed: %s", e)
        result["obv"] = None

    # --- VWAP ---
    # VWAP is meaningful only for intraday data (requires datetime index with
    # intraday timestamps). We detect intraday by checking if the index has
    # sub-day frequency.
    try:
        if has_volume and len(df) >= 2:
            idx = df.index
            is_intraday = False
            if hasattr(idx, "freq") and idx.freq is not None:
                # Frequency-based detection
                freq_str = str(idx.freq).lower()
                is_intraday = any(
                    unit in freq_str for unit in ("t", "min", "h", "s")
                )
            elif len(idx) >= 2:
                # Heuristic: if consecutive timestamps differ by < 1 day
                try:
                    diff = pd.Timestamp(idx[-1]) - pd.Timestamp(idx[-2])
                    is_intraday = diff.total_seconds() < 86400
                except Exception as exc:
                    logger.debug("Intraday detection heuristic failed: %s", exc)

            if is_intraday:
                vwap = ta.vwap(df["High"], df["Low"], df["Close"], df["Volume"])
                result["vwap"] = _safe_last(vwap)
            else:
                # Skip VWAP for daily data — not meaningful
                result["vwap"] = None
        else:
            result["vwap"] = None
    except Exception as e:
        logger.debug("VWAP failed (may not be intraday data): %s", e)
        result["vwap"] = None

    # --- Accumulation/Distribution Line ---
    try:
        if has_volume and len(df) >= 2:
            ad = ta.ad(df["High"], df["Low"], df["Close"], df["Volume"])
            result["ad_line"] = _safe_last(ad)
        else:
            result["ad_line"] = None
    except Exception as e:
        logger.debug("A/D Line failed: %s", e)
        result["ad_line"] = None

    # --- Volume SMA Ratio ---
    try:
        if has_volume and len(df) >= 20:
            vol_sma = ta.sma(df["Volume"], length=20)
            if vol_sma is not None and not vol_sma.empty:
                latest_vol = float(df["Volume"].iloc[-1])
                sma_val = float(vol_sma.iloc[-1])
                if sma_val > 0 and not pd.isna(sma_val):
                    result["volume_sma_ratio"] = round(latest_vol / sma_val, 4)
                else:
                    result["volume_sma_ratio"] = None
            else:
                result["volume_sma_ratio"] = None
        else:
            result["volume_sma_ratio"] = None
    except Exception as e:
        logger.debug("Volume SMA ratio failed: %s", e)
        result["volume_sma_ratio"] = None

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_indicators(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    """Compute all technical indicators for a single symbol.

    Args:
        symbol: Ticker symbol (e.g., "AAPL").
        df: pandas DataFrame with columns Open, High, Low, Close, Volume
            (standard yfinance format). Index should be DatetimeIndex.

    Returns:
        Dict with indicator values organized by category (trend, momentum,
        volatility, volume). Returns empty dict if pandas_ta is unavailable
        or the DataFrame is empty/invalid.
    """
    if not _HAS_PANDAS_TA:
        logger.warning(
            "pandas_ta not available — returning empty indicators for %s", symbol
        )
        return {}

    if df is None or df.empty:
        logger.warning("Empty DataFrame for %s — skipping indicators", symbol)
        return {}

    # Validate required columns
    required_cols = {"Open", "High", "Low", "Close"}
    if not required_cols.issubset(set(df.columns)):
        logger.warning(
            "DataFrame for %s missing required columns (has: %s, need: %s)",
            symbol,
            list(df.columns),
            required_cols,
        )
        return {}

    # --- Cache lookup ---
    try:
        latest_date = str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])
    except Exception:
        latest_date = "unknown"

    cache_key = f"indicators:{symbol}:{latest_date}"
    cached = _get_cached(cache_key)
    if cached is not None:
        logger.debug("Indicator cache hit for %s", symbol)
        return cached

    # --- Compute indicators by category ---
    logger.info(
        "Computing indicators for %s (%d rows, latest=%s)",
        symbol,
        len(df),
        latest_date,
    )

    # Ensure the DataFrame is sorted by date ascending
    if hasattr(df.index, "is_monotonic_increasing") and not df.index.is_monotonic_increasing:
        df = df.sort_index()

    # Drop rows where Close is NaN (common in yfinance multi-ticker downloads)
    df = df.dropna(subset=["Close"])

    if df.empty:
        logger.warning("DataFrame for %s is empty after dropping NaN closes", symbol)
        return {}

    trend = _compute_trend(df)
    momentum = _compute_momentum(df)
    volatility = _compute_volatility(df)
    volume = _compute_volume(df)

    # Build output
    latest_price = _round_val(df["Close"].iloc[-1])

    result: dict[str, Any] = {
        "symbol": symbol,
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        "latest_price": latest_price,
        "latest_date": latest_date,
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "volume": volume,
    }

    _set_cache(cache_key, result)
    return result


def compute_batch(symbols_dfs: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Compute indicators for multiple symbols.

    Args:
        symbols_dfs: Dict mapping symbol string to its OHLCV DataFrame.

    Returns:
        Dict mapping symbol to its indicator results dict. Symbols that
        fail are included with an empty dict value.
    """
    if not _HAS_PANDAS_TA:
        logger.warning(
            "pandas_ta not available — returning empty batch indicators"
        )
        return {sym: {} for sym in symbols_dfs}

    results: dict[str, dict] = {}
    for symbol, df in symbols_dfs.items():
        try:
            results[symbol] = compute_indicators(symbol, df)
        except Exception as e:
            logger.error("Indicator computation failed for %s: %s", symbol, e)
            results[symbol] = {}

    logger.info(
        "Batch indicators computed: %d/%d symbols succeeded",
        sum(1 for v in results.values() if v),
        len(symbols_dfs),
    )
    return results
