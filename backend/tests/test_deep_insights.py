"""Tests for the /api/v1/deep-insights endpoints."""  # noqa: S101

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.deep_insight import DeepInsight


# ---------------------------------------------------------------------------
# Helper to create a minimal DeepInsight
# ---------------------------------------------------------------------------


def _make_deep_insight(**overrides) -> DeepInsight:
    """Return a DeepInsight instance with sensible defaults, overridden by *overrides*."""
    defaults = dict(
        insight_type="opportunity",
        action="BUY",
        title="Test Insight",
        thesis="Test thesis for unit testing.",
        primary_symbol="TEST",
        related_symbols=[],
        supporting_evidence=[],
        confidence=0.75,
        time_horizon="1-3 months",
        risk_factors=[],
        analysts_involved=[],
        data_sources=[],
    )
    defaults.update(overrides)
    return DeepInsight(**defaults)


# ---------------------------------------------------------------------------
# GET /api/v1/deep-insights  (list)
# ---------------------------------------------------------------------------


async def test_list_deep_insights_empty(client: AsyncClient, db_session: AsyncSession):
    """Listing deep insights on an empty database returns an empty list with total 0."""
    resp = await client.get("/api/v1/deep-insights")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["items"] == []  # noqa: S101
    assert body["total"] == 0  # noqa: S101


async def test_list_deep_insights_with_data(client: AsyncClient, sample_deep_insight):
    """Listing deep insights returns existing data with correct fields."""
    resp = await client.get("/api/v1/deep-insights")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert len(body["items"]) == 1  # noqa: S101

    item = body["items"][0]
    assert item["id"] == sample_deep_insight.id  # noqa: S101
    assert item["title"] == "NVDA AI Infrastructure Play"  # noqa: S101
    assert item["action"] == "BUY"  # noqa: S101
    assert item["primary_symbol"] == "NVDA"  # noqa: S101
    assert item["confidence"] == pytest.approx(0.88)  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/deep-insights/{insight_id}  (get by ID)
# ---------------------------------------------------------------------------


async def test_get_deep_insight_found(client: AsyncClient, sample_deep_insight):
    """Getting an existing deep insight by ID returns it."""
    resp = await client.get(f"/api/v1/deep-insights/{sample_deep_insight.id}")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["id"] == sample_deep_insight.id  # noqa: S101
    assert body["title"] == "NVDA AI Infrastructure Play"  # noqa: S101
    assert body["action"] == "BUY"  # noqa: S101
    assert body["insight_type"] == "opportunity"  # noqa: S101


async def test_get_deep_insight_not_found(client: AsyncClient, db_session: AsyncSession):
    """Getting a non-existent deep insight returns 404."""
    resp = await client.get("/api/v1/deep-insights/99999")
    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/deep-insights  (action filter with grouping)
# ---------------------------------------------------------------------------


async def test_filter_deep_insights_by_action_buy_includes_strong_buy(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Filtering by action=BUY returns both BUY and STRONG_BUY insights."""
    buy_insight = _make_deep_insight(action="BUY", title="Regular Buy")
    strong_buy_insight = _make_deep_insight(action="STRONG_BUY", title="Strong Buy")
    hold_insight = _make_deep_insight(action="HOLD", title="Hold Signal")
    db_session.add_all([buy_insight, strong_buy_insight, hold_insight])
    await db_session.commit()

    resp = await client.get("/api/v1/deep-insights", params={"action": "BUY"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 2  # noqa: S101
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Regular Buy", "Strong Buy"}  # noqa: S101


async def test_filter_deep_insights_by_action_sell_includes_strong_sell(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Filtering by action=SELL returns both SELL and STRONG_SELL insights."""
    sell_insight = _make_deep_insight(action="SELL", title="Regular Sell")
    strong_sell_insight = _make_deep_insight(action="STRONG_SELL", title="Strong Sell")
    buy_insight = _make_deep_insight(action="BUY", title="Buy Signal")
    db_session.add_all([sell_insight, strong_sell_insight, buy_insight])
    await db_session.commit()

    resp = await client.get("/api/v1/deep-insights", params={"action": "SELL"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 2  # noqa: S101
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Regular Sell", "Strong Sell"}  # noqa: S101


async def test_filter_deep_insights_by_action_hold(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Filtering by action=HOLD returns only HOLD insights (no grouping)."""
    hold_insight = _make_deep_insight(action="HOLD", title="Hold Signal")
    buy_insight = _make_deep_insight(action="BUY", title="Buy Signal")
    db_session.add_all([hold_insight, buy_insight])
    await db_session.commit()

    resp = await client.get("/api/v1/deep-insights", params={"action": "HOLD"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["items"][0]["title"] == "Hold Signal"  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/deep-insights  (symbol and insight_type filters)
# ---------------------------------------------------------------------------


async def test_filter_deep_insights_by_symbol(client: AsyncClient, sample_deep_insight):
    """Filtering by symbol matches the primary_symbol field."""
    resp = await client.get("/api/v1/deep-insights", params={"symbol": "NVDA"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["items"][0]["primary_symbol"] == "NVDA"  # noqa: S101


async def test_filter_deep_insights_by_insight_type(client: AsyncClient, sample_deep_insight):
    """Filtering by insight_type returns only matching deep insights."""
    resp = await client.get("/api/v1/deep-insights", params={"insight_type": "opportunity"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["items"][0]["insight_type"] == "opportunity"  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/deep-insights/autonomous/status/{task_id}  (analysis task)
# ---------------------------------------------------------------------------


async def test_get_analysis_task_status(client: AsyncClient, sample_analysis_task):
    """Fetching analysis task status returns the task with pending status."""
    resp = await client.get(
        f"/api/v1/deep-insights/autonomous/status/{sample_analysis_task.id}"
    )
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["id"] == sample_analysis_task.id  # noqa: S101
    assert body["status"] == "pending"  # noqa: S101
    assert body["progress"] == 0  # noqa: S101


async def test_get_analysis_task_status_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Fetching a non-existent analysis task returns 404."""
    resp = await client.get(
        "/api/v1/deep-insights/autonomous/status/nonexistent-task-id"
    )
    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101
