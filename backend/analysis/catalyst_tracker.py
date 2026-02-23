"""Catalyst tracker for building LLM-ready context about upcoming earnings and events.

Consumes data from the EarningsAdapter and formats it into structured text
that can be injected into synthesis prompts for the analysis pipeline.
"""

from __future__ import annotations

import logging
import math

from data.adapters.earnings import (  # type: ignore[import-not-found]
    CatalystEvent,
    EarningsAdapter,
    EarningsQuarter,
    get_earnings_adapter,
)

logger = logging.getLogger(__name__)


class CatalystTracker:
    """Builds LLM-ready catalyst context from earnings and event data."""

    def __init__(self) -> None:
        self.earnings_adapter: EarningsAdapter = get_earnings_adapter()

    async def build_catalyst_context(
        self, symbols: list[str], days_ahead: int = 30
    ) -> str:
        """Build formatted catalyst context for LLM consumption.

        Args:
            symbols: List of ticker symbols to check.
            days_ahead: How many days ahead to scan for catalysts.

        Returns:
            Formatted markdown string describing upcoming catalysts.
        """
        if not symbols:
            return ""

        try:
            events = await self.earnings_adapter.get_upcoming_catalysts(
                symbols, days_ahead=days_ahead
            )
        except Exception as e:
            logger.warning(f"Failed to fetch catalysts: {e}")
            return ""

        if not events:
            return ""

        # Group events by symbol
        by_symbol: dict[str, list[CatalystEvent]] = {}
        for event in events:
            by_symbol.setdefault(event.symbol, []).append(event)

        lines: list[str] = [
            f"## Upcoming Catalysts (Next {days_ahead} Days)",
            "",
        ]

        # Symbols with catalysts
        for sym in sorted(by_symbol.keys()):
            sym_events = by_symbol[sym]
            for event in sym_events:
                if event.event_type == "earnings":
                    lines.append(self._format_earnings_event(sym, event))
                elif event.event_type == "ex_dividend":
                    lines.append(self._format_dividend_event(sym, event))

        # Symbols without catalysts
        no_catalyst_symbols = [
            s for s in symbols if s.upper() not in by_symbol
        ]
        if no_catalyst_symbols:
            lines.append("")
            for sym in sorted(no_catalyst_symbols):
                lines.append(
                    f"**{sym}** - No upcoming catalysts in next {days_ahead} days"
                )

        return "\n".join(lines)

    async def get_earnings_proximity_scores(
        self, symbols: list[str]
    ) -> dict[str, float]:
        """Score symbols by earnings proximity (higher = closer to earnings).

        Scores range from 0.0 (no upcoming earnings) to 1.0 (earnings today).
        Uses exponential decay: score = exp(-days_until / 10).

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict mapping symbol -> proximity score.
        """
        try:
            calendar = await self.earnings_adapter.get_earnings_calendar(
                symbols
            )
        except Exception as e:
            logger.warning(
                f"Failed to fetch earnings calendar for scoring: {e}"
            )
            return {s.upper(): 0.0 for s in symbols}

        scores: dict[str, float] = {}
        for sym in symbols:
            sym_upper = sym.upper()
            info = calendar.get(sym_upper)
            if (
                info
                and info.days_until_earnings is not None
                and info.days_until_earnings >= 0
            ):
                scores[sym_upper] = math.exp(
                    -info.days_until_earnings / 10.0
                )
            else:
                scores[sym_upper] = 0.0

        return scores

    def format_earnings_history(self, history: list[EarningsQuarter]) -> str:
        """Format beat/miss history for LLM context.

        Args:
            history: List of EarningsQuarter records.

        Returns:
            Formatted string showing beat/miss pattern.
        """
        if not history:
            return "No earnings history available."

        lines: list[str] = []
        beats = 0
        total = 0
        surprises: list[float] = []

        for q in history:
            if q.surprise_pct is not None:
                total += 1
                if q.surprise_pct > 0:
                    beats += 1
                surprises.append(q.surprise_pct)

                result = "Beat" if q.surprise_pct > 0 else "Miss"
                eps_str = ""
                if q.eps_actual is not None:
                    eps_str = f" (EPS: ${q.eps_actual:.2f}"
                    if q.eps_estimate is not None:
                        eps_str += f" vs ${q.eps_estimate:.2f} est"
                    eps_str += ")"

                date_str = (
                    q.date.strftime("%Y-%m-%d") if q.date else "N/A"
                )
                lines.append(
                    f"  {date_str}: {result} by {q.surprise_pct:+.1f}%{eps_str}"
                )

        summary = ""
        if total > 0:
            avg_surprise = sum(surprises) / len(surprises)
            summary = (
                f"  Last {total} quarters: Beat {beats}/{total} "
                f"(avg surprise: {avg_surprise:+.1f}%)"
            )

        if summary:
            lines.insert(0, summary)

        return "\n".join(lines)

    # ---------------------------------------------------------------------------
    # Formatting helpers
    # ---------------------------------------------------------------------------

    def _format_earnings_event(
        self, symbol: str, event: CatalystEvent
    ) -> str:
        """Format a single earnings catalyst event."""
        date_str = event.date.strftime("%b %d")
        lines = [
            f"**{symbol}** - Earnings in {event.days_until} days ({date_str})"
        ]

        details = event.details
        est_parts: list[str] = []
        if details.get("eps_estimate") is not None:
            est_parts.append(
                f"EPS Estimate: ${details['eps_estimate']:.2f}"
            )
        if details.get("revenue_estimate") is not None:
            rev = details["revenue_estimate"]
            if rev >= 1e9:
                est_parts.append(f"Revenue Est: ${rev / 1e9:.1f}B")
            elif rev >= 1e6:
                est_parts.append(f"Revenue Est: ${rev / 1e6:.1f}M")
            else:
                est_parts.append(f"Revenue Est: ${rev:,.0f}")

        if est_parts:
            lines.append(f"  - {' | '.join(est_parts)}")

        beat_rate = details.get("beat_rate_last_4q")
        avg_surprise = details.get("avg_surprise_pct")
        if beat_rate is not None:
            beats_count = round(beat_rate * 4)
            beat_str = f"Last 4 quarters: Beat {beats_count}/4"
            if avg_surprise is not None:
                beat_str += f" (avg surprise: {avg_surprise:+.1f}%)"
            lines.append(f"  - {beat_str}")

        return "\n".join(lines) + "\n"

    def _format_dividend_event(
        self, symbol: str, event: CatalystEvent
    ) -> str:
        """Format a single ex-dividend catalyst event."""
        date_str = event.date.strftime("%b %d")
        line = (
            f"**{symbol}** - Ex-Dividend in {event.days_until} days "
            f"({date_str})"
        )

        div_yield = event.details.get("dividend_yield")
        if div_yield is not None:
            line += f" (Yield: {div_yield * 100:.2f}%)"

        return line + "\n"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker: CatalystTracker | None = None


def get_catalyst_tracker() -> CatalystTracker:
    """Get or create the singleton CatalystTracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = CatalystTracker()
    return _tracker
