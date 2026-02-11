"""Knowledge API routes for patterns, themes, and track record.

This module provides endpoints for accessing institutional memory:
- Validated market patterns
- Conversation themes
- Historical track record
"""

from collections import Counter
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.knowledge_pattern import KnowledgePattern
from models.conversation_theme import ConversationTheme
from models.insight_outcome import InsightOutcome
from models.deep_insight import DeepInsight
from schemas.knowledge import (
    ConversationThemeListResponse,
    ConversationThemeResponse,
    KnowledgePatternListResponse,
    KnowledgePatternResponse,
    MonthlyDataPoint,
    MonthlyTrendResponse,
    PatternsSummaryResponse,
    TrackRecordResponse,
    TypeBreakdown,
)

router = APIRouter()


@router.get("/patterns", response_model=KnowledgePatternListResponse)
async def list_patterns(
    db: AsyncSession = Depends(get_db),
    pattern_type: str | None = Query(
        default=None, description="Filter by pattern type"
    ),
    min_success_rate: float = Query(
        default=0.0, ge=0.0, le=1.0, description="Minimum success rate threshold"
    ),
    is_active: bool = Query(default=True, description="Filter by active status"),
    limit: int = Query(default=20, le=100, description="Maximum results"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
) -> KnowledgePatternListResponse:
    """List validated knowledge patterns.

    Returns patterns filtered by type, success rate, and active status.
    Patterns are sorted by success rate descending.
    """
    # Build query conditions
    conditions = [
        KnowledgePattern.is_active == is_active,
        KnowledgePattern.success_rate >= min_success_rate,
    ]

    if pattern_type:
        conditions.append(KnowledgePattern.pattern_type == pattern_type)

    # Count total matching patterns
    count_query = select(func.count()).select_from(KnowledgePattern).where(and_(*conditions))
    total = await db.scalar(count_query) or 0

    # Fetch patterns with pagination
    query = (
        select(KnowledgePattern)
        .where(and_(*conditions))
        .order_by(KnowledgePattern.success_rate.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    patterns = result.scalars().all()

    return KnowledgePatternListResponse(
        items=[KnowledgePatternResponse.model_validate(p) for p in patterns],
        total=total,
    )


@router.get("/patterns/matching", response_model=KnowledgePatternListResponse)
async def get_matching_patterns(
    db: AsyncSession = Depends(get_db),
    symbols: list[str] = Query(default=[], description="Symbols to check"),
    rsi: float | None = Query(default=None, description="Current RSI value"),
    vix: float | None = Query(default=None, description="Current VIX level"),
    volume_surge_pct: float | None = Query(
        default=None, description="Volume surge percentage"
    ),
    sector_momentum: float | None = Query(
        default=None, description="Sector momentum score"
    ),
) -> KnowledgePatternListResponse:
    """Get patterns matching current market conditions.

    Evaluates trigger conditions against provided metrics and returns
    patterns whose conditions are satisfied.
    """
    # Build current conditions dict
    current_conditions: dict[str, Any] = {}
    if rsi is not None:
        current_conditions["rsi"] = rsi
    if vix is not None:
        current_conditions["vix"] = vix
    if volume_surge_pct is not None:
        current_conditions["volume_surge_pct"] = volume_surge_pct
    if sector_momentum is not None:
        current_conditions["sector_momentum"] = sector_momentum

    # Query active patterns with minimum success rate
    query = (
        select(KnowledgePattern)
        .where(
            and_(
                KnowledgePattern.is_active == True,  # noqa: E712
                KnowledgePattern.success_rate >= 0.5,
            )
        )
        .order_by(KnowledgePattern.success_rate.desc())
    )

    result = await db.execute(query)
    all_patterns = result.scalars().all()

    # Filter patterns by matching trigger conditions
    matching_patterns: list[KnowledgePattern] = []

    for pattern in all_patterns:
        if _matches_conditions(pattern.trigger_conditions, current_conditions):
            matching_patterns.append(pattern)
            if len(matching_patterns) >= 10:
                break

    return KnowledgePatternListResponse(
        items=[KnowledgePatternResponse.model_validate(p) for p in matching_patterns],
        total=len(matching_patterns),
    )


def _matches_conditions(
    trigger_conditions: dict[str, Any],
    current_conditions: dict[str, Any],
) -> bool:
    """Check if current conditions match pattern trigger conditions.

    Supports comparison operators embedded in condition names:
    - *_below: Matches if current value < trigger value
    - *_above: Matches if current value > trigger value
    - *_equals: Matches if current value == trigger value
    - Default: Matches if current value >= trigger value
    """
    if not trigger_conditions:
        return False

    for condition_key, trigger_value in trigger_conditions.items():
        if condition_key.endswith("_below"):
            metric_name = condition_key.replace("_below", "")
            current_value = current_conditions.get(metric_name)
            if current_value is None or current_value >= trigger_value:
                return False
        elif condition_key.endswith("_above"):
            metric_name = condition_key.replace("_above", "")
            current_value = current_conditions.get(metric_name)
            if current_value is None or current_value <= trigger_value:
                return False
        elif condition_key.endswith("_equals"):
            metric_name = condition_key.replace("_equals", "")
            current_value = current_conditions.get(metric_name)
            if current_value is None or current_value != trigger_value:
                return False
        else:
            current_value = current_conditions.get(condition_key)
            if current_value is None or current_value < trigger_value:
                return False

    return True


# Mapping from PatternType enum values to user-friendly summary keys
_TYPE_KEY_MAP: dict[str, str] = {
    "TECHNICAL_SETUP": "technical",
    "MACRO_CORRELATION": "macro",
    "SECTOR_ROTATION": "sector_rotation",
    "EARNINGS_PATTERN": "earnings",
    "SEASONALITY": "seasonality",
    "CROSS_ASSET": "correlation",
}


@router.get("/patterns/summary", response_model=PatternsSummaryResponse)
async def get_patterns_summary(
    db: AsyncSession = Depends(get_db),
) -> PatternsSummaryResponse:
    """Get aggregate summary statistics across all knowledge patterns.

    Returns total/active counts, average success rate, breakdowns by type
    and lifecycle status, and the most frequently referenced symbols and sectors.
    """
    # Fetch all patterns in a single query
    result = await db.execute(select(KnowledgePattern))
    patterns = list(result.scalars().all())

    if not patterns:
        return PatternsSummaryResponse(
            total=0,
            active=0,
            avg_success_rate=0.0,
            by_type={},
            by_lifecycle={},
            top_symbols=[],
            top_sectors=[],
        )

    total = len(patterns)
    active = sum(1 for p in patterns if p.is_active)

    # Average success rate
    avg_success_rate = round(
        sum(p.success_rate for p in patterns) / total, 4
    )

    # Breakdown by pattern type
    by_type: dict[str, int] = {}
    for p in patterns:
        key = _TYPE_KEY_MAP.get(p.pattern_type, p.pattern_type.lower())
        by_type[key] = by_type.get(key, 0) + 1

    # Breakdown by lifecycle status
    by_lifecycle: dict[str, int] = {}
    for p in patterns:
        status = p.lifecycle_status or "unknown"
        by_lifecycle[status] = by_lifecycle.get(status, 0) + 1

    # Top symbols (across all patterns' related_symbols JSON)
    symbol_counter: Counter[str] = Counter()
    for p in patterns:
        if p.related_symbols:
            symbol_counter.update(p.related_symbols)
    top_symbols = [sym for sym, _ in symbol_counter.most_common(10)]

    # Top sectors (across all patterns' related_sectors JSON)
    sector_counter: Counter[str] = Counter()
    for p in patterns:
        if p.related_sectors:
            sector_counter.update(p.related_sectors)
    top_sectors = [sec for sec, _ in sector_counter.most_common(5)]

    return PatternsSummaryResponse(
        total=total,
        active=active,
        avg_success_rate=avg_success_rate,
        by_type=by_type,
        by_lifecycle=by_lifecycle,
        top_symbols=top_symbols,
        top_sectors=top_sectors,
    )


@router.get("/patterns/{pattern_id}", response_model=KnowledgePatternResponse)
async def get_pattern(
    pattern_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> KnowledgePatternResponse:
    """Get a specific knowledge pattern by ID."""
    result = await db.execute(
        select(KnowledgePattern).where(KnowledgePattern.id == pattern_id)
    )
    pattern = result.scalar_one_or_none()

    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return KnowledgePatternResponse.model_validate(pattern)


@router.get("/themes", response_model=ConversationThemeListResponse)
async def list_themes(
    db: AsyncSession = Depends(get_db),
    theme_type: str | None = Query(default=None, description="Filter by theme type"),
    min_relevance: float = Query(
        default=0.3, ge=0.0, le=1.0, description="Minimum relevance threshold"
    ),
    sector: str | None = Query(default=None, description="Filter by related sector"),
    limit: int = Query(default=20, le=100, description="Maximum results"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
) -> ConversationThemeListResponse:
    """List active conversation themes.

    Returns themes filtered by type, relevance, and sector.
    Themes are sorted by current relevance descending.
    """
    # Build base conditions
    conditions = [
        ConversationTheme.is_active == True,  # noqa: E712
        ConversationTheme.current_relevance >= min_relevance,
    ]

    if theme_type:
        conditions.append(ConversationTheme.theme_type == theme_type)

    # Fetch themes (count computed after sector filter in post-processing)
    query = (
        select(ConversationTheme)
        .where(and_(*conditions))
        .order_by(ConversationTheme.current_relevance.desc())
    )
    result = await db.execute(query)
    themes = list(result.scalars().all())

    # Apply sector filter in post-processing (JSON field)
    if sector:
        themes = [
            t for t in themes
            if t.related_sectors and sector in t.related_sectors
        ]

    total = len(themes)

    # Apply pagination
    paginated_themes = themes[offset : offset + limit]

    return ConversationThemeListResponse(
        items=[ConversationThemeResponse.model_validate(t) for t in paginated_themes],
        total=total,
    )


@router.get("/themes/{theme_id}", response_model=ConversationThemeResponse)
async def get_theme(
    theme_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ConversationThemeResponse:
    """Get a specific conversation theme by ID."""
    result = await db.execute(
        select(ConversationTheme).where(ConversationTheme.id == theme_id)
    )
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    return ConversationThemeResponse.model_validate(theme)


@router.get("/track-record", response_model=TrackRecordResponse)
async def get_track_record(
    db: AsyncSession = Depends(get_db),
    insight_type: str | None = Query(default=None, description="Filter by insight type"),
    action_type: str | None = Query(default=None, description="Filter by action type"),
    lookback_days: int = Query(default=90, ge=1, le=365, description="Days to look back"),
) -> TrackRecordResponse:
    """Get historical track record of insight accuracy.

    Returns aggregate statistics including success rate breakdown
    by insight type and action type.
    """
    from datetime import datetime, timedelta

    # Calculate lookback date
    lookback_date = datetime.utcnow() - timedelta(days=lookback_days)

    # Build base query for validated outcomes
    query = (
        select(
            InsightOutcome,
            DeepInsight.insight_type,
            DeepInsight.action,
        )
        .join(DeepInsight, InsightOutcome.insight_id == DeepInsight.id)
        .where(
            and_(
                InsightOutcome.thesis_validated.isnot(None),
                InsightOutcome.created_at >= lookback_date,
            )
        )
    )

    if insight_type:
        query = query.where(DeepInsight.insight_type == insight_type)
    if action_type:
        query = query.where(DeepInsight.action == action_type)

    result = await db.execute(query)
    rows = result.all()

    # Calculate aggregate statistics
    total_insights = len(rows)
    successful = sum(1 for row in rows if row[0].thesis_validated)
    success_rate = successful / total_insights if total_insights > 0 else 0.0

    # Calculate returns for successful vs failed
    successful_returns: list[float] = []
    failed_returns: list[float] = []

    for row in rows:
        outcome = row[0]
        if outcome.actual_return_pct is not None:
            if outcome.thesis_validated:
                successful_returns.append(outcome.actual_return_pct)
            else:
                failed_returns.append(outcome.actual_return_pct)

    avg_return_successful = (
        sum(successful_returns) / len(successful_returns)
        if successful_returns
        else 0.0
    )
    avg_return_failed = (
        sum(failed_returns) / len(failed_returns) if failed_returns else 0.0
    )

    # Build breakdowns by type
    by_type: dict[str, TypeBreakdown] = {}
    by_action: dict[str, TypeBreakdown] = {}

    if not insight_type:
        type_stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            itype = row[1]
            if itype not in type_stats:
                type_stats[itype] = {"total": 0, "successful": 0, "returns": []}
            type_stats[itype]["total"] += 1
            if row[0].thesis_validated:
                type_stats[itype]["successful"] += 1
            if row[0].actual_return_pct is not None:
                type_stats[itype]["returns"].append(row[0].actual_return_pct)

        for itype, stats in type_stats.items():
            by_type[itype] = TypeBreakdown(
                total=stats["total"],
                successful=stats["successful"],
                success_rate=stats["successful"] / stats["total"] if stats["total"] > 0 else 0.0,
                avg_return=sum(stats["returns"]) / len(stats["returns"]) if stats["returns"] else None,
            )

    if not action_type:
        action_stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            action = row[2]
            if action not in action_stats:
                action_stats[action] = {"total": 0, "successful": 0, "returns": []}
            action_stats[action]["total"] += 1
            if row[0].thesis_validated:
                action_stats[action]["successful"] += 1
            if row[0].actual_return_pct is not None:
                action_stats[action]["returns"].append(row[0].actual_return_pct)

        for action, stats in action_stats.items():
            by_action[action] = TypeBreakdown(
                total=stats["total"],
                successful=stats["successful"],
                success_rate=stats["successful"] / stats["total"] if stats["total"] > 0 else 0.0,
                avg_return=sum(stats["returns"]) / len(stats["returns"]) if stats["returns"] else None,
            )

    return TrackRecordResponse(
        total_insights=total_insights,
        successful=successful,
        success_rate=round(success_rate, 4),
        by_type=by_type,
        by_action=by_action,
        avg_return_successful=round(avg_return_successful, 4),
        avg_return_failed=round(avg_return_failed, 4),
    )


@router.get("/track-record/monthly-trend", response_model=MonthlyTrendResponse)
async def get_monthly_trend(
    db: AsyncSession = Depends(get_db),
    lookback_months: int = Query(
        default=12, ge=1, le=36, description="Number of months to look back"
    ),
) -> MonthlyTrendResponse:
    """Get monthly trend of insight success rates.

    Returns per-month aggregated statistics for completed insight outcomes,
    sorted from oldest to newest month.
    """
    from collections import defaultdict
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    # Calculate the cutoff date: first day of the month N months ago
    now = datetime.utcnow()
    cutoff = (now - relativedelta(months=lookback_months)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    # Query completed outcomes within the lookback window
    query = select(InsightOutcome).where(
        and_(
            InsightOutcome.tracking_status == "COMPLETED",
            InsightOutcome.thesis_validated.isnot(None),
            InsightOutcome.tracking_end_date >= cutoff.date(),
        )
    )

    result = await db.execute(query)
    outcomes = result.scalars().all()

    # Group outcomes by month using tracking_end_date
    monthly_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "successful": 0}
    )

    for outcome in outcomes:
        month_key = outcome.tracking_end_date.strftime("%Y-%m")
        monthly_stats[month_key]["total"] += 1
        if outcome.thesis_validated:
            monthly_stats[month_key]["successful"] += 1

    # Build sorted data points (oldest to newest)
    data_points: list[MonthlyDataPoint] = []
    for month_key in sorted(monthly_stats.keys()):
        stats = monthly_stats[month_key]
        total = stats["total"]
        successful = stats["successful"]
        rate = successful / total if total > 0 else 0.0
        data_points.append(
            MonthlyDataPoint(
                month=month_key,
                rate=round(rate, 4),
                total=total,
                successful=successful,
            )
        )

    return MonthlyTrendResponse(
        data=data_points,
        period_months=lookback_months,
    )
