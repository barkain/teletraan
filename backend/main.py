"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import api_router
from api.exceptions import (
    NotFoundError,
    ValidationError,
    DataSourceError,
    not_found_handler,
    validation_error_handler,
    data_source_error_handler,
)
from config import get_settings
from database import init_db, close_db
from scheduler import etl_orchestrator

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup and shutdown."""
    # Startup: Initialize database and create tables
    await init_db()
    # Start ETL scheduler for background data fetching
    etl_orchestrator.start()
    yield
    # Shutdown: Cleanup resources
    etl_orchestrator.stop()
    await close_db()


app = FastAPI(
    title="Market Analyzer API",
    description="API for market data analysis and insights",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Vite and Next.js defaults
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers
app.add_exception_handler(NotFoundError, not_found_handler)
app.add_exception_handler(ValidationError, validation_error_handler)
app.add_exception_handler(DataSourceError, data_source_error_handler)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "An unexpected error occurred",
            "detail": str(exc) if settings.DEBUG else None,
        },
    )


# Include API router with version prefix
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
