"""Common dependencies for API routes."""

from collections.abc import AsyncGenerator
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from database import get_session

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Optional[str] = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Verify the X-API-Key header if TELETRAAN_API_KEY is configured.

    When TELETRAAN_API_KEY is not set in the environment the API is open
    (suitable for local dev). When set, every request must include a matching
    X-API-Key header or it will be rejected with HTTP 401.
    """
    configured_key = settings.TELETRAAN_API_KEY
    if not configured_key:
        return  # Open access — no key configured
    if api_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async for session in get_session():
        yield session


# Type aliases for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
ApiKeyAuth = Annotated[None, Depends(verify_api_key)]
