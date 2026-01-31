"""API package - Main router that aggregates all route modules."""

from fastapi import APIRouter

from api.routes import router as routes_router

# Main API router that aggregates all routes
api_router = APIRouter()

# Include all route modules
api_router.include_router(routes_router)

__all__ = ["api_router"]
