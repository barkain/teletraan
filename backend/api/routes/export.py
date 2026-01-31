"""Export API endpoints for downloading stock data and insights."""

import csv
import json
from datetime import date, datetime, timezone
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.insight import Insight
from models.price import PriceHistory
from models.stock import Stock
from models.indicator import TechnicalIndicator

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/stocks/{symbol}/csv")
async def export_stock_csv(
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Export stock price history as CSV."""
    # Get the stock
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

    query = query.order_by(PriceHistory.date.asc())

    result = await db.execute(query)
    prices = result.scalars().all()

    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Adjusted Close"])

    for price in prices:
        writer.writerow([
            price.date.isoformat(),
            price.open,
            price.high,
            price.low,
            price.close,
            price.volume,
            price.adjusted_close or "",
        ])

    output.seek(0)
    filename = f"{symbol.upper()}_prices"
    if start_date:
        filename += f"_from_{start_date.isoformat()}"
    if end_date:
        filename += f"_to_{end_date.isoformat()}"
    filename += ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/stocks/{symbol}/json")
async def export_stock_json(
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    include_indicators: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Export stock data as JSON."""
    # Get the stock
    stock_query = select(Stock).where(Stock.symbol == symbol.upper())
    stock = (await db.execute(stock_query)).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Build price history query
    price_query = select(PriceHistory).where(PriceHistory.stock_id == stock.id)

    if start_date:
        price_query = price_query.where(PriceHistory.date >= start_date)
    if end_date:
        price_query = price_query.where(PriceHistory.date <= end_date)

    price_query = price_query.order_by(PriceHistory.date.asc())

    result = await db.execute(price_query)
    prices = result.scalars().all()

    # Build response data
    data = {
        "symbol": stock.symbol,
        "name": stock.name,
        "sector": stock.sector,
        "industry": stock.industry,
        "market_cap": stock.market_cap,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "price_history": [
            {
                "date": price.date.isoformat(),
                "open": price.open,
                "high": price.high,
                "low": price.low,
                "close": price.close,
                "volume": price.volume,
                "adjusted_close": price.adjusted_close,
            }
            for price in prices
        ],
    }

    # Include technical indicators if requested
    if include_indicators:
        indicator_query = select(TechnicalIndicator).where(
            TechnicalIndicator.stock_id == stock.id
        )

        if start_date:
            indicator_query = indicator_query.where(TechnicalIndicator.date >= start_date)
        if end_date:
            indicator_query = indicator_query.where(TechnicalIndicator.date <= end_date)

        indicator_query = indicator_query.order_by(TechnicalIndicator.date.asc())

        indicator_result = await db.execute(indicator_query)
        indicators = indicator_result.scalars().all()

        data["technical_indicators"] = [
            {
                "date": ind.date.isoformat(),
                "type": ind.indicator_type,
                "value": ind.value,
                "metadata": json.loads(ind.metadata_json) if ind.metadata_json else None,
            }
            for ind in indicators
        ]

    output = json.dumps(data, indent=2)
    filename = f"{symbol.upper()}_data"
    if start_date:
        filename += f"_from_{start_date.isoformat()}"
    if end_date:
        filename += f"_to_{end_date.isoformat()}"
    filename += ".json"

    return StreamingResponse(
        iter([output]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/insights/csv")
async def export_insights_csv(
    insight_type: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Export insights as CSV."""
    query = select(Insight).where(Insight.is_active == True)  # noqa: E712
    query = query.where(
        (Insight.expires_at.is_(None)) | (Insight.expires_at > datetime.now(timezone.utc))
    )

    if insight_type:
        query = query.where(Insight.insight_type == insight_type)
    if severity:
        query = query.where(Insight.severity == severity)
    if symbol:
        query = query.join(Stock).where(Stock.symbol == symbol.upper())

    query = query.order_by(Insight.created_at.desc())

    result = await db.execute(query)
    insights = result.scalars().all()

    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Type",
        "Severity",
        "Title",
        "Description",
        "Confidence",
        "Created At",
        "Expires At",
    ])

    for insight in insights:
        writer.writerow([
            insight.id,
            insight.insight_type,
            insight.severity,
            insight.title,
            insight.description,
            insight.confidence,
            insight.created_at.isoformat() if insight.created_at else "",
            insight.expires_at.isoformat() if insight.expires_at else "",
        ])

    output.seek(0)
    filename = "insights"
    if insight_type:
        filename += f"_{insight_type}"
    if severity:
        filename += f"_{severity}"
    if symbol:
        filename += f"_{symbol.upper()}"
    filename += ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/insights/json")
async def export_insights_json(
    insight_type: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    include_annotations: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Export insights as JSON."""
    query = select(Insight).where(Insight.is_active == True)  # noqa: E712
    query = query.where(
        (Insight.expires_at.is_(None)) | (Insight.expires_at > datetime.now(timezone.utc))
    )

    if insight_type:
        query = query.where(Insight.insight_type == insight_type)
    if severity:
        query = query.where(Insight.severity == severity)
    if symbol:
        query = query.join(Stock).where(Stock.symbol == symbol.upper())

    query = query.order_by(Insight.created_at.desc())

    result = await db.execute(query)
    insights = result.scalars().all()

    # Build response data
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "insight_type": insight_type,
            "severity": severity,
            "symbol": symbol,
        },
        "total": len(insights),
        "insights": [],
    }

    for insight in insights:
        insight_data = {
            "id": insight.id,
            "type": insight.insight_type,
            "severity": insight.severity,
            "title": insight.title,
            "description": insight.description,
            "confidence": insight.confidence,
            "data": json.loads(insight.data_json) if insight.data_json else None,
            "created_at": insight.created_at.isoformat() if insight.created_at else None,
            "expires_at": insight.expires_at.isoformat() if insight.expires_at else None,
        }

        if include_annotations and insight.annotations:
            insight_data["annotations"] = [
                {
                    "id": ann.id,
                    "note": ann.note,
                    "created_at": ann.created_at.isoformat() if ann.created_at else None,
                }
                for ann in insight.annotations
            ]

        data["insights"].append(insight_data)

    output = json.dumps(data, indent=2)
    filename = "insights"
    if insight_type:
        filename += f"_{insight_type}"
    if severity:
        filename += f"_{severity}"
    if symbol:
        filename += f"_{symbol.upper()}"
    filename += ".json"

    return StreamingResponse(
        iter([output]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/analysis/{symbol}")
async def export_analysis(
    symbol: str,
    format: str = Query("json", enum=["json", "csv"]),
    start_date: date | None = None,
    end_date: date | None = None,
    include_indicators: bool = True,
    include_insights: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Export complete analysis for a stock including price history, indicators, and insights."""
    # Get the stock
    stock_query = select(Stock).where(Stock.symbol == symbol.upper())
    stock = (await db.execute(stock_query)).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Build price history query
    price_query = select(PriceHistory).where(PriceHistory.stock_id == stock.id)
    if start_date:
        price_query = price_query.where(PriceHistory.date >= start_date)
    if end_date:
        price_query = price_query.where(PriceHistory.date <= end_date)
    price_query = price_query.order_by(PriceHistory.date.asc())

    price_result = await db.execute(price_query)
    prices = price_result.scalars().all()

    if format == "json":
        data = {
            "symbol": stock.symbol,
            "name": stock.name,
            "sector": stock.sector,
            "industry": stock.industry,
            "market_cap": stock.market_cap,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "date_range": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None,
            },
            "price_history": [
                {
                    "date": price.date.isoformat(),
                    "open": price.open,
                    "high": price.high,
                    "low": price.low,
                    "close": price.close,
                    "volume": price.volume,
                    "adjusted_close": price.adjusted_close,
                }
                for price in prices
            ],
        }

        if include_indicators:
            indicator_query = select(TechnicalIndicator).where(
                TechnicalIndicator.stock_id == stock.id
            )
            if start_date:
                indicator_query = indicator_query.where(
                    TechnicalIndicator.date >= start_date
                )
            if end_date:
                indicator_query = indicator_query.where(TechnicalIndicator.date <= end_date)
            indicator_query = indicator_query.order_by(TechnicalIndicator.date.asc())

            indicator_result = await db.execute(indicator_query)
            indicators = indicator_result.scalars().all()

            data["technical_indicators"] = [
                {
                    "date": ind.date.isoformat(),
                    "type": ind.indicator_type,
                    "value": ind.value,
                    "metadata": json.loads(ind.metadata_json) if ind.metadata_json else None,
                }
                for ind in indicators
            ]

        if include_insights:
            insight_query = (
                select(Insight)
                .where(Insight.stock_id == stock.id)
                .where(Insight.is_active == True)  # noqa: E712
                .order_by(Insight.created_at.desc())
            )

            insight_result = await db.execute(insight_query)
            insights = insight_result.scalars().all()

            data["insights"] = [
                {
                    "id": insight.id,
                    "type": insight.insight_type,
                    "severity": insight.severity,
                    "title": insight.title,
                    "description": insight.description,
                    "confidence": insight.confidence,
                    "created_at": (
                        insight.created_at.isoformat() if insight.created_at else None
                    ),
                }
                for insight in insights
            ]

        output = json.dumps(data, indent=2)
        filename = f"{symbol.upper()}_analysis"
        if start_date:
            filename += f"_from_{start_date.isoformat()}"
        if end_date:
            filename += f"_to_{end_date.isoformat()}"
        filename += ".json"

        return StreamingResponse(
            iter([output]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    else:
        # CSV format - flatten data into rows
        output = StringIO()
        writer = csv.writer(output)

        # Write stock info header
        writer.writerow(["# Stock Information"])
        writer.writerow(["Symbol", "Name", "Sector", "Industry", "Market Cap"])
        writer.writerow([
            stock.symbol,
            stock.name,
            stock.sector or "",
            stock.industry or "",
            stock.market_cap or "",
        ])
        writer.writerow([])

        # Write price history
        writer.writerow(["# Price History"])
        writer.writerow([
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Adjusted Close",
        ])
        for price in prices:
            writer.writerow([
                price.date.isoformat(),
                price.open,
                price.high,
                price.low,
                price.close,
                price.volume,
                price.adjusted_close or "",
            ])
        writer.writerow([])

        if include_indicators:
            indicator_query = select(TechnicalIndicator).where(
                TechnicalIndicator.stock_id == stock.id
            )
            if start_date:
                indicator_query = indicator_query.where(
                    TechnicalIndicator.date >= start_date
                )
            if end_date:
                indicator_query = indicator_query.where(TechnicalIndicator.date <= end_date)
            indicator_query = indicator_query.order_by(TechnicalIndicator.date.asc())

            indicator_result = await db.execute(indicator_query)
            indicators = indicator_result.scalars().all()

            writer.writerow(["# Technical Indicators"])
            writer.writerow(["Date", "Indicator Type", "Value"])
            for ind in indicators:
                writer.writerow([ind.date.isoformat(), ind.indicator_type, ind.value])
            writer.writerow([])

        if include_insights:
            insight_query = (
                select(Insight)
                .where(Insight.stock_id == stock.id)
                .where(Insight.is_active == True)  # noqa: E712
                .order_by(Insight.created_at.desc())
            )

            insight_result = await db.execute(insight_query)
            insights = insight_result.scalars().all()

            writer.writerow(["# Insights"])
            writer.writerow([
                "ID",
                "Type",
                "Severity",
                "Title",
                "Description",
                "Confidence",
                "Created At",
            ])
            for insight in insights:
                writer.writerow([
                    insight.id,
                    insight.insight_type,
                    insight.severity,
                    insight.title,
                    insight.description,
                    insight.confidence,
                    insight.created_at.isoformat() if insight.created_at else "",
                ])

        output.seek(0)
        filename = f"{symbol.upper()}_analysis"
        if start_date:
            filename += f"_from_{start_date.isoformat()}"
        if end_date:
            filename += f"_to_{end_date.isoformat()}"
        filename += ".csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
