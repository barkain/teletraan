"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

# Raise the soft file-descriptor limit to avoid "Too many open files" (Errno 24)
# under the autonomous analysis pipeline (Claude SDK subprocesses + yfinance
# ThreadPoolExecutor + SQLite connections can exceed macOS default of 256).
# The `resource` module is Unix-only; skip on Windows.
if sys.platform != "win32":
    try:
        import resource
        _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(_hard, 4096), _hard))
    except (ImportError, ValueError, OSError):
        pass

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

# Configure logging before importing other modules
# This ensures all loggers created with getLogger(__name__) use this configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True,  # Override any existing configuration
)

# Set specific loggers to appropriate levels
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce access log noise
logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce HTTP client noise

logger = logging.getLogger(__name__)

from api import api_router  # noqa: E402
from api.exceptions import (  # noqa: E402
    NotFoundError,
    ValidationError,
    DataSourceError,
    not_found_handler,
    validation_error_handler,
    data_source_error_handler,
)
from config import get_settings  # noqa: E402
from database import init_db, close_db, async_session_factory  # noqa: E402
from scheduler import etl_orchestrator  # noqa: E402

settings = get_settings()

VERSION = "1.0.0"


def _print_startup_banner() -> None:
    """Print a spectacular ASCII art banner on server startup.

    Uses print() instead of logger.info() because uvicorn reconfigures
    logging after module import, which can suppress logger output during
    the lifespan startup phase.
    """
    banner = f"""
\033[38;5;46m
    $$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
    $                                                                          $
    $   \033[38;5;226m         ╔╦╗╔═╗╦  ╔═╗╔╦╗╦═╗╔═╗╔═╗╔╗╔\033[38;5;46m                                   $
    $   \033[38;5;226m          ║ ║╣ ║  ║╣  ║ ╠╦╝╠═╣╠═╣║║║\033[38;5;46m                                   $
    $   \033[38;5;226m          ╩ ╚═╝╩═╝╚═╝ ╩ ╩╚═╩ ╩╩ ╩╝╚╝\033[38;5;46m                                   $
    $                                                                          $
    $   \033[38;5;51m        AI-Powered Market Intelligence\033[38;5;46m                                 $
    $                                                                          $
    $   \033[38;5;250m   ╭───────────────────────────────────────────────────────╮\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m          .       *                                    \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m         /|\\     /|                                    \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m    *   / | \\   / |   *       \033[38;5;214m,=,  ,=,                 \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m   /|  /  |  \\ /  |  /|      \033[38;5;214m| |  | |  BULL            \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m  / | /   |   *   | / |      \033[38;5;214m|_|__|_|  MARKET          \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m /  |/    |       |/  |      \033[38;5;214m /~~~~\\                   \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;34m/   *     |       *   |     \033[38;5;214m/ \\  / \\   (__)            \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;196m────+─────+───────+───+─── \033[38;5;214m(  \\/ \\/  ) (oo)            \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;240m  Jan   Feb   Mar   Apr     \033[38;5;214m \\______/  /------\\        \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   │\033[38;5;240m                            \033[38;5;214m  ||  ||   / |    ||       \033[38;5;250m│\033[38;5;46m           $
    $   \033[38;5;250m   ╰───────────────────────────────────────────────────────╯\033[38;5;46m           $
    $                                                                          $
    $   \033[38;5;39m[Engine]\033[38;5;255m FastAPI + Claude Agent SDK (Multi-Agent Pipeline)\033[38;5;46m             $
    $   \033[38;5;39m[Pipeline]\033[38;5;255m MacroScan → HeatmapFetch → HeatmapAnalysis → DeepDive\033[38;5;46m       $
    $   \033[38;5;39m          \033[38;5;255m CoverageEval → Synthesis\033[38;5;46m                                    $
    $                                                                          $
    $   \033[38;5;208m┌──────────────────────────────────────────────────────┐\033[38;5;46m               $
    $   \033[38;5;208m│\033[38;5;255m  API Server   \033[38;5;226mhttp://localhost:8000                  \033[38;5;208m│\033[38;5;46m               $
    $   \033[38;5;208m│\033[38;5;255m  API Docs     \033[38;5;226mhttp://localhost:8000/docs             \033[38;5;208m│\033[38;5;46m               $
    $   \033[38;5;208m│\033[38;5;255m  WebSocket    \033[38;5;226mws://localhost:8000/api/v1/chat        \033[38;5;208m│\033[38;5;46m               $
    $   \033[38;5;208m│\033[38;5;255m  Version      \033[38;5;226m{VERSION}                                  \033[38;5;208m│               \033[38;5;46m$
    $   \033[38;5;208m└──────────────────────────────────────────────────────┘\033[38;5;46m               $
    $                                                                          $
    $$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
\033[0m"""
    print(banner, flush=True)  # noqa: T201 — intentional print for startup visibility


async def _cleanup_stale_analysis_tasks() -> None:
    """Mark any in-progress analysis tasks as failed on startup.

    Analysis tasks run as in-process background coroutines and cannot
    survive a server restart.  Any task still in an active status at
    startup is stale and must be marked failed so the frontend does not
    resume polling a dead task.
    """
    from sqlalchemy import update
    from datetime import datetime
    from models.analysis_task import AnalysisTask, AnalysisTaskStatus

    active_statuses = [
        AnalysisTaskStatus.PENDING.value,
        AnalysisTaskStatus.MACRO_SCAN.value,
        AnalysisTaskStatus.SECTOR_ROTATION.value,
        AnalysisTaskStatus.OPPORTUNITY_HUNT.value,
        AnalysisTaskStatus.DEEP_DIVE.value,
        AnalysisTaskStatus.SYNTHESIS.value,
    ]

    async with async_session_factory() as session:
        result = await session.execute(
            update(AnalysisTask)
            .where(AnalysisTask.status.in_(active_statuses))
            .values(
                status=AnalysisTaskStatus.FAILED.value,
                progress=-1,
                error_message="Server restarted while analysis was in progress",
                completed_at=datetime.utcnow(),
            )
        )
        await session.commit()

        if result.rowcount:
            logger.info(
                f"Cleaned up {result.rowcount} stale analysis task(s) from previous run"
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup and shutdown."""
    # Startup: Display banner
    _print_startup_banner()
    # Log active LLM provider — use print() for guaranteed visibility
    # (uvicorn reconfigures logging after module import, suppressing logger.info
    # output during the lifespan startup phase)
    llm_provider = settings.get_llm_provider()
    llm_display = settings.get_llm_display_name()
    print(  # noqa: T201
        f"\033[38;5;39m[LLM]\033[0m Provider: {llm_display} (provider={llm_provider})",
        flush=True,
    )
    if llm_provider == "subscription":
        print(  # noqa: T201
            "\033[38;5;208m[LLM]\033[0m WARNING: Using Claude Code subscription auth. "
            "This is NOT recommended for distributed deployments. "
            "Set ANTHROPIC_API_KEY or configure a cloud provider "
            "(Bedrock/Vertex/Azure) for production use.",
            flush=True,
        )
    # Log report publishing status
    from api.routes.reports import get_publishing_config, is_publishing_enabled
    pub_config = get_publishing_config()
    pub_method = pub_config["method"]
    if is_publishing_enabled():
        if pub_method == "github_pages":
            print(  # noqa: T201
                f"\033[38;5;39m[Publishing]\033[0m GitHub Pages: ENABLED "
                f"(repo: {pub_config['org']}/{pub_config['repo']}, "
                f"branch: {pub_config['branch']})",
                flush=True,
            )
        elif pub_method == "static_dir":
            print(  # noqa: T201
                f"\033[38;5;39m[Publishing]\033[0m Static Directory: ENABLED "
                f"(dir: {pub_config['publish_dir']}, "
                f"url: {pub_config['base_url'] or 'not set'})",
                flush=True,
            )
    else:
        if pub_method == "none":
            detail = "PUBLISH_METHOD=none"
        elif pub_method == "static_dir":
            detail = "set PUBLISH_DIR in .env to enable"
        else:
            detail = "set GITHUB_PAGES_ENABLED=true in .env to enable"
        print(  # noqa: T201
            f"\033[38;5;39m[Publishing]\033[0m DISABLED ({detail})",
            flush=True,
        )
    # Initialize database and create tables
    await init_db()
    # Load saved LLM settings from database into os.environ
    # (must happen after init_db so tables exist, but before LLM provider detection)
    from services.llm_settings import load_llm_settings_on_startup
    async with async_session_factory() as session:
        await load_llm_settings_on_startup(session)
    # Mark any leftover in-progress analysis tasks as failed
    await _cleanup_stale_analysis_tasks()
    # Start ETL scheduler for background data fetching
    etl_orchestrator.start()
    yield
    # Shutdown: Cleanup resources
    etl_orchestrator.stop()
    await close_db()


app = FastAPI(
    title="Teletraan API",
    description="API for market data analysis and insights",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS for frontend (allow any localhost port + Tauri desktop origins)
# Tauri v2 custom-protocol uses "tauri://localhost" on macOS;
# the localhost plugin uses "http://tauri.localhost".
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$|^https?://tauri\.localhost$|^tauri://localhost$",
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
