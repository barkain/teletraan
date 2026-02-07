"""Tests for the /api/v1/insights endpoints."""  # noqa: S101

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.insight import Insight
from models.stock import Stock


# ---------------------------------------------------------------------------
# GET /api/v1/insights  (list)
# ---------------------------------------------------------------------------


async def test_list_insights_empty(client: AsyncClient, db_session: AsyncSession):
    """Listing insights on an empty database returns an empty list with total 0."""
    resp = await client.get("/api/v1/insights")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["insights"] == []  # noqa: S101
    assert body["total"] == 0  # noqa: S101


async def test_list_insights_with_data(client: AsyncClient, sample_insight):
    """Listing insights returns existing insights."""
    resp = await client.get("/api/v1/insights")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert len(body["insights"]) == 1  # noqa: S101
    assert body["insights"][0]["id"] == sample_insight.id  # noqa: S101
    assert body["insights"][0]["title"] == "Golden Cross Detected"  # noqa: S101


async def test_list_insights_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_stock,
):
    """Pagination parameters skip and limit are respected."""
    for i in range(3):
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type="pattern",
            title=f"Insight {i}",
            description=f"Description {i}",
            severity="info",
            confidence=0.7,
            is_active=True,
        )
        db_session.add(insight)
    await db_session.commit()

    resp = await client.get("/api/v1/insights", params={"limit": 2})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 3  # noqa: S101
    assert len(body["insights"]) == 2  # noqa: S101

    resp = await client.get("/api/v1/insights", params={"skip": 2, "limit": 10})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert len(body["insights"]) == 1  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/insights  (filters)
# ---------------------------------------------------------------------------


async def test_filter_insights_by_insight_type(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_stock,
):
    """Filtering by insight_type returns only matching insights."""
    for itype in ("pattern", "anomaly", "pattern"):
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type=itype,
            title=f"{itype} insight",
            description="desc",
            severity="info",
            confidence=0.5,
            is_active=True,
        )
        db_session.add(insight)
    await db_session.commit()

    resp = await client.get("/api/v1/insights", params={"insight_type": "anomaly"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["insights"][0]["insight_type"] == "anomaly"  # noqa: S101


async def test_filter_insights_by_severity(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_stock,
):
    """Filtering by severity returns only matching insights."""
    for sev in ("info", "warning", "alert"):
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type="pattern",
            title=f"{sev} insight",
            description="desc",
            severity=sev,
            confidence=0.5,
            is_active=True,
        )
        db_session.add(insight)
    await db_session.commit()

    resp = await client.get("/api/v1/insights", params={"severity": "alert"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["insights"][0]["severity"] == "alert"  # noqa: S101


async def test_filter_insights_by_symbol(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_stock,
):
    """Filtering by symbol returns only insights linked to that stock."""
    insight = Insight(
        stock_id=sample_stock.id,
        insight_type="technical",
        title="AAPL insight",
        description="desc",
        severity="info",
        confidence=0.6,
        is_active=True,
    )
    db_session.add(insight)

    other_stock = Stock(
        symbol="MSFT",
        name="Microsoft",
        sector="Technology",
        industry="Software",
        market_cap=2_500_000_000_000.0,
        is_active=True,
    )
    db_session.add(other_stock)
    await db_session.commit()
    await db_session.refresh(other_stock)

    other_insight = Insight(
        stock_id=other_stock.id,
        insight_type="technical",
        title="MSFT insight",
        description="desc",
        severity="info",
        confidence=0.6,
        is_active=True,
    )
    db_session.add(other_insight)
    await db_session.commit()

    resp = await client.get("/api/v1/insights", params={"symbol": "AAPL"})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["insights"][0]["title"] == "AAPL insight"  # noqa: S101


async def test_filter_active_only_excludes_inactive(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_stock,
):
    """Default active_only=True excludes inactive insights."""
    active = Insight(
        stock_id=sample_stock.id,
        insight_type="pattern",
        title="Active",
        description="desc",
        severity="info",
        confidence=0.5,
        is_active=True,
    )
    inactive = Insight(
        stock_id=sample_stock.id,
        insight_type="pattern",
        title="Inactive",
        description="desc",
        severity="info",
        confidence=0.5,
        is_active=False,
    )
    db_session.add_all([active, inactive])
    await db_session.commit()

    resp = await client.get("/api/v1/insights")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert body["insights"][0]["title"] == "Active"  # noqa: S101

    resp = await client.get("/api/v1/insights", params={"active_only": False})
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 2  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/insights/{insight_id}  (get by ID)
# ---------------------------------------------------------------------------


async def test_get_insight_found(client: AsyncClient, sample_insight):
    """Getting an existing insight by ID returns it with correct fields."""
    resp = await client.get(f"/api/v1/insights/{sample_insight.id}")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["id"] == sample_insight.id  # noqa: S101
    assert body["title"] == "Golden Cross Detected"  # noqa: S101
    assert body["insight_type"] == "pattern"  # noqa: S101
    assert body["severity"] == "info"  # noqa: S101
    assert body["confidence"] == pytest.approx(0.85)  # noqa: S101
    assert body["is_active"] is True  # noqa: S101


async def test_get_insight_not_found(client: AsyncClient, db_session: AsyncSession):
    """Getting a non-existent insight returns 404."""
    resp = await client.get("/api/v1/insights/99999")
    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/insights/types  and  /api/v1/insights/severities
# ---------------------------------------------------------------------------


async def test_list_insight_types(client: AsyncClient):
    """The /types endpoint returns the known insight type list."""
    resp = await client.get("/api/v1/insights/types")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert "types" in body  # noqa: S101
    assert "pattern" in body["types"]  # noqa: S101
    assert "anomaly" in body["types"]  # noqa: S101


async def test_list_severities(client: AsyncClient):
    """The /severities endpoint returns the known severity list."""
    resp = await client.get("/api/v1/insights/severities")
    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert "severities" in body  # noqa: S101
    assert set(body["severities"]) == {"info", "warning", "alert"}  # noqa: S101
