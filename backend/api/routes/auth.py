"""Authentication routes: login, refresh, me, logout."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, Cookie, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from auth import create_access_token, create_refresh_token, verify_token, verify_password, TokenType
from models.user import User
from schemas.auth import LoginRequest, TokenResponse, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days in seconds


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=True,          # HTTPS only (safe for local dev via localhost exception)
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/api/v1/auth",  # Scoped to auth endpoints only
    )


async def _get_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username + password. Returns access token and sets refresh cookie."""
    user = await _get_user(db, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    access_token = create_access_token(user.username)
    refresh_token = create_refresh_token(user.username)
    _set_refresh_cookie(response, refresh_token)

    logger.info("User %r logged in", user.username)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> TokenResponse:
    """Issue a new access token using the refresh token cookie."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        username = verify_token(refresh_token, TokenType.REFRESH)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await _get_user(db, username)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_access = create_access_token(user.username)
    new_refresh = create_refresh_token(user.username)
    _set_refresh_cookie(response, new_refresh)

    return TokenResponse(access_token=new_access)


@router.get("/me", response_model=UserResponse)
async def me(
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> UserResponse:
    """Return the current user based on the refresh token (used on page load)."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        username = verify_token(refresh_token, TokenType.REFRESH)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await _get_user(db, username)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return UserResponse(username=user.username, is_active=user.is_active)


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the refresh token cookie."""
    response.delete_cookie(key=_REFRESH_COOKIE, path="/api/v1/auth")
    return {"detail": "Logged out"}
