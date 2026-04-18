"""Options-implied market signals: VIX term structure, SKEW index, put/call ratio, IV percentile.

Fetches freely available options-derived indicators from Yahoo Finance and formats
them as structured context for macro and risk analyst agents.

Signals:
- VIX term structure: VIX vs VIX3M (contango = calm, backwardation = stressed)
- CBOE Skew Index (^SKEW): elevated skew = tail-risk hedging even when VIX is low
- Put/Call ratio: aggregated from SPY near-term options chain
- VIX 52-week percentile: where current VIX sits vs the past year
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Put/call ratio reference thresholds (SPY historical averages)
PC_RATIO_AVG = 0.9
PC_COMPLACENT_THRESHOLD = 0.7   # below avg = too bullish / complacent
PC_FEARFUL_THRESHOLD = 1.2       # above avg = fear / hedging


@dataclass
class OptionsSignals:
    """Computed options-implied market signals."""

    vix: float = 0.0
    vix3m: float = 0.0
    skew: float = 0.0
    vix_percentile_52w: float = 0.0
    term_structure: str = "unknown"       # contango | backwardation | flat
    term_structure_spread: float = 0.0   # VIX3M - VIX (positive = contango)
    put_call_ratio: float | None = None
    pc_signal: str = "neutral"            # complacent | neutral | fearful
    available: bool = False

    def format_block(self) -> str:
        """Format signals as a text block for LLM injection.

        Returns:
            Formatted string block, or empty string if signals unavailable.
        """
        if not self.available:
            return ""

        lines = ["=== OPTIONS SENTIMENT ==="]

        # Put/call ratio
        if self.put_call_ratio is not None:
            if self.put_call_ratio < PC_COMPLACENT_THRESHOLD:
                label = f"below avg {PC_RATIO_AVG:.1f} = complacent"
            elif self.put_call_ratio > PC_FEARFUL_THRESHOLD:
                label = f"above avg {PC_RATIO_AVG:.1f} = fearful/hedging"
            else:
                label = f"near avg {PC_RATIO_AVG:.1f} = neutral"
            lines.append(f"- SPY Put/Call Ratio: {self.put_call_ratio:.2f} ({label})")

        # VIX term structure
        if self.vix > 0 and self.vix3m > 0:
            mood = (
                "calm" if self.term_structure == "contango"
                else "stressed" if self.term_structure == "backwardation"
                else "neutral"
            )
            lines.append(
                f"- VIX Term Structure: {self.term_structure.title()} "
                f"(VIX {self.vix:.1f}, VIX3M {self.vix3m:.1f}, "
                f"spread {self.term_structure_spread:+.1f}) = {mood}"
            )
        elif self.vix > 0:
            lines.append(f"- VIX: {self.vix:.1f}")

        # CBOE Skew
        if self.skew > 0:
            if self.skew > 135:
                skew_label = "elevated = significant tail-risk hedging"
            elif self.skew > 120:
                skew_label = "moderately elevated = some tail-risk concern"
            elif self.skew > 110:
                skew_label = "normal"
            else:
                skew_label = "low = complacency, limited tail hedging"
            lines.append(f"- CBOE Skew: {self.skew:.0f} ({skew_label})")

        # VIX 52-week percentile
        if self.vix_percentile_52w > 0:
            if self.vix_percentile_52w < 25:
                pct_label = "low = vol complacency"
            elif self.vix_percentile_52w > 75:
                pct_label = "high = vol fear"
            else:
                pct_label = "moderate"
            lines.append(f"- VIX 52w Percentile: {self.vix_percentile_52w:.0f}% ({pct_label})")

        return "\n".join(lines)


async def fetch_options_signals(adapter: Any | None = None) -> OptionsSignals:
    """Fetch and compute all options-implied signals.

    Uses yfinance to fetch VIX history, VIX3M, CBOE Skew, and SPY options chain.
    All I/O runs in a thread pool executor to stay non-blocking. Gracefully
    degrades if any individual source is unavailable.

    Args:
        adapter: Optional YahooFinanceAdapter (reserved for interface consistency;
            raw yfinance calls are used here to fetch the 1-year VIX history
            needed for percentile calculation).

    Returns:
        OptionsSignals with all available signals populated.
    """
    signals = OptionsSignals()

    try:
        import yfinance as yf

        loop = asyncio.get_running_loop()

        async def _fetch_hist(symbol: str, period: str) -> Any:
            ticker = yf.Ticker(symbol)
            return await loop.run_in_executor(
                None, lambda t=ticker, p=period: t.history(period=p)
            )

        # Parallel: VIX (1y for percentile), VIX3M (5d current), SKEW (5d current)
        vix_hist, vix3m_hist, skew_hist = await asyncio.gather(
            _fetch_hist("^VIX", "1y"),
            _fetch_hist("^VIX3M", "5d"),
            _fetch_hist("^SKEW", "5d"),
            return_exceptions=True,
        )

        # VIX current + 52-week percentile rank
        if (
            not isinstance(vix_hist, Exception)
            and vix_hist is not None
            and not vix_hist.empty
        ):
            signals.vix = round(float(vix_hist["Close"].iloc[-1]), 2)
            closes = vix_hist["Close"].dropna().tolist()
            if len(closes) > 1:
                below = sum(1 for v in closes[:-1] if v <= closes[-1])
                signals.vix_percentile_52w = round((below / (len(closes) - 1)) * 100, 1)

        # VIX3M current value
        if (
            not isinstance(vix3m_hist, Exception)
            and vix3m_hist is not None
            and not vix3m_hist.empty
        ):
            signals.vix3m = round(float(vix3m_hist["Close"].iloc[-1]), 2)

        # CBOE Skew current value
        if (
            not isinstance(skew_hist, Exception)
            and skew_hist is not None
            and not skew_hist.empty
        ):
            signals.skew = round(float(skew_hist["Close"].iloc[-1]), 1)

        # VIX term structure classification
        if signals.vix > 0 and signals.vix3m > 0:
            spread = signals.vix3m - signals.vix
            signals.term_structure_spread = round(spread, 2)
            if spread > 1.0:
                signals.term_structure = "contango"
            elif spread < -1.0:
                signals.term_structure = "backwardation"
            else:
                signals.term_structure = "flat"

        # SPY put/call ratio from near-term options chain
        try:
            spy = yf.Ticker("SPY")
            expirations = await loop.run_in_executor(None, lambda t=spy: t.options)
            if expirations:
                chain = await loop.run_in_executor(
                    None,
                    lambda t=spy, e=expirations[0]: t.option_chain(e),
                )
                put_vol = float(chain.puts["volume"].fillna(0).sum())
                call_vol = float(chain.calls["volume"].fillna(0).sum())
                if call_vol > 0:
                    signals.put_call_ratio = round(put_vol / call_vol, 2)
                    if signals.put_call_ratio < PC_COMPLACENT_THRESHOLD:
                        signals.pc_signal = "complacent"
                    elif signals.put_call_ratio > PC_FEARFUL_THRESHOLD:
                        signals.pc_signal = "fearful"
                    else:
                        signals.pc_signal = "neutral"
        except Exception as e:
            logger.debug(f"SPY put/call ratio unavailable: {e}")

        signals.available = signals.vix > 0

    except Exception as e:
        logger.warning(f"Options signals fetch failed: {e}")

    return signals
