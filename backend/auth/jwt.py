"""JWT token creation and verification."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from jose import JWTError, jwt

logger = logging.getLogger(__name__)


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def _settings():
    from config import get_settings
    return get_settings()


def create_access_token(subject: str) -> str:
    """Create a short-lived access token for *subject* (username)."""
    s = _settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _encode({"sub": subject, "type": TokenType.ACCESS, "exp": expire})


def create_refresh_token(subject: str) -> str:
    """Create a long-lived refresh token for *subject* (username)."""
    s = _settings()
    expire = datetime.now(timezone.utc) + timedelta(days=s.REFRESH_TOKEN_EXPIRE_DAYS)
    return _encode({"sub": subject, "type": TokenType.REFRESH, "exp": expire})


def verify_token(token: str, expected_type: TokenType) -> str:
    """Decode *token* and return the subject (username).

    Raises ValueError if the token is invalid, expired, or wrong type.
    """
    s = _settings()
    try:
        payload = jwt.decode(token, s.JWT_SECRET_KEY, algorithms=[s.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc

    sub: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if not sub:
        raise ValueError("Token missing subject")
    if token_type != expected_type:
        raise ValueError(f"Expected {expected_type} token, got {token_type!r}")

    return sub


def _encode(claims: dict[str, Any]) -> str:
    s = _settings()
    return jwt.encode(claims, s.JWT_SECRET_KEY, algorithm=s.JWT_ALGORITHM)
