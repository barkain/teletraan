"""Stock-related API endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.stock import Stock
from models.price import PriceHistory
from schemas.stock import PriceHistoryResponse, StockListResponse, StockResponse

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=StockListResponse)
async def list_stocks(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    sector: str | None = None,
    search: str | None = None,
    active_only: bool = True,
):
    """List all tracked stocks with pagination and filtering."""
    query = select(Stock)

    if active_only:
        query = query.where(Stock.is_active == True)  # noqa: E712
    if sector:
        query = query.where(Stock.sector == sector)
    if search:
        query = query.where(
            Stock.symbol.ilike(f"%{search}%") | Stock.name.ilike(f"%{search}%")
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Get paginated results
    query = query.offset(skip).limit(limit).order_by(Stock.symbol)
    result = await db.execute(query)
    stocks = result.scalars().all()

    return StockListResponse(stocks=stocks, total=total or 0)


@router.get("/sectors/list")
async def list_sectors(db: AsyncSession = Depends(get_db)):
    """Get list of all sectors."""
    query = select(Stock.sector).where(Stock.sector.isnot(None)).distinct()
    result = await db.execute(query)
    sectors = [row[0] for row in result.all()]
    return {"sectors": sorted(sectors)}


@router.get("/{symbol}", response_model=StockResponse)
async def get_stock(symbol: str, db: AsyncSession = Depends(get_db)):
    """Get stock details by symbol."""
    query = select(Stock).where(Stock.symbol == symbol.upper())
    result = await db.execute(query)
    stock = result.scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    return stock


@router.get("/{symbol}/history", response_model=list[PriceHistoryResponse])
async def get_price_history(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(252, ge=1, le=1000),  # ~1 year of trading days
):
    """Get price history for a stock."""
    # First get the stock
    stock_query = select(Stock).where(Stock.symbol == symbol.upper())
    stock = (await db.execute(stock_query)).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Build price history query
    query = select(PriceHistory).where(PriceHistory.stock_id == stock.id)

    if start_date:
        query = query.where(PriceHistory.date >= start_date)
    if end_date:
        query = query.where(PriceHistory.date <= end_date)

    query = query.order_by(PriceHistory.date.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
