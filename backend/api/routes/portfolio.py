"""Portfolio API routes for managing investment holdings."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import yfinance as yf

from api.deps import get_db
from models.portfolio import Portfolio, PortfolioHolding
from models.deep_insight import DeepInsight
from schemas.portfolio import (
    AffectedHolding,
    HoldingCreate,
    HoldingResponse,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioImpactResponse,
    PortfolioResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _fetch_current_price(symbol: str) -> float | None:
    """Fetch current market price for a symbol via yfinance.

    Uses run_in_executor to avoid blocking the async event loop.
    """
    def _get():
        try:
            ticker = yf.Ticker(symbol)
            return ticker.info.get("regularMarketPrice") or ticker.info.get("previousClose")
        except Exception:
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _get)


async def _get_or_create_portfolio(db: AsyncSession) -> Portfolio:
    """Get the single portfolio, creating it if it doesn't exist."""
    result = await db.execute(select(Portfolio).limit(1))
    portfolio = result.scalar_one_or_none()

    if not portfolio:
        portfolio = Portfolio(name="My Portfolio")
        db.add(portfolio)
        await db.commit()
        await db.refresh(portfolio)

    return portfolio


async def _enrich_holdings(
    holdings: list[PortfolioHolding],
) -> tuple[list[HoldingResponse], float]:
    """Enrich holdings with current prices and compute totals.

    Returns:
        Tuple of (enriched holding responses, total market value).
    """
    if not holdings:
        return [], 0.0

    # Fetch all prices in parallel
    price_tasks = [_fetch_current_price(h.symbol) for h in holdings]
    prices = await asyncio.gather(*price_tasks)

    total_value = 0.0
    enriched: list[dict] = []

    for holding, price in zip(holdings, prices):
        market_value = (price * holding.shares) if price else None
        cost_total = holding.cost_basis * holding.shares
        gain_loss = (market_value - cost_total) if market_value is not None else None
        gain_loss_pct = (
            ((gain_loss / cost_total) * 100) if gain_loss is not None and cost_total > 0 else None
        )

        if market_value is not None:
            total_value += market_value

        enriched.append({
            "holding": holding,
            "current_price": price,
            "market_value": market_value,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
        })

    # Compute allocation percentages
    responses: list[HoldingResponse] = []
    for item in enriched:
        h = item["holding"]
        allocation_pct = (
            ((item["market_value"] / total_value) * 100)
            if item["market_value"] is not None and total_value > 0
            else None
        )

        resp = HoldingResponse.model_validate(h)
        resp.current_price = item["current_price"]
        resp.market_value = item["market_value"]
        resp.gain_loss = item["gain_loss"]
        resp.gain_loss_pct = item["gain_loss_pct"]
        resp.allocation_pct = allocation_pct
        responses.append(resp)

    return responses, total_value


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    """Get the portfolio with enriched holdings.

    If no portfolio exists, auto-creates one named 'My Portfolio'.
    Each holding is enriched with current price, market value,
    gain/loss, and allocation percentage.
    """
    portfolio = await _get_or_create_portfolio(db)

    enriched_holdings, total_value = await _enrich_holdings(portfolio.holdings)

    total_cost = sum(h.shares * h.cost_basis for h in portfolio.holdings)
    total_gain_loss = (total_value - total_cost) if total_value > 0 else None
    total_gain_loss_pct = (
        ((total_gain_loss / total_cost) * 100)
        if total_gain_loss is not None and total_cost > 0
        else None
    )

    resp = PortfolioResponse.model_validate(portfolio)
    resp.holdings = enriched_holdings
    resp.total_value = total_value if total_value > 0 else None
    resp.total_cost = total_cost if total_cost > 0 else None
    resp.total_gain_loss = total_gain_loss
    resp.total_gain_loss_pct = total_gain_loss_pct

    return resp


@router.post("", response_model=PortfolioResponse)
async def create_portfolio(
    request: PortfolioCreate | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new portfolio if one does not already exist.

    Args:
        request: Optional portfolio name and description.
        db: Database session.

    Returns:
        The created or existing portfolio.
    """
    # Check if portfolio already exists
    result = await db.execute(select(Portfolio).limit(1))
    existing = result.scalar_one_or_none()

    if existing:
        return PortfolioResponse.model_validate(existing)

    portfolio = Portfolio(
        name=request.name if request else "My Portfolio",
        description=request.description if request else None,
    )
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)

    return PortfolioResponse.model_validate(portfolio)


@router.post("/holdings", response_model=HoldingResponse)
async def add_holding(
    request: HoldingCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new holding to the portfolio.

    Auto-creates the portfolio if it doesn't exist.
    Symbol is uppercased automatically.

    Args:
        request: Holding details (symbol, shares, cost_basis, notes).
        db: Database session.

    Returns:
        The created holding.
    """
    portfolio = await _get_or_create_portfolio(db)

    # Check if holding with same symbol already exists
    existing_query = select(PortfolioHolding).where(
        PortfolioHolding.portfolio_id == portfolio.id,
        PortfolioHolding.symbol == request.symbol.upper(),
    )
    existing = (await db.execute(existing_query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Holding for {request.symbol.upper()} already exists. Use PUT to update.",
        )

    holding = PortfolioHolding(
        portfolio_id=portfolio.id,
        symbol=request.symbol.upper(),
        shares=request.shares,
        cost_basis=request.cost_basis,
        notes=request.notes,
    )
    db.add(holding)
    await db.commit()
    await db.refresh(holding)

    return HoldingResponse.model_validate(holding)


@router.put("/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(
    holding_id: int,
    request: HoldingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing holding.

    Args:
        holding_id: The ID of the holding to update.
        request: Fields to update (shares, cost_basis, notes).
        db: Database session.

    Returns:
        The updated holding.
    """
    result = await db.execute(
        select(PortfolioHolding).where(PortfolioHolding.id == holding_id)
    )
    holding = result.scalar_one_or_none()

    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    if request.shares is not None:
        holding.shares = request.shares
    if request.cost_basis is not None:
        holding.cost_basis = request.cost_basis
    if request.notes is not None:
        holding.notes = request.notes

    await db.commit()
    await db.refresh(holding)

    return HoldingResponse.model_validate(holding)


@router.delete("/holdings/{holding_id}")
async def delete_holding(
    holding_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a holding from the portfolio.

    Args:
        holding_id: The ID of the holding to delete.
        db: Database session.

    Returns:
        Confirmation message.
    """
    result = await db.execute(
        select(PortfolioHolding).where(PortfolioHolding.id == holding_id)
    )
    holding = result.scalar_one_or_none()

    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    await db.delete(holding)
    await db.commit()

    return {"message": "Holding deleted"}


@router.get("/impact", response_model=PortfolioImpactResponse)
async def get_portfolio_impact(db: AsyncSession = Depends(get_db)):
    """Analyze how active deep insights affect portfolio holdings.

    For each active insight, checks if primary_symbol or related_symbols
    match any holding. Computes allocation exposure and impact direction
    (bullish/bearish/neutral) based on insight action.

    Returns:
        PortfolioImpactResponse with affected holdings and exposure breakdown.
    """
    portfolio = await _get_or_create_portfolio(db)

    if not portfolio.holdings:
        return PortfolioImpactResponse(
            portfolio_value=0.0,
            affected_holdings=[],
            overall_bullish_exposure=0.0,
            overall_bearish_exposure=0.0,
            insight_count=0,
        )

    # Enrich holdings to get market values and allocations
    enriched_holdings, total_value = await _enrich_holdings(portfolio.holdings)

    # Build symbol-to-holding map
    holding_map: dict[str, HoldingResponse] = {}
    for h in enriched_holdings:
        holding_map[h.symbol] = h

    # Fetch active insights (recent, ordered by created_at desc)
    insight_result = await db.execute(
        select(DeepInsight).order_by(DeepInsight.created_at.desc()).limit(100)
    )
    insights = insight_result.scalars().all()

    # Determine impact direction from action
    bullish_actions = {"STRONG_BUY", "BUY"}
    bearish_actions = {"SELL", "STRONG_SELL"}

    # Track affected holdings: symbol -> {allocation_pct, insight_ids, direction}
    affected: dict[str, dict] = {}

    for insight in insights:
        # Collect all symbols this insight is about
        insight_symbols: set[str] = set()
        if insight.primary_symbol:
            insight_symbols.add(insight.primary_symbol.upper())
        if insight.related_symbols:
            for s in insight.related_symbols:
                if isinstance(s, str):
                    insight_symbols.add(s.upper())

        # Determine direction
        if insight.action in bullish_actions:
            direction = "bullish"
        elif insight.action in bearish_actions:
            direction = "bearish"
        else:
            direction = "neutral"

        # Match against holdings
        for sym in insight_symbols:
            if sym in holding_map:
                if sym not in affected:
                    affected[sym] = {
                        "allocation_pct": holding_map[sym].allocation_pct or 0.0,
                        "insight_ids": [],
                        "impact_direction": direction,
                    }
                affected[sym]["insight_ids"].append(insight.id)
                # If any insight is bearish, mark as bearish; bullish otherwise
                if direction == "bearish":
                    affected[sym]["impact_direction"] = "bearish"
                elif direction == "bullish" and affected[sym]["impact_direction"] != "bearish":
                    affected[sym]["impact_direction"] = "bullish"

    # Build response
    affected_holdings = [
        AffectedHolding(
            symbol=sym,
            allocation_pct=data["allocation_pct"],
            insight_ids=data["insight_ids"],
            impact_direction=data["impact_direction"],
        )
        for sym, data in affected.items()
    ]

    overall_bullish = sum(
        h.allocation_pct for h in affected_holdings if h.impact_direction == "bullish"
    )
    overall_bearish = sum(
        h.allocation_pct for h in affected_holdings if h.impact_direction == "bearish"
    )

    return PortfolioImpactResponse(
        portfolio_value=total_value,
        affected_holdings=affected_holdings,
        overall_bullish_exposure=overall_bullish,
        overall_bearish_exposure=overall_bearish,
        insight_count=len(insights),
    )
