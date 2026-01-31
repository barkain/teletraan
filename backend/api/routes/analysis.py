"""Analysis API endpoints for technical indicators, patterns, and anomalies."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from analysis.indicators import indicator_analyzer
from analysis.patterns import pattern_detector
from analysis.anomalies import anomaly_detector
from analysis.sectors import sector_analyzer, SECTOR_ETFS
from analysis.engine import analysis_engine
from models.stock import Stock
from models.price import PriceHistory
from models.insight import Insight
from schemas.analysis import (
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisSummaryResponse,
    AnomalyDetail,
    AnomalyResponse,
    IndicatorDetail,
    PatternDetail,
    PatternResponse,
    SectorAnalysisResponse,
    TechnicalAnalysisResponse,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


async def _get_stock_prices(
    db: AsyncSession,
    symbol: str,
    limit: int = 252
) -> tuple[Stock, list[dict[str, Any]]]:
    """Fetch stock and its price history."""
    # Get stock
    stock_query = select(Stock).where(Stock.symbol == symbol.upper())
    stock = (await db.execute(stock_query)).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Get price history
    price_query = (
        select(PriceHistory)
        .where(PriceHistory.stock_id == stock.id)
        .order_by(PriceHistory.date.asc())
        .limit(limit)
    )
    result = await db.execute(price_query)
    prices = result.scalars().all()

    if not prices:
        raise HTTPException(
            status_code=404,
            detail=f"No price data available for {symbol}"
        )

    # Convert to dict format expected by analysis modules
    price_data = [
        {
            "date": p.date,
            "open": p.open,
            "high": p.high,
            "low": p.low,
            "close": p.close,
            "volume": p.volume,
        }
        for p in prices
    ]

    return stock, price_data


@router.get("/technical/{symbol}", response_model=TechnicalAnalysisResponse)
async def get_technical_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    lookback: int = Query(100, ge=20, le=500, description="Number of periods to analyze"),
) -> TechnicalAnalysisResponse:
    """
    Get technical analysis for a stock.

    Returns technical indicator values and signals including RSI, MACD,
    Bollinger Bands, Stochastic, ATR, and moving averages.
    """
    stock, price_data = await _get_stock_prices(db, symbol, limit=lookback)

    # Run indicator analysis
    indicator_results = await indicator_analyzer.analyze_stock(price_data)
    signals = await indicator_analyzer.get_signals(indicator_results)

    # Check for crossovers if we have enough data
    crossovers = []
    if len(price_data) >= 200:
        closes = [p["close"] for p in price_data]
        crossovers = await indicator_analyzer.detect_crossovers(closes)

    # Build response
    indicators = [
        IndicatorDetail(
            indicator=detail["indicator"],
            value=detail["value"],
            signal=detail["signal"],
            strength=detail["strength"],
        )
        for detail in signals.get("details", [])
    ]

    return TechnicalAnalysisResponse(
        symbol=stock.symbol,
        analyzed_at=datetime.utcnow(),
        overall_signal=signals.get("overall_signal", "neutral"),
        confidence=signals.get("confidence", 0.0),
        bullish_count=signals.get("bullish_count", 0),
        bearish_count=signals.get("bearish_count", 0),
        neutral_count=signals.get("neutral_count", 0),
        indicators=indicators,
        crossovers=crossovers,
    )


@router.get("/patterns/{symbol}", response_model=PatternResponse)
async def get_patterns(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    min_confidence: float = Query(0.6, ge=0.0, le=1.0, description="Minimum pattern confidence"),
) -> PatternResponse:
    """
    Get detected chart patterns for a stock.

    Detects various patterns including double tops/bottoms, head and shoulders,
    golden/death crosses, breakouts, and continuation patterns.
    """
    stock, price_data = await _get_stock_prices(db, symbol, limit=300)

    # Configure pattern detector
    pattern_detector.min_confidence = min_confidence

    # Detect all patterns
    patterns = await pattern_detector.detect_all_patterns(stock.symbol, price_data)

    # Get support/resistance levels
    sr_levels = await pattern_detector.detect_support_resistance(price_data)

    # Get pattern summary
    summary = await pattern_detector.get_pattern_summary(patterns)

    # Build pattern details
    pattern_details = [
        PatternDetail(
            pattern_type=p.pattern_type.value,
            start_date=p.start_date,
            end_date=p.end_date,
            confidence=p.confidence,
            price_target=p.price_target,
            stop_loss=p.stop_loss,
            description=p.description,
            supporting_data=p.supporting_data,
        )
        for p in patterns
    ]

    return PatternResponse(
        symbol=stock.symbol,
        analyzed_at=datetime.utcnow(),
        total_patterns=summary.get("total_patterns", 0),
        bullish_patterns=summary.get("bullish_patterns", 0),
        bearish_patterns=summary.get("bearish_patterns", 0),
        neutral_patterns=summary.get("neutral_patterns", 0),
        overall_bias=summary.get("overall_bias", "neutral"),
        confidence=summary.get("confidence", 0.0),
        patterns=pattern_details,
        support_levels=sr_levels.get("support", []),
        resistance_levels=sr_levels.get("resistance", []),
    )


@router.get("/anomalies/{symbol}", response_model=AnomalyResponse)
async def get_anomalies(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> AnomalyResponse:
    """
    Get detected anomalies for a stock.

    Detects unusual market activity including volume spikes, price gaps,
    volatility surges, and unusual price moves.
    """
    stock, price_data = await _get_stock_prices(db, symbol, limit=50)

    # Detect all anomalies
    anomalies = await anomaly_detector.detect_all_anomalies(stock.symbol, price_data)

    # Count by severity
    severity_counts: dict[str, int] = {"info": 0, "warning": 0, "alert": 0}
    for anomaly in anomalies:
        severity_counts[anomaly.severity] = severity_counts.get(anomaly.severity, 0) + 1

    # Build anomaly details
    anomaly_details = [
        AnomalyDetail(
            anomaly_type=a.anomaly_type.value,
            detected_at=a.detected_at,
            severity=a.severity,
            value=a.value,
            expected_range=a.expected_range,
            z_score=a.z_score,
            description=a.description,
        )
        for a in anomalies
    ]

    return AnomalyResponse(
        symbol=stock.symbol,
        analyzed_at=datetime.utcnow(),
        total_anomalies=len(anomalies),
        anomalies_by_severity=severity_counts,
        anomalies=anomaly_details,
    )


@router.get("/sectors", response_model=SectorAnalysisResponse)
async def get_sector_analysis(
    db: AsyncSession = Depends(get_db),
) -> SectorAnalysisResponse:
    """
    Get sector rotation analysis.

    Analyzes sector performance, relative strength, rotation patterns,
    and identifies the current market cycle phase.
    """
    # Fetch sector ETF prices
    sector_prices: dict[str, list[dict[str, Any]]] = {}
    benchmark_prices: list[dict[str, Any]] = []

    for etf_symbol in SECTOR_ETFS.keys():
        stock_query = select(Stock).where(Stock.symbol == etf_symbol)
        stock = (await db.execute(stock_query)).scalar_one_or_none()

        if stock:
            price_query = (
                select(PriceHistory)
                .where(PriceHistory.stock_id == stock.id)
                .order_by(PriceHistory.date.desc())
                .limit(100)
            )
            result = await db.execute(price_query)
            prices = result.scalars().all()

            sector_prices[etf_symbol] = [
                {
                    "date": p.date.isoformat(),
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ]

    # Fetch SPY as benchmark
    spy_query = select(Stock).where(Stock.symbol == "SPY")
    spy_stock = (await db.execute(spy_query)).scalar_one_or_none()

    if spy_stock:
        spy_price_query = (
            select(PriceHistory)
            .where(PriceHistory.stock_id == spy_stock.id)
            .order_by(PriceHistory.date.desc())
            .limit(100)
        )
        spy_result = await db.execute(spy_price_query)
        spy_prices = spy_result.scalars().all()
        benchmark_prices = [
            {
                "date": p.date.isoformat(),
                "close": p.close,
                "volume": p.volume,
            }
            for p in spy_prices
        ]

    # Run sector analysis
    summary = await sector_analyzer.get_sector_summary(
        sector_prices,
        benchmark_prices,
        economic_data=None,  # Would come from economic data service
    )

    # Convert to response format
    from schemas.analysis import (
        RotationAnalysis,
        SectorInsight,
        SectorMetricDetail,
    )

    sector_metrics = {
        symbol: SectorMetricDetail(
            name=data["name"],
            daily_return=data["daily_return"],
            weekly_return=data["weekly_return"],
            monthly_return=data["monthly_return"],
            quarterly_return=data["quarterly_return"],
            ytd_return=data["ytd_return"],
            relative_strength=data["relative_strength"],
            momentum_score=data["momentum_score"],
            volatility=data["volatility"],
            volume_trend=data["volume_trend"],
        )
        for symbol, data in summary.get("sector_metrics", {}).items()
    }

    rotation_data = summary.get("rotation_analysis", {})
    rotation_analysis = RotationAnalysis(
        rotation_detected=rotation_data.get("rotation_detected", False),
        rotation_type=rotation_data.get("rotation_type"),
        leading_sectors=rotation_data.get("leading_sectors", []),
        lagging_sectors=rotation_data.get("lagging_sectors", []),
        signals=rotation_data.get("signals", []),
        cyclical_vs_defensive=rotation_data.get("cyclical_vs_defensive", {}),
    )

    insights = [
        SectorInsight(
            type=i["type"],
            priority=i["priority"],
            title=i["title"],
            description=i["description"],
            action=i["action"],
            sectors=i.get("sectors", []),
            warnings=i.get("warnings", []),
            divergences=i.get("divergences", []),
        )
        for i in summary.get("insights", [])
    ]

    return SectorAnalysisResponse(
        timestamp=datetime.fromisoformat(summary.get("timestamp", datetime.utcnow().isoformat())),
        market_phase=summary.get("market_phase", "unknown"),
        phase_description=summary.get("phase_description", ""),
        expected_leaders=summary.get("expected_leaders", []),
        sector_metrics=sector_metrics,
        rotation_analysis=rotation_analysis,
        insights=insights,
    )


@router.post("/run", response_model=AnalysisRunResponse)
async def trigger_analysis(
    background_tasks: BackgroundTasks,
    request: AnalysisRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> AnalysisRunResponse:
    """
    Trigger analysis run for specified symbols or all tracked stocks.

    The analysis runs in the background and generates insights that can
    be retrieved via the insights endpoints.
    """
    symbols = request.symbols if request else None

    # Get symbols to analyze
    if symbols:
        symbol_list = [s.upper() for s in symbols]
    else:
        # Get all active stocks
        query = select(Stock.symbol).where(Stock.is_active == True)  # noqa: E712
        result = await db.execute(query)
        symbol_list = [row[0] for row in result.all()]

    if not symbol_list:
        raise HTTPException(
            status_code=400,
            detail="No symbols found to analyze"
        )

    # Schedule background analysis
    background_tasks.add_task(
        analysis_engine.run_full_analysis,
        symbols=symbol_list,
    )

    return AnalysisRunResponse(
        status="started",
        message=f"Analysis started for {len(symbol_list)} symbols",
        symbols=symbol_list if symbols else "all",
        started_at=datetime.utcnow(),
    )


@router.get("/summary", response_model=AnalysisSummaryResponse)
async def get_analysis_summary(
    db: AsyncSession = Depends(get_db),
) -> AnalysisSummaryResponse:
    """
    Get summary of latest analysis results.

    Returns counts of detected patterns, anomalies, and insights
    along with the last analysis run timestamp.
    """
    # Get stocks count
    stocks_count = await db.scalar(
        select(func.count()).select_from(Stock).where(Stock.is_active == True)  # noqa: E712
    ) or 0

    # Get insights stats
    insights_query = select(Insight).where(Insight.is_active == True)  # noqa: E712
    insights_result = await db.execute(insights_query)
    insights = insights_result.scalars().all()

    # Count by type
    patterns_count = 0
    anomalies_count = 0
    patterns_by_type: dict[str, int] = {}
    anomalies_by_severity: dict[str, int] = {"info": 0, "warning": 0, "alert": 0}
    insights_by_type: dict[str, int] = {}
    last_run: datetime | None = None

    for insight in insights:
        # Track last run
        if last_run is None or insight.created_at > last_run:
            last_run = insight.created_at

        # Count by type
        insight_type = insight.insight_type
        insights_by_type[insight_type] = insights_by_type.get(insight_type, 0) + 1

        if insight_type == "pattern":
            patterns_count += 1
            # Would parse data_json for pattern type if needed
            patterns_by_type["detected"] = patterns_by_type.get("detected", 0) + 1
        elif insight_type == "anomaly":
            anomalies_count += 1
            severity = insight.severity
            anomalies_by_severity[severity] = anomalies_by_severity.get(severity, 0) + 1

    return AnalysisSummaryResponse(
        last_run=last_run,
        stocks_analyzed=stocks_count,
        patterns_detected=patterns_count,
        anomalies_detected=anomalies_count,
        insights_generated=len(insights),
        patterns_by_type=patterns_by_type,
        anomalies_by_severity=anomalies_by_severity,
        insights_by_type=insights_by_type,
    )
