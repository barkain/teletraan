"""Tests for the /api/v1/portfolio endpoints."""  # noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.deep_insight import DeepInsight
from models.portfolio import Portfolio, PortfolioHolding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deep_insight(**overrides) -> DeepInsight:
    """Return a DeepInsight with sensible defaults, overridden by *overrides*."""
    defaults = dict(
        insight_type="opportunity",
        action="BUY",
        title="Test Insight",
        thesis="Test thesis.",
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


async def _seed_portfolio_with_holding(
    db: AsyncSession,
    symbol: str = "AAPL",
    shares: float = 10.0,
    cost_basis: float = 150.0,
    notes: str | None = None,
) -> tuple[Portfolio, PortfolioHolding]:
    """Insert a Portfolio and one PortfolioHolding and return both."""
    portfolio = Portfolio(name="My Portfolio")
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)

    holding = PortfolioHolding(
        portfolio_id=portfolio.id,
        symbol=symbol,
        shares=shares,
        cost_basis=cost_basis,
        notes=notes,
    )
    db.add(holding)
    await db.commit()
    await db.refresh(holding)

    return portfolio, holding


def _patch_yfinance_price(price: float = 190.0):
    """Return a context-manager that patches yfinance.Ticker to return *price*.

    The patch targets the import inside the portfolio routes module so the
    ``_fetch_current_price`` helper picks it up.
    """
    ticker_instance = MagicMock()
    ticker_instance.info = {
        "regularMarketPrice": price,
        "previousClose": price - 1.0,
    }
    return patch(
        "api.routes.portfolio.yf.Ticker",
        return_value=ticker_instance,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio  (auto-create default)
# ---------------------------------------------------------------------------


async def test_get_portfolio_creates_default(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/portfolio auto-creates a portfolio named 'My Portfolio' when none exists."""
    with _patch_yfinance_price():
        resp = await client.get("/api/v1/portfolio")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["name"] == "My Portfolio"  # noqa: S101
    assert body["holdings"] == []  # noqa: S101
    assert "id" in body  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio  (returns existing with holdings)
# ---------------------------------------------------------------------------


async def test_get_portfolio_returns_existing(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/portfolio returns the portfolio including its holdings."""
    await _seed_portfolio_with_holding(db_session, symbol="AAPL", shares=5.0, cost_basis=150.0)

    with _patch_yfinance_price(190.0):
        resp = await client.get("/api/v1/portfolio")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["name"] == "My Portfolio"  # noqa: S101
    assert len(body["holdings"]) == 1  # noqa: S101
    assert body["holdings"][0]["symbol"] == "AAPL"  # noqa: S101
    assert body["holdings"][0]["shares"] == 5.0  # noqa: S101
    # Enriched fields should be populated
    assert body["holdings"][0]["current_price"] == pytest.approx(190.0)  # noqa: S101
    assert body["holdings"][0]["market_value"] == pytest.approx(950.0)  # noqa: S101


# ---------------------------------------------------------------------------
# POST /api/v1/portfolio  (create)
# ---------------------------------------------------------------------------


async def test_create_portfolio(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/portfolio creates a portfolio with the given name."""
    resp = await client.post(
        "/api/v1/portfolio",
        json={"name": "Tech Portfolio", "description": "Technology stocks"},
    )

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["name"] == "Tech Portfolio"  # noqa: S101
    assert body["description"] == "Technology stocks"  # noqa: S101
    assert "id" in body  # noqa: S101


# ---------------------------------------------------------------------------
# POST /api/v1/portfolio/holdings  (add holding)
# ---------------------------------------------------------------------------


async def test_add_holding(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/portfolio/holdings adds a new holding to the portfolio."""
    resp = await client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "MSFT", "shares": 20.0, "cost_basis": 350.0, "notes": "Long-term hold"},
    )

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["symbol"] == "MSFT"  # noqa: S101
    assert body["shares"] == 20.0  # noqa: S101
    assert body["cost_basis"] == 350.0  # noqa: S101
    assert body["notes"] == "Long-term hold"  # noqa: S101
    assert "id" in body  # noqa: S101


async def test_add_holding_validates_fields(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/portfolio/holdings with missing required fields returns 422."""
    # Missing 'shares' and 'cost_basis'
    resp = await client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "AAPL"},
    )
    assert resp.status_code == 422  # noqa: S101

    # Missing 'symbol'
    resp = await client.post(
        "/api/v1/portfolio/holdings",
        json={"shares": 10.0, "cost_basis": 150.0},
    )
    assert resp.status_code == 422  # noqa: S101

    # Empty body
    resp = await client.post(
        "/api/v1/portfolio/holdings",
        json={},
    )
    assert resp.status_code == 422  # noqa: S101


async def test_add_holding_uppercases_symbol(client: AsyncClient, db_session: AsyncSession):
    """POST /api/v1/portfolio/holdings stores symbol in uppercase."""
    resp = await client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "aapl", "shares": 10.0, "cost_basis": 150.0},
    )

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["symbol"] == "AAPL"  # noqa: S101


# ---------------------------------------------------------------------------
# PUT /api/v1/portfolio/holdings/{id}  (update holding)
# ---------------------------------------------------------------------------


async def test_update_holding(client: AsyncClient, db_session: AsyncSession):
    """PUT /api/v1/portfolio/holdings/{id} updates the specified fields."""
    _portfolio, holding = await _seed_portfolio_with_holding(
        db_session, symbol="AAPL", shares=10.0, cost_basis=150.0,
    )

    resp = await client.put(
        f"/api/v1/portfolio/holdings/{holding.id}",
        json={"shares": 25.0, "cost_basis": 160.0, "notes": "Added more"},
    )

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["shares"] == 25.0  # noqa: S101
    assert body["cost_basis"] == 160.0  # noqa: S101
    assert body["notes"] == "Added more"  # noqa: S101
    assert body["id"] == holding.id  # noqa: S101


async def test_update_holding_not_found(client: AsyncClient, db_session: AsyncSession):
    """PUT /api/v1/portfolio/holdings/{id} returns 404 for a non-existent holding."""
    resp = await client.put(
        "/api/v1/portfolio/holdings/99999",
        json={"shares": 5.0},
    )

    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# DELETE /api/v1/portfolio/holdings/{id}
# ---------------------------------------------------------------------------


async def test_delete_holding(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/portfolio/holdings/{id} removes the holding."""
    _portfolio, holding = await _seed_portfolio_with_holding(
        db_session, symbol="AAPL", shares=10.0, cost_basis=150.0,
    )

    resp = await client.delete(f"/api/v1/portfolio/holdings/{holding.id}")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert "deleted" in body["message"].lower()  # noqa: S101

    # Verify the holding is gone via GET portfolio
    with _patch_yfinance_price():
        resp2 = await client.get("/api/v1/portfolio")
    assert resp2.status_code == 200  # noqa: S101
    assert resp2.json()["holdings"] == []  # noqa: S101


async def test_delete_holding_not_found(client: AsyncClient, db_session: AsyncSession):
    """DELETE /api/v1/portfolio/holdings/{id} returns 404 for a non-existent holding."""
    resp = await client.delete("/api/v1/portfolio/holdings/99999")

    assert resp.status_code == 404  # noqa: S101
    assert "not found" in resp.json()["detail"].lower()  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio/impact  (no matching insights)
# ---------------------------------------------------------------------------


async def test_portfolio_impact_no_insights(client: AsyncClient, db_session: AsyncSession):
    """GET /api/v1/portfolio/impact returns empty impact when no insights match."""
    # Create portfolio with a holding but no deep insights in db
    await _seed_portfolio_with_holding(db_session, symbol="AAPL", shares=10.0, cost_basis=150.0)

    with _patch_yfinance_price(190.0):
        resp = await client.get("/api/v1/portfolio/impact")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()
    assert body["affected_holdings"] == []  # noqa: S101
    assert body["overall_bullish_exposure"] == 0.0  # noqa: S101
    assert body["overall_bearish_exposure"] == 0.0  # noqa: S101
    assert body["insight_count"] == 0  # noqa: S101


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio/impact  (with matching insights)
# ---------------------------------------------------------------------------


async def test_portfolio_impact_with_matching_insights(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /api/v1/portfolio/impact returns correct impact when insights match holdings."""
    # Seed portfolio with two holdings
    portfolio = Portfolio(name="My Portfolio")
    db_session.add(portfolio)
    await db_session.commit()
    await db_session.refresh(portfolio)

    holding_aapl = PortfolioHolding(
        portfolio_id=portfolio.id, symbol="AAPL", shares=10.0, cost_basis=150.0,
    )
    holding_nvda = PortfolioHolding(
        portfolio_id=portfolio.id, symbol="NVDA", shares=5.0, cost_basis=800.0,
    )
    db_session.add_all([holding_aapl, holding_nvda])
    await db_session.commit()

    # Create a BUY insight matching AAPL
    buy_insight = _make_deep_insight(
        action="BUY",
        title="AAPL Bullish",
        primary_symbol="AAPL",
        related_symbols=[],
    )
    # Create a SELL insight matching NVDA
    sell_insight = _make_deep_insight(
        action="SELL",
        title="NVDA Bearish",
        primary_symbol="NVDA",
        related_symbols=["AAPL"],  # AAPL also appears as related
    )
    db_session.add_all([buy_insight, sell_insight])
    await db_session.commit()

    # Expire the cached portfolio so the route handler re-loads it with holdings.
    # Without this, SQLAlchemy returns the identity-mapped Portfolio from the first
    # commit (when it had 0 holdings) because expire_on_commit=False in the test
    # session factory.
    db_session.expire(portfolio)

    # Mock yfinance to return predictable prices: AAPL=190, NVDA=900
    def _ticker_side_effect(symbol: str):
        mock_ticker = MagicMock()
        if symbol == "AAPL":
            mock_ticker.info = {"regularMarketPrice": 190.0}
        elif symbol == "NVDA":
            mock_ticker.info = {"regularMarketPrice": 900.0}
        else:
            mock_ticker.info = {"regularMarketPrice": 100.0}
        return mock_ticker

    with patch("api.routes.portfolio.yf.Ticker", side_effect=_ticker_side_effect):
        resp = await client.get("/api/v1/portfolio/impact")

    assert resp.status_code == 200  # noqa: S101
    body = resp.json()

    assert body["insight_count"] == 2  # noqa: S101
    assert body["portfolio_value"] > 0  # noqa: S101

    # Both AAPL and NVDA should be affected
    affected_symbols = {h["symbol"] for h in body["affected_holdings"]}
    assert "AAPL" in affected_symbols  # noqa: S101
    assert "NVDA" in affected_symbols  # noqa: S101

    # AAPL appears in the BUY insight (bullish) AND in the SELL insight as related (bearish).
    # The bearish direction should override bullish per the route logic.
    aapl_impact = next(h for h in body["affected_holdings"] if h["symbol"] == "AAPL")
    assert aapl_impact["impact_direction"] == "bearish"  # noqa: S101

    # NVDA is primary_symbol of the SELL insight -> bearish
    nvda_impact = next(h for h in body["affected_holdings"] if h["symbol"] == "NVDA")
    assert nvda_impact["impact_direction"] == "bearish"  # noqa: S101

    # Since both are bearish, overall_bearish_exposure should be > 0
    assert body["overall_bearish_exposure"] > 0  # noqa: S101
