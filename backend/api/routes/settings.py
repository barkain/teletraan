"""Settings API endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from schemas.settings import (
    AllSettingsResponse,
    LLMProviderConfig,
    LLMProviderStatus,
    LLMTestRequest,
    LLMTestResult,
    SettingsResetResponse,
    SettingUpdate,
    WatchlistSettings,
    WatchlistUpdate,
)
from services.llm_settings import LLMSettingsService
from services.settings import SettingsService, get_settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def get_service(db: AsyncSession = Depends(get_db)) -> SettingsService:
    """Dependency to get settings service."""
    return get_settings_service(db)


@router.get("", response_model=AllSettingsResponse)
async def get_all_settings(
    service: SettingsService = Depends(get_service),
) -> AllSettingsResponse:
    """Get all user settings."""
    settings = await service.get_all_settings()
    return AllSettingsResponse(settings=settings)


@router.post("/reset", response_model=SettingsResetResponse)
async def reset_settings(
    service: SettingsService = Depends(get_service),
) -> SettingsResetResponse:
    """Reset all settings to defaults."""
    settings = await service.reset_to_defaults()
    return SettingsResetResponse(
        success=True,
        message="Settings have been reset to defaults",
        settings=settings,
    )


@router.get("/watchlist", response_model=WatchlistSettings)
async def get_watchlist(
    service: SettingsService = Depends(get_service),
) -> WatchlistSettings:
    """Get the current watchlist settings.

    Returns the list of symbols in the watchlist and the last refresh timestamp.
    If no watchlist is set, returns the default symbols.
    """
    symbols = await service.get_setting("watchlist_symbols")
    if symbols is None:
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA"]

    # Get last refresh time from settings if available
    last_refresh = await service.get_setting("watchlist_last_refresh")

    return WatchlistSettings(symbols=symbols, last_refresh=last_refresh)


@router.put("/watchlist", response_model=WatchlistSettings)
async def update_watchlist(
    update: WatchlistUpdate,
    service: SettingsService = Depends(get_service),
) -> WatchlistSettings:
    """Update the watchlist with new symbols.

    Replaces the entire watchlist with the provided symbols.
    Symbols are validated and normalized to uppercase.
    """
    from datetime import datetime, timezone

    # Update the watchlist using the service (symbols already validated by schema)
    updated_symbols = await service.update_watchlist(update.symbols, action="set")

    # Update the last refresh timestamp
    last_refresh = datetime.now(timezone.utc)
    await service.set_setting("watchlist_last_refresh", last_refresh.isoformat())

    return WatchlistSettings(symbols=updated_symbols, last_refresh=last_refresh)


@router.post("/watchlist/add")
async def add_to_watchlist(
    symbols: list[str],
    service: SettingsService = Depends(get_service),
) -> dict[str, list[str]]:
    """Add symbols to the watchlist."""
    watchlist = await service.update_watchlist(symbols, action="add")
    return {"watchlist": watchlist}


@router.post("/watchlist/remove")
async def remove_from_watchlist(
    symbols: list[str],
    service: SettingsService = Depends(get_service),
) -> dict[str, list[str]]:
    """Remove symbols from the watchlist."""
    watchlist = await service.update_watchlist(symbols, action="remove")
    return {"watchlist": watchlist}


# ============================================
# LLM Provider Settings
# ============================================


def get_llm_service(db: AsyncSession = Depends(get_db)) -> LLMSettingsService:
    """Dependency to get LLM settings service."""
    return LLMSettingsService(db)


@router.get("/llm", response_model=LLMProviderStatus)
async def get_llm_settings(
    service: LLMSettingsService = Depends(get_llm_service),
) -> LLMProviderStatus:
    """Get current LLM provider configuration.

    API keys are masked (only last 4 chars shown).
    """
    status = await service.get_status()
    return LLMProviderStatus(**status)


@router.put("/llm", response_model=LLMProviderStatus)
async def update_llm_settings(
    config: LLMProviderConfig,
    service: LLMSettingsService = Depends(get_llm_service),
) -> LLMProviderStatus:
    """Save LLM provider configuration.

    Settings are stored in the database. Values from .env always take
    priority and cannot be overridden through this endpoint.
    Changes take effect immediately (no restart required).
    """
    await service.save(config.model_dump(exclude_none=True))
    status = await service.get_status()
    return LLMProviderStatus(**status)


@router.delete("/llm")
async def reset_llm_settings(
    service: LLMSettingsService = Depends(get_llm_service),
) -> dict[str, str]:
    """Reset LLM settings to defaults.

    Deletes all saved LLM credentials from the database and clears
    the corresponding runtime environment variables, reverting to
    Claude Code subscription as the default provider.
    """
    await service.reset()
    return {"status": "reset", "message": "LLM settings reset to defaults"}


@router.post("/llm/test", response_model=LLMTestResult)
async def test_llm_connection(
    body: LLMTestRequest,
    llm_service: LLMSettingsService = Depends(get_llm_service),
) -> LLMTestResult:
    """Test the LLM provider connection using values from the request body.

    The frontend sends the current form values so the user can test
    *before* saving. When the form sends empty/null credentials (e.g. the
    user didn't re-type a saved token), we fall back to the DB-saved values
    so that "Test Connection" works for already-persisted credentials.
    """
    # Fall back to DB-saved credentials when the form sends empty values
    if not body.auth_token or not body.api_key or not body.base_url:
        db_values = await llm_service.get_all()
        if not body.auth_token and db_values.get("ANTHROPIC_AUTH_TOKEN"):
            body.auth_token = db_values["ANTHROPIC_AUTH_TOKEN"]
        if not body.api_key and db_values.get("ANTHROPIC_API_KEY"):
            body.api_key = db_values["ANTHROPIC_API_KEY"]
        if not body.base_url and db_values.get("ANTHROPIC_BASE_URL"):
            body.base_url = db_values["ANTHROPIC_BASE_URL"]

    provider = body.provider
    model = body.model or "claude-sonnet-4-20250514"

    result = await _test_llm_connection_http(provider, model, body)
    return LLMTestResult(**result)


@router.get("/{key}")
async def get_setting(
    key: str,
    service: SettingsService = Depends(get_service),
) -> dict[str, Any]:
    """Get a specific setting by key.

    NOTE: This catch-all route is declared last so that static routes
    like /llm and /watchlist are matched first by FastAPI.
    """
    value = await service.get_setting(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"key": key, "value": value}


@router.put("/{key}")
async def update_setting(
    key: str,
    update: SettingUpdate,
    service: SettingsService = Depends(get_service),
) -> dict[str, Any]:
    """Update a specific setting.

    NOTE: This catch-all route is declared last so that static routes
    like /llm and /watchlist are matched first by FastAPI.
    """
    setting = await service.set_setting(key, update.value)
    return {
        "key": setting.key,
        "value": json.loads(setting.value),
        "updated_at": setting.updated_at.isoformat(),
    }


async def _test_llm_connection_http(
    provider: str, model: str, body: LLMTestRequest
) -> dict:
    """Test LLM connection directly via HTTP, bypassing SDK subscription fallback.

    Uses the values from the request body, NOT from server config.
    """
    import aiohttp

    # Auto-detect: resolve to a concrete provider based on provided credentials
    if provider == "auto":
        if body.auth_token and body.base_url:
            provider = "proxy"
        elif body.auth_token:
            provider = "proxy"
        elif body.api_key:
            provider = "anthropic_api"
        else:
            # No credentials provided -- cannot test anything
            return {
                "success": False,
                "message": (
                    "No credentials configured. Using Claude Code subscription "
                    "(cannot be tested via API). Select a specific provider and "
                    "enter credentials to test the connection."
                ),
                "provider": "auto",
                "model": model,
            }

    if provider in ("proxy", "anthropic_api"):
        # Determine base URL and API key based on provider
        if provider == "proxy":
            base_url = (body.base_url or "https://api.anthropic.com").rstrip("/")
            api_key = body.auth_token
        else:
            base_url = "https://api.anthropic.com"
            api_key = body.api_key

        if not api_key:
            return {
                "success": False,
                "message": f"No API key configured for provider '{provider}'",
                "provider": provider,
                "model": model,
            }

        timeout_s = (body.timeout_ms / 1000) if body.timeout_ms else 15

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                    timeout=aiohttp.ClientTimeout(total=timeout_s),
                )
                if resp.status == 200:
                    data = await resp.json()
                    preview = data.get("content", [{}])[0].get("text", "")
                    return {
                        "success": True,
                        "message": "Connection successful",
                        "provider": provider,
                        "model": model,
                        "response_preview": preview[:200] if preview else None,
                    }
                elif resp.status in (401, 403):
                    return {
                        "success": False,
                        "message": "Invalid API key or unauthorized",
                        "provider": provider,
                        "model": model,
                    }
                else:
                    resp_body = await resp.text()
                    return {
                        "success": False,
                        "message": f"HTTP {resp.status}: {resp_body[:200]}",
                        "provider": provider,
                        "model": model,
                    }
        except aiohttp.ClientError as e:
            logger.warning("LLM connection test failed: %s", e)
            return {
                "success": False,
                "message": f"Connection failed: {e}",
                "provider": provider,
                "model": model,
            }

    elif provider == "subscription":
        return {
            "success": True,
            "message": "Subscription auth (using local Claude Code login). Cannot verify remotely.",
            "provider": provider,
            "model": model,
        }

    else:
        # bedrock, vertex, azure, ollama — can't easily test without full cloud SDK
        return {
            "success": True,
            "message": f"Provider '{provider}' configured. Full validation requires cloud credentials.",
            "provider": provider,
            "model": model,
        }
