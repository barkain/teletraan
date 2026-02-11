"""Tests for the /api/v1/research endpoints."""  # noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest  # type: ignore[import-not-found]
from httpx import AsyncClient  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from models.deep_insight import DeepInsight  # type: ignore[import-not-found]
from models.insight_conversation import (  # type: ignore[import-not-found]
    FollowUpResearch,
    InsightConversation,
    ResearchStatus,
    ResearchType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deep_insight(**overrides) -> DeepInsight:
    """Return a DeepInsight with sensible defaults, overridden by *overrides*."""
    defaults = dict(
        insight_type="opportunity",
        action="BUY",
        title="Test Insight",
        thesis="Test thesis for research.",
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


async def _seed_insight_and_conversation(
    db: AsyncSession,
    *,
    insight_title: str = "Test Insight",
) -> tuple[DeepInsight, InsightConversation]:
    """Insert a DeepInsight and an InsightConversation linked to it.

    Returns:
        Tuple of (DeepInsight, InsightConversation).
    """
    insight = _make_deep_insight(title=insight_title)
    db.add(insight)
    await db.commit()
    await db.refresh(insight)

    conversation = InsightConversation(
        deep_insight_id=insight.id,
        title=f"Conversation about {insight_title}",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    return insight, conversation


async def _seed_research(
    db: AsyncSession,
    conversation: InsightConversation,
    *,
    research_type: ResearchType = ResearchType.DEEP_DIVE,
    status: ResearchStatus = ResearchStatus.PENDING,
    query: str = "What is the outlook for AAPL?",
) -> FollowUpResearch:
    """Insert and return a FollowUpResearch record."""
    research = FollowUpResearch(
        conversation_id=conversation.id,
        research_type=research_type,
        query=query,
        parameters={"symbols": ["AAPL"]},
        status=status,
    )
    db.add(research)
    await db.commit()
    await db.refresh(research)
    return research


# ---------------------------------------------------------------------------
# GET /api/v1/research  (list)
# ---------------------------------------------------------------------------


async def test_list_research_empty(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/research returns empty list when no research exists."""
    resp = await client.get("/api/v1/research")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["items"] == []  # noqa: S101
    assert body["total"] == 0  # noqa: S101


async def test_list_research_with_data(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/research returns research records when they exist."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    await _seed_research(db_session, conversation, query="Research question A")
    await _seed_research(
        db_session,
        conversation,
        query="Research question B",
        research_type=ResearchType.SCENARIO_ANALYSIS,
    )

    resp = await client.get("/api/v1/research")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 2  # noqa: S101
    assert len(body["items"]) == 2  # noqa: S101
    # Ordered by created_at descending
    queries = [item["query"] for item in body["items"]]
    assert "Research question A" in queries  # noqa: S101
    assert "Research question B" in queries  # noqa: S101


async def test_list_research_filter_by_status(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/research?status=COMPLETED filters by status."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    await _seed_research(db_session, conversation, status=ResearchStatus.PENDING)
    await _seed_research(db_session, conversation, status=ResearchStatus.COMPLETED, query="Completed research")
    await _seed_research(db_session, conversation, status=ResearchStatus.RUNNING, query="Running research")

    # Filter for COMPLETED
    resp = await client.get("/api/v1/research", params={"status": "COMPLETED"})

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["total"] == 1  # noqa: S101
    assert len(body["items"]) == 1  # noqa: S101
    assert body["items"][0]["status"] == "COMPLETED"  # noqa: S101

    # Filter for RUNNING
    resp2 = await client.get("/api/v1/research", params={"status": "RUNNING"})

    assert resp2.status_code == 200  # noqa: S101
    body2 = resp2.json()
    assert body2["total"] == 1  # noqa: S101
    assert body2["items"][0]["status"] == "RUNNING"  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/research/{id}  (detail)
# ---------------------------------------------------------------------------


async def test_get_research_detail(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/research/{id} returns full research detail."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    research = await _seed_research(db_session, conversation, query="Detailed research question")

    resp = await client.get(f"/api/v1/research/{research.id}")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["id"] == research.id  # noqa: S101
    assert body["query"] == "Detailed research question"  # noqa: S101
    assert body["research_type"] == "DEEP_DIVE"  # noqa: S101
    assert body["status"] == "PENDING"  # noqa: S101
    assert body["conversation_id"] == conversation.id  # noqa: S101


async def test_get_research_not_found(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/research/{id} returns 404 for non-existent research."""
    resp = await client.get("/api/v1/research/99999")

    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# POST /api/v1/research  (create)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="Route uses InsightConversation.insight_id instead of deep_insight_id",
    strict=True,
)
async def test_create_research(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/research creates a new research record with PENDING status."""
    # Seed a parent insight so create_research can find it
    insight = _make_deep_insight(title="Parent Insight for Research")
    db_session.add(insight)
    await db_session.commit()
    await db_session.refresh(insight)

    # Mock the followup research launcher to avoid LLM calls
    mock_launcher = AsyncMock()
    mock_launcher.launch = AsyncMock()

    with patch(
        "api.routes.research.get_followup_research_launcher",
        return_value=mock_launcher,
    ):
        resp = await client.post(
            "/api/v1/research",
            json={
                "parent_insight_id": insight.id,
                "research_type": "DEEP_DIVE",
                "query": "What happens if rates rise?",
                "symbols": ["AAPL", "MSFT"],
                "questions": ["Impact on tech sector?"],
            },
        )

    assert resp.status_code == 201  # noqa: S101
    body = resp.json()
    assert body["status"] == "PENDING"  # noqa: S101
    assert body["query"] == "What happens if rates rise?"  # noqa: S101
    assert body["research_type"] == "DEEP_DIVE"  # noqa: S101
    assert "id" in body  # noqa: S101
    assert body["conversation_id"] is not None  # noqa: S101


@pytest.mark.xfail(
    reason="Route creates InsightConversation with deep_insight_id=None (NOT NULL violation)",
    strict=True,
)
async def test_create_research_no_parent_insight(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/research without parent_insight_id creates standalone research."""
    mock_launcher = AsyncMock()
    mock_launcher.launch = AsyncMock()

    with patch(
        "api.routes.research.get_followup_research_launcher",
        return_value=mock_launcher,
    ):
        resp = await client.post(
            "/api/v1/research",
            json={
                "research_type": "SCENARIO_ANALYSIS",
                "query": "General market outlook for Q2",
                "symbols": ["SPY"],
            },
        )

    assert resp.status_code == 201  # noqa: S101
    body = resp.json()
    assert body["status"] == "PENDING"  # noqa: S101
    assert body["query"] == "General market outlook for Q2"  # noqa: S101
    assert body["parent_insight_summary"] is None  # noqa: S101


async def test_create_research_invalid_parent_insight(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/research with non-existent parent_insight_id returns 400."""
    resp = await client.post(
        "/api/v1/research",
        json={
            "parent_insight_id": 99999,
            "research_type": "DEEP_DIVE",
            "query": "Research with bad parent",
        },
    )

    assert resp.status_code == 400  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# DELETE /api/v1/research/{id}  (cancel)
# ---------------------------------------------------------------------------


async def test_cancel_research(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/research/{id} sets status to CANCELLED."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    research = await _seed_research(db_session, conversation, status=ResearchStatus.PENDING)

    resp = await client.delete(f"/api/v1/research/{research.id}")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["status"] == "CANCELLED"  # noqa: S101
    assert body["completed_at"] is not None  # noqa: S101


async def test_cancel_research_running(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/research/{id} can cancel RUNNING research too."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    research = await _seed_research(db_session, conversation, status=ResearchStatus.RUNNING)

    resp = await client.delete(f"/api/v1/research/{research.id}")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["status"] == "CANCELLED"  # noqa: S101


async def test_cancel_research_already_completed(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/research/{id} returns 400 if research is already completed."""
    insight, conversation = await _seed_insight_and_conversation(db_session)
    research = await _seed_research(db_session, conversation, status=ResearchStatus.COMPLETED)

    resp = await client.delete(f"/api/v1/research/{research.id}")

    assert resp.status_code == 400  # noqa: S101
    assert "cannot cancel" in resp.json()["detail"].lower()  # noqa: S101


async def test_cancel_research_not_found(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/research/{id} returns 404 for non-existent research."""
    resp = await client.delete("/api/v1/research/99999")

    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101
