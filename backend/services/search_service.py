"""Search service with text preprocessing and relevance scoring."""

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.insight import Insight
from models.stock import Stock


class SearchService:
    """Service for searching stocks and insights with relevance scoring."""

    def _calculate_stock_relevance(self, stock: Stock, query: str) -> float:
        """
        Calculate relevance score for a stock.

        Scoring:
        - Exact symbol match: 100 points
        - Symbol starts with query: 80 points
        - Symbol contains query: 60 points
        - Name starts with query: 50 points
        - Name contains query: 30 points
        """
        query_lower = query.lower()
        symbol_lower = stock.symbol.lower()
        name_lower = stock.name.lower()

        score = 0.0

        # Symbol matching (highest priority)
        if symbol_lower == query_lower:
            score += 100.0
        elif symbol_lower.startswith(query_lower):
            score += 80.0
        elif query_lower in symbol_lower:
            score += 60.0

        # Name matching
        if name_lower.startswith(query_lower):
            score += 50.0
        elif query_lower in name_lower:
            score += 30.0

        return score

    def _calculate_insight_relevance(self, insight: Insight, query: str) -> float:
        """
        Calculate relevance score for an insight.

        Scoring:
        - Title starts with query: 80 points
        - Title contains query: 50 points
        - Description contains query: 30 points
        - Recent insights get a boost (up to 20 points)
        """
        query_lower = query.lower()
        title_lower = insight.title.lower()
        description_lower = insight.description.lower() if insight.description else ""

        score = 0.0

        # Title matching (highest priority)
        if title_lower.startswith(query_lower):
            score += 80.0
        elif query_lower in title_lower:
            score += 50.0

        # Description matching
        if query_lower in description_lower:
            score += 30.0

        # Recency boost (insights from last 7 days get up to 20 points)
        if insight.created_at:
            days_old = (datetime.now(timezone.utc) - insight.created_at).days
            if days_old < 7:
                score += 20.0 * (1 - days_old / 7)

        return score

    async def global_search(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 20,
    ) -> dict:
        """
        Search across stocks and insights.

        Returns combined results with relevance scoring.
        """
        half_limit = limit // 2

        # Search stocks
        stock_results = await self.search_stocks(
            db, query, limit=half_limit, active_only=True
        )

        # Search insights
        insight_results = await self.search_insights(
            db, query, limit=half_limit, active_only=True
        )

        return {
            "stocks": stock_results["stocks"],
            "insights": insight_results["insights"],
            "total": stock_results["total"] + insight_results["total"],
            "query": query,
        }

    async def search_stocks(
        self,
        db: AsyncSession,
        query: str,
        sector: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> dict:
        """Search stocks by symbol or name with optional filters."""
        base_query = select(Stock)

        # Apply filters
        if active_only:
            base_query = base_query.where(Stock.is_active == True)  # noqa: E712
        if sector:
            base_query = base_query.where(Stock.sector == sector)

        # Search condition
        search_condition = or_(
            Stock.symbol.ilike(f"%{query}%"),
            Stock.name.ilike(f"%{query}%"),
        )
        base_query = base_query.where(search_condition)

        # Execute query
        result = await db.execute(base_query)
        stocks = result.scalars().all()

        # Calculate relevance and sort
        scored_stocks = []
        for stock in stocks:
            score = self._calculate_stock_relevance(stock, query)
            stock_dict = {
                "id": stock.id,
                "symbol": stock.symbol,
                "name": stock.name,
                "sector": stock.sector,
                "industry": stock.industry,
                "market_cap": stock.market_cap,
                "is_active": stock.is_active,
                "created_at": stock.created_at,
                "relevance_score": score,
            }
            scored_stocks.append(stock_dict)

        # Sort by relevance score descending
        scored_stocks.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Apply limit after scoring
        limited_stocks = scored_stocks[:limit]

        return {
            "stocks": limited_stocks,
            "total": len(scored_stocks),
        }

    async def search_insights(
        self,
        db: AsyncSession,
        query: str,
        insight_type: str | None = None,
        severity: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> dict:
        """Search insights by title or description with optional filters."""
        base_query = select(Insight)

        # Apply filters
        if active_only:
            base_query = base_query.where(Insight.is_active == True)  # noqa: E712
            base_query = base_query.where(
                (Insight.expires_at.is_(None))
                | (Insight.expires_at > datetime.now(timezone.utc))
            )
        if insight_type:
            base_query = base_query.where(Insight.insight_type == insight_type)
        if severity:
            base_query = base_query.where(Insight.severity == severity)

        # Search condition
        search_condition = or_(
            Insight.title.ilike(f"%{query}%"),
            Insight.description.ilike(f"%{query}%"),
        )
        base_query = base_query.where(search_condition)

        # Execute query
        result = await db.execute(base_query)
        insights = result.scalars().all()

        # Calculate relevance and sort
        scored_insights = []
        for insight in insights:
            score = self._calculate_insight_relevance(insight, query)
            insight_dict = {
                "id": insight.id,
                "stock_id": insight.stock_id,
                "insight_type": insight.insight_type,
                "title": insight.title,
                "description": insight.description,
                "severity": insight.severity,
                "confidence": insight.confidence,
                "is_active": insight.is_active,
                "created_at": insight.created_at,
                "expires_at": insight.expires_at,
                "relevance_score": score,
            }
            scored_insights.append(insight_dict)

        # Sort by relevance score descending
        scored_insights.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Apply limit after scoring
        limited_insights = scored_insights[:limit]

        return {
            "insights": limited_insights,
            "total": len(scored_insights),
        }

    async def get_suggestions(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """Get quick search suggestions for autocomplete."""
        suggestions = []

        # Get stock suggestions (prioritize symbol matches)
        stock_query = (
            select(Stock)
            .where(Stock.is_active == True)  # noqa: E712
            .where(
                or_(
                    Stock.symbol.ilike(f"{query}%"),
                    Stock.name.ilike(f"%{query}%"),
                )
            )
            .limit(limit)
        )
        result = await db.execute(stock_query)
        stocks = result.scalars().all()

        for stock in stocks:
            suggestions.append(
                {
                    "text": f"{stock.symbol} - {stock.name}",
                    "type": "stock",
                    "symbol": stock.symbol,
                    "id": stock.id,
                }
            )

        return suggestions[:limit]


# Singleton instance
search_service = SearchService()
