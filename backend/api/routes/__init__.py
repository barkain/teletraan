"""API routes package - Combines all route modules."""

from fastapi import APIRouter

from api.routes.analysis import router as analysis_router
from api.routes.chat import router as chat_router
from api.routes.data import router as data_router
from api.routes.export import router as export_router
from api.routes.health import router as health_router
from api.routes.insights import router as insights_router
from api.routes.search import router as search_router
from api.routes.settings import router as settings_router
from api.routes.stocks import router as stocks_router

# Combined router for all routes
router = APIRouter()

# Include route modules
router.include_router(health_router, tags=["health"])
router.include_router(analysis_router)
router.include_router(chat_router)
router.include_router(data_router, tags=["data"])
router.include_router(insights_router)
router.include_router(search_router)
router.include_router(settings_router, tags=["settings"])
router.include_router(stocks_router, tags=["stocks"])
router.include_router(export_router)

__all__ = ["router"]
