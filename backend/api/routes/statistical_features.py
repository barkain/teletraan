"""API routes for statistical features endpoints."""

import logging
from datetime import date as date_type
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from analysis.statistical_calculator import StatisticalFeatureCalculator
from models.statistical_feature import StatisticalFeature
from models.stock import Stock
from schemas.statistical_feature import (
    ActiveSignalResponse,
    ActiveSignalsResponse,
    ComputeFeaturesRequest,
    ComputeFeaturesResponse,
    StatisticalFeatureResponse,
    StatisticalFeaturesListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/features", tags=["features"])


# Signal strength thresholds based on percentile
STRONG_THRESHOLD = 85.0
MODERATE_THRESHOLD = 65.0


def _determine_signal_strength(percentile: float | None, value: float) -> str:
    """Determine signal strength based on percentile or absolute value.

    Args:
        percentile: Percentile ranking (0-100) if available.
        value: Absolute feature value.

    Returns:
        Strength classification: "strong", "moderate", or "weak".
    """
    if percentile is not None:
        # Use percentile distance from 50 (neutral)
        distance = abs(percentile - 50)
        if distance >= STRONG_THRESHOLD - 50:
            return "strong"
        elif distance >= MODERATE_THRESHOLD - 50:
            return "moderate"
        else:
            return "weak"
    else:
        # Fallback to absolute value magnitude
        abs_value = abs(value)
        if abs_value >= 5.0:
            return "strong"
        elif abs_value >= 2.0:
            return "moderate"
        else:
            return "weak"


# NOTE: /signals route MUST be defined BEFORE /{symbol} to prevent FastAPI
# from interpreting "signals" as a symbol parameter
@router.get("/signals", response_model=ActiveSignalsResponse)
async def get_active_signals(
    signal_type: str | None = Query(
        default=None,
        description="Filter by signal type: 'bullish', 'bearish', 'oversold', 'overbought', etc.",
    ),
    min_strength: Literal["weak", "moderate", "strong"] | None = Query(
        default=None,
        description="Minimum signal strength filter.",
    ),
    db: AsyncSession = Depends(get_db),
) -> ActiveSignalsResponse:
    """Get all active signals across the watchlist.

    Retrieves signals from the most recent calculation date that indicate
    actionable conditions (not neutral signals).

    Args:
        signal_type: Optional filter for specific signal types.
        min_strength: Optional minimum strength filter.
        db: Database session.

    Returns:
        ActiveSignalsResponse with all matching signals.
    """
    # Get the latest calculation date across all symbols
    latest_date_query = (
        select(StatisticalFeature.calculation_date)
        .order_by(StatisticalFeature.calculation_date.desc())
        .limit(1)
    )
    result = await db.execute(latest_date_query)
    latest_date = result.scalar_one_or_none()

    if latest_date is None:
        return ActiveSignalsResponse(
            signals=[],
            count=0,
            as_of=datetime.now(),
        )

    # Build query for non-neutral signals
    query = select(StatisticalFeature).where(
        StatisticalFeature.calculation_date == latest_date,
        StatisticalFeature.signal != "neutral",
        StatisticalFeature.signal != "normal",
        StatisticalFeature.signal != "market_beta",
    )

    if signal_type:
        query = query.where(StatisticalFeature.signal == signal_type.lower())

    result = await db.execute(query)
    features = result.scalars().all()

    # Convert to active signals with strength
    signals: list[ActiveSignalResponse] = []
    strength_order = {"weak": 0, "moderate": 1, "strong": 2}
    min_strength_value = strength_order.get(min_strength, 0) if min_strength else 0

    for feature in features:
        strength = _determine_signal_strength(feature.percentile, feature.value)

        # Apply strength filter
        if strength_order.get(strength, 0) >= min_strength_value:
            signals.append(
                ActiveSignalResponse(
                    symbol=feature.symbol,
                    feature_type=feature.feature_type,
                    signal=feature.signal,
                    value=feature.value,
                    strength=strength,
                )
            )

    # Sort by strength (descending) then symbol
    signals.sort(key=lambda s: (-strength_order.get(s.strength, 0), s.symbol))

    return ActiveSignalsResponse(
        signals=signals,
        count=len(signals),
        as_of=datetime.now(),
    )


@router.get("/{symbol}", response_model=StatisticalFeaturesListResponse)
async def get_features_for_symbol(
    symbol: str,
    calculation_date: date_type | None = Query(
        default=None,
        description="Date for features. Defaults to latest available.",
    ),
    db: AsyncSession = Depends(get_db),
) -> StatisticalFeaturesListResponse:
    """Get all statistical features for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL").
        calculation_date: Optional date for features. Uses latest if not provided.
        db: Database session.

    Returns:
        StatisticalFeaturesListResponse with all features for the symbol.

    Raises:
        HTTPException: If no features found for the symbol.
    """
    symbol = symbol.upper()

    # Build query
    query = select(StatisticalFeature).where(StatisticalFeature.symbol == symbol)

    if calculation_date:
        query = query.where(StatisticalFeature.calculation_date == calculation_date)
    else:
        # Get latest calculation date for this symbol
        latest_date_query = (
            select(StatisticalFeature.calculation_date)
            .where(StatisticalFeature.symbol == symbol)
            .order_by(StatisticalFeature.calculation_date.desc())
            .limit(1)
        )
        result = await db.execute(latest_date_query)
        latest_date = result.scalar_one_or_none()

        if latest_date is None:
            raise HTTPException(
                status_code=404,
                detail=f"No features found for symbol {symbol}",
            )

        query = query.where(StatisticalFeature.calculation_date == latest_date)
        calculation_date = latest_date

    query = query.order_by(StatisticalFeature.feature_type)
    result = await db.execute(query)
    features = result.scalars().all()

    if not features:
        raise HTTPException(
            status_code=404,
            detail=f"No features found for symbol {symbol}",
        )

    return StatisticalFeaturesListResponse(
        symbol=symbol,
        features=[StatisticalFeatureResponse.model_validate(f) for f in features],
        calculation_date=calculation_date,
    )


@router.get("/{symbol}/{feature_type}", response_model=StatisticalFeatureResponse)
async def get_specific_feature(
    symbol: str,
    feature_type: str,
    calculation_date: date_type | None = Query(
        default=None,
        description="Date for the feature. Defaults to latest available.",
    ),
    db: AsyncSession = Depends(get_db),
) -> StatisticalFeatureResponse:
    """Get a specific statistical feature for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL").
        feature_type: Type of feature (e.g., "momentum_roc_5d", "zscore_20d").
        calculation_date: Optional date for the feature. Uses latest if not provided.
        db: Database session.

    Returns:
        StatisticalFeatureResponse for the requested feature.

    Raises:
        HTTPException: If feature not found.
    """
    symbol = symbol.upper()
    feature_type = feature_type.lower()

    # Build query
    query = select(StatisticalFeature).where(
        StatisticalFeature.symbol == symbol,
        StatisticalFeature.feature_type == feature_type,
    )

    if calculation_date:
        query = query.where(StatisticalFeature.calculation_date == calculation_date)
    else:
        query = query.order_by(StatisticalFeature.calculation_date.desc())

    query = query.limit(1)
    result = await db.execute(query)
    feature = result.scalar_one_or_none()

    if feature is None:
        raise HTTPException(
            status_code=404,
            detail=f"Feature '{feature_type}' not found for symbol {symbol}",
        )

    return StatisticalFeatureResponse.model_validate(feature)


@router.post("/compute", response_model=ComputeFeaturesResponse)
async def compute_features(
    request: ComputeFeaturesRequest,
    db: AsyncSession = Depends(get_db),
) -> ComputeFeaturesResponse:
    """Trigger statistical feature computation for specified symbols.

    This endpoint initiates the computation of all statistical features
    for the provided symbols. Features computed include momentum, z-scores,
    volatility regime, seasonality, and cross-sectional rankings.

    Args:
        request: Request containing list of symbols to compute.
        db: Database session.

    Returns:
        ComputeFeaturesResponse with computation status.

    Raises:
        HTTPException: If symbols list is empty or computation fails.
    """
    if not request.symbols:
        raise HTTPException(
            status_code=400,
            detail="At least one symbol must be provided",
        )

    # Normalize symbols
    symbols = [s.upper().strip() for s in request.symbols if s.strip()]

    if not symbols:
        raise HTTPException(
            status_code=400,
            detail="At least one valid symbol must be provided",
        )

    # Validate that symbols exist in the database
    valid_symbols: list[str] = []
    for symbol in symbols:
        stock_query = select(Stock).where(Stock.symbol == symbol)
        result = await db.execute(stock_query)
        stock = result.scalar_one_or_none()
        if stock:
            valid_symbols.append(symbol)
        else:
            logger.warning(f"Symbol {symbol} not found in database, skipping")

    if not valid_symbols:
        raise HTTPException(
            status_code=404,
            detail="None of the provided symbols were found in the database",
        )

    try:
        logger.info(f"Starting feature computation for {len(valid_symbols)} symbols: {valid_symbols}")

        calculator = StatisticalFeatureCalculator(db)
        features = await calculator.compute_all_features(valid_symbols)
        await db.commit()

        logger.info(f"Feature computation complete: {len(features)} features computed")

        return ComputeFeaturesResponse(
            status="completed",
            symbols=valid_symbols,
            message=f"Computed {len(features)} features for {len(valid_symbols)} symbols",
        )

    except Exception as e:
        logger.error(f"Feature computation failed: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Feature computation failed: {str(e)}",
        )
