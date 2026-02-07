"""Comprehensive pytest fixtures for the Teletraan backend test suite.

Provides:
- Async in-memory SQLite test database with full schema
- FastAPI async test client (httpx.AsyncClient + ASGITransport)
- Sample data factories for Stock, PriceHistory, Insight, AnalysisTask, DeepInsight
- Mock fixtures for yfinance and claude-agent-sdk external services
"""

from __future__ import annotations

import uuid
from datetime import date
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Test database engine & session factory (in-memory SQLite)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

TestSessionFactory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated async database session backed by in-memory SQLite.

    Creates all tables before the test and drops them afterwards so every test
    starts with a clean schema.
    """
    from database import Base  # noqa: E402  -- deferred to avoid circular imports

    # Import all model modules so Base.metadata knows about every table.
    import models  # noqa: F401

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionFactory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an ``httpx.AsyncClient`` wired to the FastAPI app.

    The ``get_db`` dependency (from both ``database`` and ``api.deps``) is
    overridden so every request handler receives the test session.
    """
    from main import app  # noqa: E402
    from database import get_db as database_get_db  # noqa: E402
    from api.deps import get_db as deps_get_db  # noqa: E402

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[database_get_db] = _override_get_db
    app.dependency_overrides[deps_get_db] = _override_get_db

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_stock_data() -> dict[str, Any]:
    """Return a dictionary representing typical stock data fields.

    Useful for constructing ``Stock`` model instances or for feeding into
    analysis helpers that expect a stock-data dict.
    """
    return {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 3_000_000_000_000.0,
        "is_active": True,
    }


@pytest.fixture()
def sample_price_data() -> list[dict[str, Any]]:
    """Return a list of price-history dicts suitable for analysis modules.

    Contains 5 consecutive trading days with realistic OHLCV data.
    """
    prices = [
        {"date": date(2026, 1, 5), "open": 180.0, "high": 185.0, "low": 179.0, "close": 184.0, "volume": 50_000_000},
        {"date": date(2026, 1, 6), "open": 184.0, "high": 187.0, "low": 183.0, "close": 186.0, "volume": 48_000_000},
        {"date": date(2026, 1, 7), "open": 186.0, "high": 189.0, "low": 184.0, "close": 185.0, "volume": 52_000_000},
        {"date": date(2026, 1, 8), "open": 185.0, "high": 188.0, "low": 182.0, "close": 187.0, "volume": 55_000_000},
        {"date": date(2026, 1, 9), "open": 187.0, "high": 190.0, "low": 186.0, "close": 189.0, "volume": 47_000_000},
    ]
    return prices


@pytest.fixture()
async def sample_stock(db_session: AsyncSession, sample_stock_data: dict[str, Any]):
    """Insert and return a ``Stock`` row in the test database."""
    from models.stock import Stock

    stock = Stock(**sample_stock_data)
    db_session.add(stock)
    await db_session.commit()
    await db_session.refresh(stock)
    return stock


@pytest.fixture()
async def sample_stock_with_prices(
    db_session: AsyncSession,
    sample_stock,
    sample_price_data: list[dict[str, Any]],
):
    """Insert a ``Stock`` with associated ``PriceHistory`` rows and return the stock."""
    from models.price import PriceHistory

    for p in sample_price_data:
        ph = PriceHistory(stock_id=sample_stock.id, **p)
        db_session.add(ph)
    await db_session.commit()
    return sample_stock


@pytest.fixture()
async def sample_insight(db_session: AsyncSession, sample_stock):
    """Insert and return an ``Insight`` row linked to the sample stock."""
    from models.insight import Insight

    insight = Insight(
        stock_id=sample_stock.id,
        insight_type="pattern",
        title="Golden Cross Detected",
        description="50-day SMA crossed above 200-day SMA indicating bullish trend",
        severity="info",
        confidence=0.85,
        is_active=True,
    )
    db_session.add(insight)
    await db_session.commit()
    await db_session.refresh(insight)
    return insight


@pytest.fixture()
async def sample_analysis_task(db_session: AsyncSession):
    """Insert and return an ``AnalysisTask`` row in the test database."""
    from models.analysis_task import AnalysisTask, AnalysisTaskStatus

    task = AnalysisTask(
        id=str(uuid.uuid4()),
        status=AnalysisTaskStatus.PENDING.value,
        progress=0,
        current_phase="Initializing...",
        max_insights=5,
        deep_dive_count=7,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.fixture()
async def sample_deep_insight(db_session: AsyncSession):
    """Insert and return a ``DeepInsight`` row in the test database."""
    from models.deep_insight import DeepInsight

    insight = DeepInsight(
        insight_type="opportunity",
        action="BUY",
        title="NVDA AI Infrastructure Play",
        thesis="Strong demand for GPU compute driven by LLM training buildout.",
        primary_symbol="NVDA",
        related_symbols=["AMD", "AVGO", "SMH"],
        supporting_evidence=[
            {"analyst": "technical", "finding": "Breakout above $900 resistance"},
            {"analyst": "macro", "finding": "Capex growth in hyperscaler segment"},
        ],
        confidence=0.88,
        time_horizon="3-6 months",
        risk_factors=["Valuation stretched at 35x forward PE", "China export restrictions"],
        invalidation_trigger="Close below $780 on weekly chart",
        analysts_involved=["technical", "macro", "sector"],
        data_sources=["yfinance", "FRED"],
        entry_zone="$880-$920",
        target_price="$1100 within 6 months",
        stop_loss="$780 (-13%)",
        timeframe="position",
    )
    db_session.add(insight)
    await db_session.commit()
    await db_session.refresh(insight)
    return insight


# ---------------------------------------------------------------------------
# Mock fixtures for external services
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_yfinance():
    """Patch ``yfinance.download`` and ``yfinance.Ticker`` with deterministic fakes.

    Yields a namespace object with ``.download`` and ``.Ticker`` attributes for
    further assertion or configuration by the test.

    The ``Ticker().info`` property returns minimal stock metadata, and
    ``Ticker().history()`` returns a small DataFrame-like MagicMock.
    """
    import pandas as pd

    # Build a realistic DataFrame for yfinance.download / Ticker.history
    dates = pd.date_range("2026-01-05", periods=5, freq="B")
    mock_df = pd.DataFrame(
        {
            "Open": [180.0, 184.0, 186.0, 185.0, 187.0],
            "High": [185.0, 187.0, 189.0, 188.0, 190.0],
            "Low": [179.0, 183.0, 184.0, 182.0, 186.0],
            "Close": [184.0, 186.0, 185.0, 187.0, 189.0],
            "Volume": [50_000_000, 48_000_000, 52_000_000, 55_000_000, 47_000_000],
        },
        index=dates,
    )

    ticker_instance = MagicMock()
    ticker_instance.info = {
        "symbol": "AAPL",
        "shortName": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "marketCap": 3_000_000_000_000,
        "previousClose": 189.0,
        "regularMarketPrice": 190.5,
    }
    ticker_instance.history.return_value = mock_df

    with (
        patch("yfinance.download", return_value=mock_df) as mock_download,
        patch("yfinance.Ticker", return_value=ticker_instance) as mock_ticker_cls,
    ):
        yield MagicMock(download=mock_download, Ticker=mock_ticker_cls)


@pytest.fixture()
def mock_claude_sdk():
    """Patch ``claude_agent_sdk`` entry points used by the market agent.

    Mocks ``ClaudeSDKClient`` so tests never make real LLM calls. The mock
    client's ``complete()`` / ``create()`` methods return a canned assistant
    response.

    Yields the mock ``ClaudeSDKClient`` class for assertion.
    """
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "Based on my analysis, AAPL shows a bullish trend."

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    mock_response.stop_reason = "end_turn"
    mock_response.model = "claude-opus-4-6"

    mock_client_instance = MagicMock()
    # Support both sync and async call patterns
    mock_client_instance.create = MagicMock(return_value=mock_response)
    mock_client_instance.complete = MagicMock(return_value=mock_response)

    # Also support async variants
    mock_client_instance.acreate = AsyncMock(return_value=mock_response)
    mock_client_instance.acomplete = AsyncMock(return_value=mock_response)

    with patch(
        "claude_agent_sdk.ClaudeSDKClient",
        return_value=mock_client_instance,
    ) as mock_cls:
        yield mock_cls
