"""Settings service for managing user preferences."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.settings import UserSettings


# Default settings configuration
DEFAULT_SETTINGS: dict[str, Any] = {
    "watchlist_symbols": ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA"],
    "refresh_interval": 5,  # minutes: 1, 5, 15, 30
    "theme": "system",  # "light", "dark", "system"
    "chart_type": "candlestick",  # "candlestick", "line", "area"
    "notification_preferences": {
        "price_alerts": True,
        "insight_alerts": True,
        "daily_summary": False,
    },
    "api_key": None,  # Optional external API key
}


class SettingsService:
    """Service for managing user settings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_settings(self) -> dict[str, Any]:
        """Get all settings, merging defaults with stored values."""
        result = await self.db.execute(select(UserSettings))
        stored_settings = result.scalars().all()

        # Start with defaults
        settings = DEFAULT_SETTINGS.copy()

        # Override with stored values
        for setting in stored_settings:
            try:
                settings[setting.key] = json.loads(setting.value)
            except json.JSONDecodeError:
                settings[setting.key] = setting.value

        return settings

    async def get_setting(self, key: str) -> Any:
        """Get a single setting by key."""
        result = await self.db.execute(
            select(UserSettings).where(UserSettings.key == key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            try:
                return json.loads(setting.value)
            except json.JSONDecodeError:
                return setting.value

        # Return default if exists
        return DEFAULT_SETTINGS.get(key)

    async def set_setting(self, key: str, value: Any) -> UserSettings:
        """Set a single setting."""
        result = await self.db.execute(
            select(UserSettings).where(UserSettings.key == key)
        )
        setting = result.scalar_one_or_none()

        json_value = json.dumps(value)

        if setting:
            setting.value = json_value
        else:
            setting = UserSettings(key=key, value=json_value)
            self.db.add(setting)

        await self.db.commit()
        await self.db.refresh(setting)
        return setting

    async def reset_to_defaults(self) -> dict[str, Any]:
        """Reset all settings to defaults."""
        # Delete all stored settings
        result = await self.db.execute(select(UserSettings))
        stored_settings = result.scalars().all()

        for setting in stored_settings:
            await self.db.delete(setting)

        await self.db.commit()

        return DEFAULT_SETTINGS.copy()

    async def update_watchlist(
        self, symbols: list[str], action: str = "set"
    ) -> list[str]:
        """Update watchlist symbols.

        Args:
            symbols: List of stock symbols
            action: "set" to replace, "add" to append, "remove" to delete

        Returns:
            Updated watchlist
        """
        current_watchlist = await self.get_setting("watchlist_symbols") or []

        if action == "set":
            new_watchlist = symbols
        elif action == "add":
            new_watchlist = list(set(current_watchlist + symbols))
        elif action == "remove":
            new_watchlist = [s for s in current_watchlist if s not in symbols]
        else:
            new_watchlist = current_watchlist

        # Normalize to uppercase
        new_watchlist = [s.upper() for s in new_watchlist]

        await self.set_setting("watchlist_symbols", new_watchlist)
        return new_watchlist


def get_settings_service(db: AsyncSession) -> SettingsService:
    """Factory function to create settings service."""
    return SettingsService(db)
