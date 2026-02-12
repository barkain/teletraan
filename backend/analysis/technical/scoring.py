"""
TradingView-style composite technical scoring engine.

Takes raw indicator values and computes a composite technical score
from -1.0 (Strong Sell) to +1.0 (Strong Buy).
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category weights (pattern recognition deferred, its 0.15 redistributed)
# Original: trend=0.30, momentum=0.25, volatility=0.15, volume=0.15, pattern=0.15
# Redistributed proportionally among the four active categories (sum = 0.85):
#   trend:      0.30 / 0.85 ≈ 0.353
#   momentum:   0.25 / 0.85 ≈ 0.294
#   volatility: 0.15 / 0.85 ≈ 0.176
#   volume:     0.15 / 0.85 ≈ 0.176
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS: dict[str, float] = {
    "trend": 0.353,
    "momentum": 0.294,
    "volatility": 0.176,
    "volume": 0.176,
}

# Rating thresholds
RATING_THRESHOLDS: list[tuple[float, str]] = [
    (0.5, "Strong Buy"),
    (0.1, "Buy"),
    (-0.1, "Neutral"),
    (-0.5, "Sell"),
]
RATING_DEFAULT = "Strong Sell"


@dataclass
class TechnicalSignalSummary:
    """Result of composite technical scoring."""

    symbol: str
    composite_score: float  # -1.0 to 1.0
    rating: str  # "Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"
    confidence: float  # 0.0 to 1.0 (indicator agreement rate)
    breakdown: dict = field(default_factory=dict)  # scores per category
    signals: dict = field(default_factory=dict)  # individual indicator signals
    key_levels: dict = field(default_factory=dict)  # support/resistance/pivot


def _sign(x: float) -> int:
    """Return +1, 0, or -1."""
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


class TechnicalScorer:
    """Computes a TradingView-style composite technical score."""

    # ------------------------------------------------------------------
    # Trend signal generators
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_sma(indicators: dict, price: float) -> dict[str, int]:
        """SMA signals: Price > SMA -> Buy, Price < SMA -> Sell."""
        signals: dict[str, int] = {}
        for period in (20, 50, 200):
            key = f"sma_{period}"
            val = indicators.get(key)
            if val is not None:
                signals[key] = 1 if price > val else -1
        return signals

    @staticmethod
    def _signal_ema(indicators: dict, price: float) -> dict[str, int]:
        """EMA signals: Price > EMA -> Buy."""
        signals: dict[str, int] = {}
        for period in (12, 26):
            key = f"ema_{period}"
            val = indicators.get(key)
            if val is not None:
                signals[key] = 1 if price > val else -1
        return signals

    @staticmethod
    def _signal_macd(indicators: dict) -> dict[str, int]:
        """MACD signals: histogram polarity + signal line crossover."""
        signals: dict[str, int] = {}
        histogram = indicators.get("macd_histogram")
        if histogram is not None:
            signals["macd_histogram"] = 1 if histogram > 0 else (-1 if histogram < 0 else 0)

        macd_line = indicators.get("macd_line")
        macd_signal = indicators.get("macd_signal")
        if macd_line is not None and macd_signal is not None:
            signals["macd_crossover"] = 1 if macd_line > macd_signal else -1
        return signals

    @staticmethod
    def _signal_adx(indicators: dict) -> dict[str, int]:
        """ADX signals: trend strength + direction."""
        adx = indicators.get("adx")
        plus_di = indicators.get("plus_di") or indicators.get("adx_plus_di")
        minus_di = indicators.get("minus_di") or indicators.get("adx_minus_di")
        if adx is None or plus_di is None or minus_di is None:
            return {}
        if adx < 25:
            return {"adx": 0}
        return {"adx": 1 if plus_di > minus_di else -1}

    @staticmethod
    def _signal_psar(indicators: dict, price: float) -> dict[str, int]:
        """Parabolic SAR: Price > PSAR -> Buy."""
        psar = indicators.get("psar") or indicators.get("parabolic_sar")
        if psar is None:
            return {}
        return {"psar": 1 if price > psar else -1}

    # ------------------------------------------------------------------
    # Momentum signal generators
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_rsi(indicators: dict) -> dict[str, int]:
        """RSI: >70 Sell, <30 Buy, else Neutral."""
        rsi = indicators.get("rsi") or indicators.get("rsi_14")
        if rsi is None:
            return {}
        if rsi > 70:
            return {"rsi": -1}
        elif rsi < 30:
            return {"rsi": 1}
        return {"rsi": 0}

    @staticmethod
    def _signal_stochastic(indicators: dict) -> dict[str, int]:
        """Stochastic: %K extremes + %K/%D crossover."""
        k = indicators.get("stoch_k") or indicators.get("stochastic_k")
        d = indicators.get("stoch_d") or indicators.get("stochastic_d")
        if k is None:
            return {}

        # Overbought/oversold takes priority
        if k > 80:
            return {"stochastic": -1}
        if k < 20:
            return {"stochastic": 1}

        # Crossover
        if d is not None:
            return {"stochastic": 1 if k > d else -1}
        return {"stochastic": 0}

    @staticmethod
    def _signal_cci(indicators: dict) -> dict[str, int]:
        """CCI: >100 Sell, <-100 Buy, else Neutral."""
        cci = indicators.get("cci")
        if cci is None:
            return {}
        if cci > 100:
            return {"cci": -1}
        elif cci < -100:
            return {"cci": 1}
        return {"cci": 0}

    @staticmethod
    def _signal_williams_r(indicators: dict) -> dict[str, int]:
        """Williams %R: >-20 Sell, <-80 Buy, else Neutral."""
        wr = indicators.get("williams_r") or indicators.get("willr")
        if wr is None:
            return {}
        if wr > -20:
            return {"williams_r": -1}
        elif wr < -80:
            return {"williams_r": 1}
        return {"williams_r": 0}

    @staticmethod
    def _signal_roc(indicators: dict) -> dict[str, int]:
        """ROC: >0 Buy, <0 Sell."""
        roc = indicators.get("roc")
        if roc is None:
            return {}
        return {"roc": 1 if roc > 0 else (-1 if roc < 0 else 0)}

    @staticmethod
    def _signal_mfi(indicators: dict) -> dict[str, int]:
        """MFI: >80 Sell, <20 Buy, else Neutral."""
        mfi = indicators.get("mfi")
        if mfi is None:
            return {}
        if mfi > 80:
            return {"mfi": -1}
        elif mfi < 20:
            return {"mfi": 1}
        return {"mfi": 0}

    # ------------------------------------------------------------------
    # Volatility signal generators
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_bollinger(indicators: dict) -> dict[str, int]:
        """Bollinger %B: >1.0 Sell, <0.0 Buy, 0.4-0.6 Neutral, else trend-following."""
        pct_b = indicators.get("bollinger_pct_b") or indicators.get("bb_pct_b")
        if pct_b is None:
            return {}
        if pct_b > 1.0:
            return {"bollinger_pct_b": -1}
        elif pct_b < 0.0:
            return {"bollinger_pct_b": 1}
        elif 0.4 <= pct_b <= 0.6:
            return {"bollinger_pct_b": 0}
        else:
            # Trend-following: above midpoint is bullish
            return {"bollinger_pct_b": 1 if pct_b > 0.5 else -1}

    @staticmethod
    def _signal_atr(indicators: dict) -> dict[str, int]:
        """ATR: Rising ATR with uptrend -> Buy, with downtrend -> Sell."""
        atr = indicators.get("atr")
        atr_prev = indicators.get("atr_prev") or indicators.get("atr_previous")
        if atr is None:
            return {}

        # Need prior ATR to determine direction; if unavailable, skip
        if atr_prev is None:
            return {}

        atr_rising = atr > atr_prev
        if not atr_rising:
            return {"atr": 0}

        # Determine trend from SMA-based signals or price vs SMA50
        sma50 = indicators.get("sma_50")
        price = indicators.get("_price")
        if sma50 is not None and price is not None:
            return {"atr": 1 if price > sma50 else -1}
        return {"atr": 0}

    @staticmethod
    def _signal_keltner(indicators: dict, price: float) -> dict[str, int]:
        """Keltner Channel: Price above upper -> Buy (breakout), below lower -> Sell."""
        upper = indicators.get("keltner_upper")
        lower = indicators.get("keltner_lower")
        signals: dict[str, int] = {}
        if upper is not None and lower is not None:
            if price > upper:
                signals["keltner"] = 1
            elif price < lower:
                signals["keltner"] = -1
            else:
                signals["keltner"] = 0
        return signals

    # ------------------------------------------------------------------
    # Volume signal generators
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_obv(indicators: dict) -> dict[str, int]:
        """OBV: Rising -> Buy, Falling -> Sell."""
        obv = indicators.get("obv")
        obv_sma = indicators.get("obv_sma") or indicators.get("obv_sma_5")
        if obv is None:
            return {}

        # Compare to 5-period SMA of OBV if available
        if obv_sma is not None:
            return {"obv": 1 if obv > obv_sma else -1}

        # Fallback: sign of latest change
        obv_prev = indicators.get("obv_prev") or indicators.get("obv_previous")
        if obv_prev is not None:
            diff = obv - obv_prev
            return {"obv": 1 if diff > 0 else (-1 if diff < 0 else 0)}

        return {}

    @staticmethod
    def _signal_volume_ratio(indicators: dict, trend_signal: float) -> dict[str, int]:
        """Volume ratio: >1.5 amplifies trend, <0.5 weakens (Neutral)."""
        vr = indicators.get("volume_ratio") or indicators.get("vol_ratio")
        if vr is None:
            return {}
        if vr < 0.5:
            return {"volume_ratio": 0}
        if vr > 1.5:
            return {"volume_ratio": _sign(trend_signal) if trend_signal != 0 else 0}
        return {"volume_ratio": 0}

    # ------------------------------------------------------------------
    # Key levels extraction
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_key_levels(indicators: dict, price: float) -> dict:
        """Extract support, resistance, and pivot levels from indicators."""
        support: list[float] = []
        resistance: list[float] = []
        pivot: float | None = None

        # Support levels
        sma200 = indicators.get("sma_200")
        if sma200 is not None:
            support.append(round(sma200, 2))

        bb_lower = indicators.get("bollinger_lower") or indicators.get("bb_lower")
        if bb_lower is not None:
            support.append(round(bb_lower, 2))

        keltner_lower = indicators.get("keltner_lower")
        if keltner_lower is not None:
            support.append(round(keltner_lower, 2))

        # Resistance levels
        bb_upper = indicators.get("bollinger_upper") or indicators.get("bb_upper")
        if bb_upper is not None:
            resistance.append(round(bb_upper, 2))

        keltner_upper = indicators.get("keltner_upper")
        if keltner_upper is not None:
            resistance.append(round(keltner_upper, 2))

        recent_high = indicators.get("recent_high") or indicators.get("high_52w")
        if recent_high is not None:
            resistance.append(round(recent_high, 2))

        # Pivot: SMA50
        sma50 = indicators.get("sma_50")
        if sma50 is not None:
            pivot = round(sma50, 2)

        # Sort levels
        support.sort()
        resistance.sort()

        return {
            "support": support,
            "resistance": resistance,
            "pivot": pivot,
        }

    # ------------------------------------------------------------------
    # Main scoring method
    # ------------------------------------------------------------------
    def compute_score(
        self,
        indicators: dict,
        price: float,
        symbol: str = "UNKNOWN",
    ) -> TechnicalSignalSummary:
        """Compute composite technical score from raw indicator values.

        Args:
            indicators: Dictionary of raw indicator values (from indicators.py).
            price: Current price of the instrument.
            symbol: Ticker symbol for the result.

        Returns:
            TechnicalSignalSummary with composite score and breakdown.
        """
        # Inject price for ATR signal helper
        enriched = {**indicators, "_price": price}

        # ----------------------------------------------------------
        # 1. Generate signals per category
        # ----------------------------------------------------------
        trend_signals: dict[str, int] = {}
        trend_signals.update(self._signal_sma(enriched, price))
        trend_signals.update(self._signal_ema(enriched, price))
        trend_signals.update(self._signal_macd(enriched))
        trend_signals.update(self._signal_adx(enriched))
        trend_signals.update(self._signal_psar(enriched, price))

        momentum_signals: dict[str, int] = {}
        momentum_signals.update(self._signal_rsi(enriched))
        momentum_signals.update(self._signal_stochastic(enriched))
        momentum_signals.update(self._signal_cci(enriched))
        momentum_signals.update(self._signal_williams_r(enriched))
        momentum_signals.update(self._signal_roc(enriched))
        momentum_signals.update(self._signal_mfi(enriched))

        volatility_signals: dict[str, int] = {}
        volatility_signals.update(self._signal_bollinger(enriched))
        volatility_signals.update(self._signal_atr(enriched))
        volatility_signals.update(self._signal_keltner(enriched, price))

        # For volume ratio, we need the trend signal direction
        trend_score = (
            sum(trend_signals.values()) / len(trend_signals)
            if trend_signals
            else 0.0
        )

        volume_signals: dict[str, int] = {}
        volume_signals.update(self._signal_obv(enriched))
        volume_signals.update(self._signal_volume_ratio(enriched, trend_score))

        category_signals: dict[str, dict[str, int]] = {
            "trend": trend_signals,
            "momentum": momentum_signals,
            "volatility": volatility_signals,
            "volume": volume_signals,
        }

        # ----------------------------------------------------------
        # 2. Compute per-category scores (mean of signals)
        # ----------------------------------------------------------
        category_scores: dict[str, float] = {}
        active_weights: dict[str, float] = {}

        for cat, sigs in category_signals.items():
            if sigs:
                cat_mean = sum(sigs.values()) / len(sigs)
                category_scores[cat] = round(cat_mean, 4)
                active_weights[cat] = CATEGORY_WEIGHTS[cat]
            else:
                logger.debug("Category '%s' has no available indicators — skipped", cat)

        # ----------------------------------------------------------
        # 3. Compute weighted composite score
        # ----------------------------------------------------------
        if not active_weights:
            logger.warning("No indicators available for %s — returning neutral", symbol)
            return TechnicalSignalSummary(
                symbol=symbol,
                composite_score=0.0,
                rating="Neutral",
                confidence=0.0,
                breakdown={},
                signals={},
                key_levels=self._extract_key_levels(indicators, price),
            )

        # Normalise weights so they sum to 1.0 (redistributes missing categories)
        weight_sum = sum(active_weights.values())
        normalised: dict[str, float] = {
            cat: w / weight_sum for cat, w in active_weights.items()
        }

        composite = sum(
            normalised[cat] * category_scores[cat] for cat in normalised
        )
        composite = max(-1.0, min(1.0, composite))  # clamp

        # ----------------------------------------------------------
        # 4. Determine rating
        # ----------------------------------------------------------
        rating = RATING_DEFAULT
        for threshold, label in RATING_THRESHOLDS:
            if composite > threshold:
                rating = label
                break

        # ----------------------------------------------------------
        # 5. Compute confidence (agreement rate)
        # ----------------------------------------------------------
        all_signals: dict[str, int] = {}
        for sigs in category_signals.values():
            all_signals.update(sigs)

        if all_signals and composite != 0.0:
            direction = _sign(composite)
            agreeing = sum(1 for v in all_signals.values() if _sign(v) == direction)
            confidence = agreeing / len(all_signals)
        elif all_signals:
            # Composite is exactly 0 — count neutrals as agreement
            neutral_count = sum(1 for v in all_signals.values() if v == 0)
            confidence = neutral_count / len(all_signals)
        else:
            confidence = 0.0

        confidence = round(confidence, 4)

        # ----------------------------------------------------------
        # 6. Build individual signal detail dict
        # ----------------------------------------------------------
        signals_detail: dict[str, dict] = {}
        for cat, sigs in category_signals.items():
            for name, val in sigs.items():
                sig_label = "Buy" if val > 0 else ("Sell" if val < 0 else "Neutral")
                signals_detail[name] = {
                    "signal": val,
                    "label": sig_label,
                    "category": cat,
                    "value": indicators.get(name),
                }

        # ----------------------------------------------------------
        # 7. Key levels
        # ----------------------------------------------------------
        key_levels = self._extract_key_levels(indicators, price)

        return TechnicalSignalSummary(
            symbol=symbol,
            composite_score=round(composite, 4),
            rating=rating,
            confidence=confidence,
            breakdown=category_scores,
            signals=signals_detail,
            key_levels=key_levels,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_scorer_instance: TechnicalScorer | None = None


def get_technical_scorer() -> TechnicalScorer:
    """Get or create the singleton TechnicalScorer instance.

    Returns:
        The TechnicalScorer singleton instance.
    """
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = TechnicalScorer()
    return _scorer_instance
