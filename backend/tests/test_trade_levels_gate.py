"""Tests for trade-level persistence, the entry-price sanity gate and factor wiring.

Regression cover for three measured defects:

* ``_store_insights_from_heatmap`` built its ``DeepInsight`` without ever
  setting ``entry_zone``/``target_price``/``stop_loss``/``timeframe``, so the
  levels the synthesis lead produced were dropped on the floor -- 309 of 414
  stored insights carried NULL levels and outcome tracking could never fire
  ``entry_triggered`` (6/221).
* The levels that did survive were quoted off stale charts: a STRONG_BUY on ARM
  with entry "$205-215" while ARM traded at $439.46.
* ``compute_factor_scores`` was called with one positional argument, so
  fundamentals never arrived and every symbol sat at exactly 0.60 coverage with
  ``value`` and ``quality`` permanently missing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from analysis.agents.heatmap_interfaces import (
    HeatmapAnalysis,
    HeatmapData,
    StockHeatmapEntry,
)
from analysis.agents.macro_scanner import MacroScanResult
from analysis.agents.opportunity_hunter import OpportunityList
from analysis.agents.sector_rotator import SectorRotationResult
from analysis.autonomous_engine import MAX_ENTRY_DEVIATION_PCT, AutonomousDeepEngine
from analysis.factor_model import FactorModel
from analysis.price_freshness import build_freshness, last_weekday
from models.deep_insight import DeepInsight


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The real numbers from the 2026-06-19 run that motivated the gate.
ARM_STALE_ENTRY = "$205-215"
ARM_LIVE_PRICE = 439.46


def _insight_data(
    symbol: str = "ARM",
    entry_zone: str | None = ARM_STALE_ENTRY,
    action: str = "HOLD",
) -> dict[str, Any]:
    """Build a synthesis-shaped insight dict carrying trading levels.

    ``action`` defaults to HOLD so the store path does not start outcome
    tracking (which would reach for live prices).
    """
    return {
        "insight_type": "opportunity",
        "action": action,
        "title": f"{symbol} setup",
        "thesis": "Thesis body.",
        "primary_symbol": symbol,
        "confidence": 0.7,
        "time_horizon": "medium_term",
        "entry_zone": entry_zone,
        "target_price": "$260",
        "stop_loss": "$195",
        "timeframe": "position",
    }


def _pre_context(symbol: str, price: float) -> dict[str, Any]:
    """Context carrying a fresh, usable price snapshot for *symbol*."""
    return {
        "price_freshness": {
            symbol.upper(): build_freshness(
                symbol.upper(), last_weekday(date.today()), price, "db_close"
            )
        }
    }


def _stale_pre_context(symbol: str, price: float) -> dict[str, Any]:
    """Context whose only snapshot is too old to be usable."""
    return {
        "price_freshness": {
            symbol.upper(): build_freshness(
                symbol.upper(),
                date.today() - timedelta(days=30),
                price,
                "db_close",
            )
        }
    }


def _engine() -> AutonomousDeepEngine:
    return AutonomousDeepEngine()


async def _store_heatmap(
    session: Any,
    engine: AutonomousDeepEngine,
    insights: list[dict[str, Any]],
    pre_context: dict[str, Any] | None,
) -> list[DeepInsight]:
    return await engine._store_insights_from_heatmap(
        session=session,
        insights_data=insights,
        macro_result=MacroScanResult(),
        heatmap_analysis=HeatmapAnalysis(),
        pre_context=pre_context,
    )


async def _store_legacy(
    session: Any,
    engine: AutonomousDeepEngine,
    insights: list[dict[str, Any]],
    pre_context: dict[str, Any] | None = None,
) -> list[DeepInsight]:
    return await engine._store_insights(
        session=session,
        insights_data=insights,
        macro_result=MacroScanResult(),
        sector_result=SectorRotationResult(),
        candidates=OpportunityList(),
        pre_context=pre_context,
    )


async def _persisted(session: Any, symbol: str) -> DeepInsight | None:
    rows = await session.execute(
        select(DeepInsight).where(DeepInsight.primary_symbol == symbol)
    )
    return rows.scalars().first()


# ---------------------------------------------------------------------------
# A. Trade levels round-trip to the database
# ---------------------------------------------------------------------------

async def test_heatmap_store_persists_trade_levels(db_session):
    """Levels emitted by synthesis must reach the DeepInsight row.

    Fails against the old code, which never passed entry_zone/target_price/
    stop_loss/timeframe to the DeepInsight constructor.
    """
    engine = _engine()
    data = _insight_data("ARM", entry_zone="$430-445")

    stored = await _store_heatmap(
        db_session, engine, [data], _pre_context("ARM", ARM_LIVE_PRICE)
    )

    assert len(stored) == 1
    row = await _persisted(db_session, "ARM")
    assert row is not None
    assert row.entry_zone == "$430-445"
    assert row.target_price == "$260"
    assert row.stop_loss == "$195"
    assert row.timeframe == "position"


async def test_legacy_store_persists_trade_levels(db_session):
    """The legacy pipeline's store path persists levels too."""
    engine = _engine()
    data = _insight_data("NVDA", entry_zone="$880-900")

    with patch.object(
        AutonomousDeepEngine,
        "_live_price_for_gate",
        AsyncMock(return_value=(890.0, "yahoo_quote")),
    ):
        stored = await _store_legacy(db_session, engine, [data])

    assert len(stored) == 1
    row = await _persisted(db_session, "NVDA")
    assert row is not None
    assert row.entry_zone == "$880-900"
    assert row.target_price == "$260"
    assert row.stop_loss == "$195"
    assert row.timeframe == "position"


# ---------------------------------------------------------------------------
# B. Entry-price sanity gate
# ---------------------------------------------------------------------------

async def test_entry_far_from_live_price_is_rejected(db_session, caplog):
    """ARM's $205-215 entry against a $439.46 tape must not be stored."""
    engine = _engine()
    data = _insight_data("ARM", entry_zone=ARM_STALE_ENTRY)

    with caplog.at_level(logging.WARNING, logger="analysis.autonomous_engine"):
        stored = await _store_heatmap(
            db_session, engine, [data], _pre_context("ARM", ARM_LIVE_PRICE)
        )

    assert stored == []
    assert await _persisted(db_session, "ARM") is None

    rejection = "\n".join(
        r.getMessage() for r in caplog.records if "[GATE] Rejected" in r.getMessage()
    )
    assert "ARM" in rejection
    assert "210.00" in rejection  # entry midpoint
    assert "439.46" in rejection  # live price
    assert "52.2%" in rejection  # computed deviation


async def test_entry_near_live_price_is_kept(db_session):
    """An entry inside the tolerance band survives the gate."""
    engine = _engine()
    # Midpoint 420 vs 439.46 -> 4.4% deviation.
    data = _insight_data("ARM", entry_zone="$410-430")

    stored = await _store_heatmap(
        db_session, engine, [data], _pre_context("ARM", ARM_LIVE_PRICE)
    )

    assert len(stored) == 1
    assert stored[0].entry_zone == "$410-430"


@pytest.mark.parametrize(
    ("midpoint", "kept"),
    [
        (ARM_LIVE_PRICE * (1 + (MAX_ENTRY_DEVIATION_PCT - 1) / 100), True),
        (ARM_LIVE_PRICE * (1 + (MAX_ENTRY_DEVIATION_PCT + 1) / 100), False),
    ],
)
async def test_gate_threshold_boundary(midpoint, kept):
    """The gate cuts at MAX_ENTRY_DEVIATION_PCT, not at some other number."""
    engine = _engine()
    passed = await engine._passes_entry_sanity_gate(
        "ARM", f"${midpoint:.2f}", _pre_context("ARM", ARM_LIVE_PRICE)
    )
    assert passed is kept


async def test_insight_rejected_when_no_usable_price(db_session):
    """No usable price means the entry cannot be verified, so it is dropped.

    Decision: the gate fails closed. An entry that nothing can be checked
    against is precisely the unverifiable recommendation this wave exists to
    keep away from the user; a stale snapshot plus a dead quote endpoint means
    the run's prices are broken, not that its levels are trustworthy.
    """
    engine = _engine()
    data = _insight_data("ARM", entry_zone="$430-445")

    with patch(
        "data.adapters.yahoo.yahoo_adapter.get_current_price",
        AsyncMock(side_effect=RuntimeError("quote endpoint down")),
    ):
        stored = await _store_heatmap(
            db_session, engine, [data], _stale_pre_context("ARM", 205.0)
        )

    assert stored == []
    assert await _persisted(db_session, "ARM") is None


async def test_stale_snapshot_falls_back_to_live_quote(db_session):
    """A stale snapshot is not used as the gate's reference price."""
    engine = _engine()
    data = _insight_data("ARM", entry_zone="$430-445")

    quote = AsyncMock(return_value={"symbol": "ARM", "price": ARM_LIVE_PRICE})
    with patch("data.adapters.yahoo.yahoo_adapter.get_current_price", quote):
        # The stale snapshot says $205 -- if the gate used it, $430-445 would
        # be rejected as 113% away.
        stored = await _store_heatmap(
            db_session, engine, [data], _stale_pre_context("ARM", 205.0)
        )

    assert len(stored) == 1
    quote.assert_awaited_once()


async def test_insight_without_entry_zone_is_not_gated(db_session):
    """An insight making no price claim has nothing to verify and is kept."""
    engine = _engine()
    data = _insight_data("MSFT", entry_zone=None)

    stored = await _store_heatmap(db_session, engine, [data], {})

    assert len(stored) == 1
    row = await _persisted(db_session, "MSFT")
    assert row is not None
    assert row.entry_zone is None
    assert row.target_price == "$260"


async def test_non_numeric_entry_zone_is_not_gated():
    """A qualitative entry ("on a breakout") carries no stale price to catch."""
    engine = _engine()
    passed = await engine._passes_entry_sanity_gate(
        "ARM", "on a breakout above resistance", _pre_context("ARM", ARM_LIVE_PRICE)
    )
    assert passed is True


# ---------------------------------------------------------------------------
# C. Factor model receives fundamentals
# ---------------------------------------------------------------------------

def _heatmap(symbols: list[str]) -> HeatmapData:
    """Heatmap with all four market-data factors measurable for every symbol."""
    stocks = [
        StockHeatmapEntry(
            symbol=sym,
            sector="Technology",
            price=100.0 + i,
            change_1d=0.5 + i,
            change_5d=1.0 + i,
            change_20d=3.0 + i,
            change_60d=8.0 + i,
            volume_ratio=1.1 + i * 0.1,
            market_cap=500.0,
            rsi_14=45.0 + i * 3,
            volatility_20d=25.0 + i,
        )
        for i, sym in enumerate(symbols)
    ]
    return HeatmapData(stocks=stocks, timestamp=datetime.utcnow())


def _fundamentals(symbols: list[str]) -> dict[str, dict]:
    return {
        sym: {
            "pe_ratio": 20.0 + i,
            "pb_ratio": 4.0 + i,
            "fcf_yield": 0.03 + i * 0.01,
            "roe": 0.25 + i * 0.02,
            "profit_margins": 0.20 + i * 0.01,
            "debt_to_equity": 40.0 + i * 5,
        }
        for i, sym in enumerate(symbols)
    }


async def test_factor_scores_computed_without_fundamentals_cap_at_060():
    """Baseline: market data alone leaves value and quality unmeasured."""
    symbols = ["AAA", "BBB", "CCC"]
    scores = await FactorModel().compute_factor_scores(
        {s.symbol: s.to_dict() for s in _heatmap(symbols).stocks}
    )

    assert set(scores) == set(symbols)
    for score in scores.values():
        assert score.coverage == pytest.approx(0.60)
        assert sorted(score.missing_factors) == ["quality", "value"]


async def test_pipeline_passes_fundamentals_to_factor_model():
    """The pipeline must hand fundamentals to compute_factor_scores.

    Fails against the old single-positional-argument call, which left every
    symbol at 0.60 coverage with value and quality permanently missing.
    """
    engine = _engine()
    symbols = ["AAA", "BBB", "CCC"]
    model = FactorModel()

    with patch.object(
        FactorModel,
        "fetch_fundamental_data",
        AsyncMock(return_value=_fundamentals(symbols)),
    ), patch("analysis.factor_model.get_factor_model", return_value=model):
        scores = await engine._compute_factor_scores(_heatmap(symbols))

    assert set(scores) == set(symbols)
    for score in scores.values():
        assert score.coverage == pytest.approx(1.0)
        assert score.missing_factors == []
        assert sorted(score.factors_used) == [
            "momentum", "quality", "technical", "value", "volatility", "volume",
        ]

    mean_coverage = sum(s.coverage for s in scores.values()) / len(scores)
    assert mean_coverage > 0.60


async def test_factor_scoring_degrades_when_fundamental_fetch_fails():
    """A failed fundamental fetch degrades the model instead of killing it."""
    engine = _engine()
    symbols = ["AAA", "BBB", "CCC"]
    model = FactorModel()

    with patch.object(
        FactorModel,
        "fetch_fundamental_data",
        AsyncMock(side_effect=RuntimeError("yfinance down")),
    ), patch("analysis.factor_model.get_factor_model", return_value=model):
        scores = await engine._compute_factor_scores(_heatmap(symbols))

    assert set(scores) == set(symbols)
    for score in scores.values():
        assert score.coverage == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# D1. The report must not print a plausible 50 for an unmeasured factor
# ---------------------------------------------------------------------------

async def test_report_renders_missing_factor_as_dash():
    """FactorScore.to_dict() omits unmeasured factors; the renderer must not
    substitute a neutral-looking 50 for them."""
    from api.routes.reports import _build_factor_scores_section

    symbols = ["AAA", "BBB", "CCC"]
    scores = await FactorModel().compute_factor_scores(
        {s.symbol: s.to_dict() for s in _heatmap(symbols).stocks}
    )
    payload = {sym: fs.to_dict() for sym, fs in scores.items()}
    assert all("value_score" not in p for p in payload.values())

    html = _build_factor_scores_section(payload)

    # One dash per unmeasured factor (value + quality) per symbol -- and no
    # invented number in their place.
    assert html.count('title="not measured"') == 2 * len(payload)
    assert "60%" in html  # coverage surfaced alongside the scores


async def test_report_renders_missing_factor_without_inventing_a_number():
    """The unmeasured cells carry a dash, never a plausible 50."""
    from api.routes.reports import _build_factor_scores_section

    html = _build_factor_scores_section(
        {
            "AAA": {
                "composite_score": 72.0,
                "coverage": 0.6,
                "momentum_score": 81.0,
                "volatility_score": 55.0,
                "volume_score": 66.0,
                "technical_score": 77.0,
                "missing_factors": ["value", "quality"],
            }
        }
    )

    assert ">50<" not in html
    assert html.count('title="not measured"') == 2
    assert ">81<" in html
    assert "60%" in html


async def test_report_renders_measured_factors_normally():
    """Measured factors still render as numbers."""
    from api.routes.reports import _build_factor_scores_section

    html = _build_factor_scores_section(
        {
            "AAA": {
                "composite_score": 72.0,
                "coverage": 1.0,
                "momentum_score": 81.0,
                "value_score": 64.0,
                "quality_score": 70.0,
                "volatility_score": 55.0,
                "volume_score": 66.0,
                "technical_score": 77.0,
                "missing_factors": [],
            }
        }
    )

    assert ">81<" in html
    assert ">64<" in html
    assert "100%" in html
    assert 'title="not measured"' not in html


# ---------------------------------------------------------------------------
# D. The legacy store prices from the run's own context
# ---------------------------------------------------------------------------

async def test_legacy_store_prices_from_the_provided_context(db_session):
    """The legacy path used to quote Yahoo once per insight inside the DB loop.

    ``_store_insights`` took no ``pre_context`` and passed ``None``, so every
    level-bearing legacy insight made a serial live call while a session was
    open -- and a Yahoo outage dropped all of them even when the run's own
    price context was perfectly healthy.
    """
    engine = _engine()
    data = _insight_data("ARM", entry_zone="$430-445")

    quote = AsyncMock(side_effect=RuntimeError("Yahoo must not be called"))
    with patch("data.adapters.yahoo.yahoo_adapter.get_current_price", quote):
        stored = await _store_legacy(
            db_session, engine, [data], _pre_context("ARM", ARM_LIVE_PRICE)
        )

    quote.assert_not_awaited()
    assert len(stored) == 1
    row = await _persisted(db_session, "ARM")
    assert row is not None
    assert row.entry_zone == "$430-445"


async def test_legacy_store_gate_rejects_a_stale_entry_from_the_context(db_session):
    """Threading the context in must not weaken the gate."""
    engine = _engine()
    data = _insight_data("ARM", entry_zone=ARM_STALE_ENTRY)

    quote = AsyncMock(side_effect=RuntimeError("Yahoo must not be called"))
    with patch("data.adapters.yahoo.yahoo_adapter.get_current_price", quote):
        stored = await _store_legacy(
            db_session, engine, [data], _pre_context("ARM", ARM_LIVE_PRICE)
        )

    quote.assert_not_awaited()
    assert stored == []
    assert await _persisted(db_session, "ARM") is None


async def test_legacy_store_still_falls_back_to_a_live_quote(db_session):
    """With no usable snapshot the gate keeps its live-quote fallback."""
    engine = _engine()
    data = _insight_data("ARM", entry_zone="$430-445")

    quote = AsyncMock(return_value={"symbol": "ARM", "price": ARM_LIVE_PRICE})
    with patch("data.adapters.yahoo.yahoo_adapter.get_current_price", quote):
        stored = await _store_legacy(
            db_session, engine, [data], _stale_pre_context("ARM", 205.0)
        )

    quote.assert_awaited_once()
    assert len(stored) == 1
