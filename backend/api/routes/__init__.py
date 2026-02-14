"""API routes package - Combines all route modules."""

from fastapi import APIRouter

from api.routes.analysis import router as analysis_router
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

# Combined router for all routes
router = APIRouter()

# Include route modules
router.include_router(health_router, tags=["health"])
router.include_router(analysis_router)
router.include_router(chat_router)
router.include_router(data_router, tags=["data"])
router.include_router(deep_insights_router, prefix="/deep-insights", tags=["deep-insights"])
router.include_router(insight_conversations_router, tags=["insight-conversations"])
router.include_router(insight_modifications_router, tags=["insight-modifications"])
router.include_router(insights_router)
router.include_router(search_router)
router.include_router(settings_router, tags=["settings"])
router.include_router(statistical_features_router, tags=["features"])
router.include_router(stocks_router, tags=["stocks"])
router.include_router(outcomes_router, tags=["outcomes"])
router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
router.include_router(reports_router, prefix="/reports", tags=["reports"])
router.include_router(research_router, tags=["research"])
router.include_router(runs_router, prefix="/runs", tags=["runs"])
router.include_router(export_router)

__all__ = ["router"]
