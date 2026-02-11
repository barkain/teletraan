"""Tests for the /api/v1/knowledge/track-record/monthly-trend endpoint."""  # noqa: S101

from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from models.deep_insight import DeepInsight  # type: ignore[import-not-found]
from models.insight_outcome import InsightOutcome  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deep_insight(**overrides) -> DeepInsight:
    """Return a DeepInsight with sensible defaults."""
    defaults = dict(
        insight_type="opportunity",
        action="BUY",
        title="Test Insight",
        thesis="Test thesis.",
        primary_symbol="AAPL",
        related_symbols=[],
        supporting_evidence=[],
        confidence=0.80,
        time_horizon="1-3 months",
        risk_factors=[],
        analysts_involved=[],
        data_sources=[],
    )
    defaults.update(overrides)
    return DeepInsight(**defaults)


async def _seed_outcome(
    db: AsyncSession,
    *,
    thesis_validated: bool = True,
    tracking_end_date: date | None = None,
    actual_return_pct: float | None = None,
) -> InsightOutcome:
    """Insert a DeepInsight and a COMPLETED InsightOutcome linked to it.

    Returns:
        The created InsightOutcome.
    """
    insight = _make_deep_insight()
    db.add(insight)
    await db.commit()
    await db.refresh(insight)

    end_date = tracking_end_date or date.today()
    outcome = InsightOutcome(
        insight_id=insight.id,
        tracking_status="COMPLETED",
        tracking_start_date=end_date - timedelta(days=30),
        tracking_end_date=end_date,
        initial_price=150.0,
        final_price=165.0 if thesis_validated else 140.0,
        actual_return_pct=actual_return_pct,
        predicted_direction="bullish",
        thesis_validated=thesis_validated,
        outcome_category="SUCCESS" if thesis_validated else "FAILURE",
    )
    db.add(outcome)
    await db.commit()
    await db.refresh(outcome)
    return outcome


# ---------------------------------------------------------------------------
# GET /api/v1/knowledge/track-record/monthly-trend
# ---------------------------------------------------------------------------


async def test_monthly_trend_empty(client: AsyncClient, db_session: AsyncSession):
    """Returns empty data list when no completed outcomes exist."""
    resp = await client.get("/api/v1/knowledge/track-record/monthly-trend")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["data"] == []  # noqa: S101
    assert body["period_months"] == 12  # noqa: S101  (default)


async def test_monthly_trend_with_data(client: AsyncClient, db_session: AsyncSession):
    """Returns correctly grouped monthly data when outcomes exist."""
    today = date.today()

    # Create outcomes across two different months
    # Month 1 (current month): 2 successful, 1 failed
    await _seed_outcome(db_session, thesis_validated=True, tracking_end_date=today)
    await _seed_outcome(db_session, thesis_validated=True, tracking_end_date=today - timedelta(days=1))
    await _seed_outcome(db_session, thesis_validated=False, tracking_end_date=today - timedelta(days=2))

    # Month 2 (last month): 1 successful
    last_month = today.replace(day=1) - timedelta(days=1)
    await _seed_outcome(db_session, thesis_validated=True, tracking_end_date=last_month)

    resp = await client.get("/api/v1/knowledge/track-record/monthly-trend")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert len(body["data"]) == 2  # noqa: S101  (two distinct months)

    # Data is sorted oldest-to-newest
    months = [dp["month"] for dp in body["data"]]
    assert months == sorted(months)  # noqa: S101

    # Find current month data
    current_month_key = today.strftime("%Y-%m")
    current_dp = next((dp for dp in body["data"] if dp["month"] == current_month_key), None)
    assert current_dp is not None  # noqa: S101
    assert current_dp["total"] == 3  # noqa: S101
    assert current_dp["successful"] == 2  # noqa: S101

    # Find last month data
    last_month_key = last_month.strftime("%Y-%m")
    last_dp = next((dp for dp in body["data"] if dp["month"] == last_month_key), None)
    assert last_dp is not None  # noqa: S101
    assert last_dp["total"] == 1  # noqa: S101
    assert last_dp["successful"] == 1  # noqa: S101
    assert last_dp["rate"] == 1.0  # noqa: S101


async def test_monthly_trend_custom_lookback(client: AsyncClient, db_session: AsyncSession):
    """Respects the lookback_months query parameter."""
    resp = await client.get(
        "/api/v1/knowledge/track-record/monthly-trend",
        params={"lookback_months": 6},
    )

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["period_months"] == 6  # noqa: S101


# ---------------------------------------------------------------------------
# Import verification for pattern extraction and outcome tracking
# ---------------------------------------------------------------------------


async def test_imports(client: AsyncClient, db_session: AsyncSession):
    """Verify that modified modules import without errors."""
    # Pattern extraction modules
    from analysis.pattern_extractor import PatternExtractor  # type: ignore[import-not-found]  # noqa: F401

    # Engine modules that were modified
    from analysis.autonomous_engine import AutonomousDeepEngine  # type: ignore[import-not-found]  # noqa: F401
    from analysis.deep_engine import DeepAnalysisEngine  # type: ignore[import-not-found]  # noqa: F401

    # Outcome tracking model
    from models.insight_outcome import InsightOutcome as _IO  # type: ignore[import-not-found]  # noqa: F401, F811

    # Knowledge route schemas
    from schemas.knowledge import MonthlyTrendResponse  # type: ignore[import-not-found]  # noqa: F401
    from schemas.knowledge import MonthlyDataPoint  # type: ignore[import-not-found]  # noqa: F401

    # Research schemas
    from schemas.research import ResearchCreateRequest  # type: ignore[import-not-found]  # noqa: F401
    from schemas.research import ResearchListResponse  # type: ignore[import-not-found]  # noqa: F401
