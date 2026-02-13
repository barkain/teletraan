"""Service for managing LLM provider settings stored in the database.

Provides CRUD operations for LLM configuration that persists across restarts.
Environment variables (.env) always take priority over database-stored values.
"""

import json
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.settings import UserSettings

logger = logging.getLogger(__name__)

# Keys we store in the user_settings table for LLM config
LLM_SETTING_KEYS = [
    "LLM_PROVIDER",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "API_TIMEOUT_MS",
    "ANTHROPIC_MODEL",
    "AWS_REGION",
    "VERTEX_PROJECT",
    "VERTEX_REGION",
]

# Prefix to namespace LLM settings in the user_settings table
_LLM_PREFIX = "llm:"


def _db_key(setting_name: str) -> str:
    """Convert a setting name to the namespaced DB key."""
    return f"{_LLM_PREFIX}{setting_name}"


def _mask_secret(value: str | None) -> str | None:
    """Mask a secret value, showing only the last 4 characters."""
    if not value:
        return None
    if len(value) <= 8:
        return "****" + value[-2:] if len(value) > 2 else "****"
    # Show prefix hint + last 4
    prefix = value[:7] if value.startswith(("sk-ant-", "sk-")) else value[:3]
    return f"{prefix}...{value[-4:]}"


def _is_env_set(key: str) -> bool:
    """Check if a setting is explicitly set via environment / .env file.

    We check os.environ directly. pydantic-settings loads .env into
    os.environ at import time, so this catches both real env vars and
    .env file entries.
    """
    return key in os.environ and os.environ[key] != ""


class LLMSettingsService:
    """Service for LLM provider configuration stored in user_settings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_db_value(self, key: str) -> str | None:
        """Read a single LLM setting from the database."""
        result = await self.db.execute(
            select(UserSettings).where(UserSettings.key == _db_key(key))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        try:
            return json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return row.value

    async def _set_db_value(self, key: str, value: Any) -> None:
        """Write a single LLM setting to the database."""
        db_key = _db_key(key)
        result = await self.db.execute(
            select(UserSettings).where(UserSettings.key == db_key)
        )
        row = result.scalar_one_or_none()
        json_value = json.dumps(value)

        if row:
            row.value = json_value
        else:
            row = UserSettings(key=db_key, value=json_value)
            self.db.add(row)

    async def get_all(self) -> dict[str, Any]:
        """Return all LLM settings from database (raw, unmasked)."""
        values: dict[str, Any] = {}
        for key in LLM_SETTING_KEYS:
            val = await self._get_db_value(key)
            if val is not None:
                values[key] = val
        return values

    async def get_status(self) -> dict[str, Any]:
        """Build the full LLM provider status response.

        Resolves effective values (env > db > default) and masks secrets.
        """
        from config import get_settings

        settings = get_settings()
        db_values = await self.get_all()

        # Determine if .env is overriding anything
        env_keys_present = [k for k in LLM_SETTING_KEYS if _is_env_set(k)]
        env_override = len(env_keys_present) > 0

        # Effective values: env takes priority, then db, then config defaults
        def effective(key: str, default: Any = None) -> Any:
            if _is_env_set(key):
                return os.environ[key]
            if key in db_values:
                return db_values[key]
            return default

        configured_provider = effective("LLM_PROVIDER", settings.LLM_PROVIDER)
        model = effective("ANTHROPIC_MODEL", settings.ANTHROPIC_MODEL)

        return {
            "active_provider": settings.get_llm_provider(),
            "active_provider_display": settings.get_llm_display_name(),
            "configured_provider": configured_provider,
            "model": model,
            "env_override": env_override,
            "anthropic_api_key": _mask_secret(
                effective("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY)
            ),
            "anthropic_auth_token": _mask_secret(
                effective("ANTHROPIC_AUTH_TOKEN", settings.ANTHROPIC_AUTH_TOKEN)
            ),
            "anthropic_base_url": effective(
                "ANTHROPIC_BASE_URL", settings.ANTHROPIC_BASE_URL
            ),
            "api_timeout_ms": effective("API_TIMEOUT_MS", settings.API_TIMEOUT_MS),
            "aws_region": effective("AWS_REGION", settings.AWS_REGION),
            "vertex_project": effective("VERTEX_PROJECT", settings.VERTEX_PROJECT),
            "vertex_region": effective("VERTEX_REGION", settings.VERTEX_REGION),
        }

    async def save(self, config: dict[str, Any]) -> None:
        """Save LLM settings to the database and update runtime config.

        Only non-None values in ``config`` are saved. Pass None or omit
        a key to leave the existing value unchanged.
        """
        import config as config_module

        field_to_env = {
            "llm_provider": "LLM_PROVIDER",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "anthropic_auth_token": "ANTHROPIC_AUTH_TOKEN",
            "anthropic_base_url": "ANTHROPIC_BASE_URL",
            "api_timeout_ms": "API_TIMEOUT_MS",
            "anthropic_model": "ANTHROPIC_MODEL",
            "aws_region": "AWS_REGION",
            "vertex_project": "VERTEX_PROJECT",
            "vertex_region": "VERTEX_REGION",
        }

        for field_name, env_key in field_to_env.items():
            value = config.get(field_name)
            if value is None:
                continue

            # Don't overwrite if .env has a value for this key
            if _is_env_set(env_key):
                logger.info(
                    "Skipping %s: .env value takes priority", env_key
                )
                continue

            # Store in database
            await self._set_db_value(env_key, value if not isinstance(value, int) else value)

            # Update os.environ so changes take effect immediately
            str_value = str(value)
            os.environ[env_key] = str_value

        await self.db.commit()

        # Clear the cached Settings singleton so it picks up new env vars
        config_module.get_settings.cache_clear()

        # Reset the LLM env configured flag so pool picks up new config
        try:
            import llm.client_pool as pool_mod
            pool_mod._llm_env_configured = False
        except ImportError:
            pass

        logger.info("LLM settings saved and applied")


async def load_llm_settings_on_startup(db: AsyncSession) -> None:
    """Load saved LLM settings from the database into os.environ.

    Called once during application startup. .env values are NOT overwritten.
    """
    service = LLMSettingsService(db)
    db_values = await service.get_all()

    applied = []
    for key, value in db_values.items():
        if _is_env_set(key):
            continue  # .env takes priority
        os.environ[key] = str(value)
        applied.append(key)

    if applied:
        # Clear cached Settings so it re-reads env
        from config import get_settings
        get_settings.cache_clear()
        logger.info("Loaded LLM settings from database: %s", ", ".join(applied))
    else:
        logger.debug("No database LLM settings to apply (env or empty)")
