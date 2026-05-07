"""API routes package - Combines all route modules."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.routes.analysis import router as analysis_router
from api.routes.auth import router as auth_router
from api.routes.chat import router as chat_router
from api.routes.data import router as data_router
from api.routes.deep_insights import router as deep_insights_router
from api.routes.export import router as export_router
from api.routes.health import router as health_router
from api.routes.insight_conversations import router as insight_conversations_router
from api.routes.insight_modifications import router as insight_modifications_router
from api.routes.insights import router as insights_router
from api.routes.knowledge import router as knowledge_router
from api.routes.outcomes import router as outcomes_router
from api.routes.portfolio import router as portfolio_router
from api.routes.reports import router as reports_router
from api.routes.research import router as research_router
from api.routes.runs import router as runs_router
from api.routes.search import router as search_router
from api.routes.settings import router as settings_router
from api.routes.statistical_features import router as statistical_features_router
from api.routes.stocks import router as stocks_router
from api.routes.alpha_engine import router as alpha_engine_router
from api.routes.backtest import router as backtest_router
from api.routes.thematic_insights import router as thematic_insights_router

# Combined router for all routes
router = APIRouter()

# Public routes (no auth required)
router.include_router(health_router, tags=["health"])
router.include_router(auth_router)

# Protected routes — all require a valid Bearer access token
_auth = [Depends(get_current_user)]

router.include_router(analysis_router, dependencies=_auth)
router.include_router(chat_router, dependencies=_auth)
router.include_router(data_router, tags=["data"], dependencies=_auth)
router.include_router(deep_insights_router, prefix="/deep-insights", tags=["deep-insights"], dependencies=_auth)
router.include_router(insight_conversations_router, tags=["insight-conversations"], dependencies=_auth)
router.include_router(insight_modifications_router, tags=["insight-modifications"], dependencies=_auth)
router.include_router(insights_router, dependencies=_auth)
router.include_router(search_router, dependencies=_auth)
router.include_router(settings_router, tags=["settings"], dependencies=_auth)
router.include_router(statistical_features_router, tags=["features"], dependencies=_auth)
router.include_router(stocks_router, tags=["stocks"], dependencies=_auth)
router.include_router(outcomes_router, tags=["outcomes"], dependencies=_auth)
router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"], dependencies=_auth)
router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"], dependencies=_auth)
router.include_router(reports_router, prefix="/reports", tags=["reports"], dependencies=_auth)
router.include_router(research_router, tags=["research"], dependencies=_auth)
router.include_router(runs_router, prefix="/runs", tags=["runs"], dependencies=_auth)
router.include_router(export_router, dependencies=_auth)
router.include_router(alpha_engine_router, prefix="/alpha-engine", tags=["alpha-engine"], dependencies=_auth)
router.include_router(backtest_router, dependencies=_auth)
router.include_router(thematic_insights_router, prefix="/thematic-insights", tags=["thematic-insights"], dependencies=_auth)

__all__ = ["router"]
