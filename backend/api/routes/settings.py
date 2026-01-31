"""Settings API endpoints."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from schemas.settings import (
    AllSettingsResponse,
    SettingsResetResponse,
    SettingUpdate,
    WatchlistSettings,
    WatchlistUpdate,
)
from services.settings import SettingsService, get_settings_service

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


@router.get("/{key}")
async def get_setting(
    key: str,
    service: SettingsService = Depends(get_service),
) -> dict[str, Any]:
    """Get a specific setting by key."""
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
    """Update a specific setting."""
    setting = await service.set_setting(key, update.value)
    return {
        "key": setting.key,
        "value": json.loads(setting.value),
        "updated_at": setting.updated_at.isoformat(),
    }


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
