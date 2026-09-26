

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

@dataclass
class AuthUser:
    id: uuid.UUID | None
    label: str
    email: str | None = None
    picture: str | None = None

class GoogleCredentialBody(BaseModel):
    credential: str = Field(..., min_length=20, description="Google ID token from GIS")

def _jwt_secret() -> str:
    settings = get_settings()
    secret = (settings.auth_jwt_secret or "").strip()
    if secret:
        return secret

    client = (settings.google_client_id or "dev").strip()
    return f"grounded-dev-{client}"

def _issue_session_token(
    *,
    user_id: uuid.UUID,
    email: str | None,
    name: str,
    picture: str | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "picture": picture,
        "iat": now,
        "exp": now + timedelta(days=max(1, settings.auth_token_days)),
        "iss": "grounded-rag",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")

def _user_from_payload(payload: dict[str, Any], user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        label=payload.get("name") or user.email or "user",
        email=user.email,
        picture=payload.get("picture"),
    )

def _decode_session_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            _jwt_secret(),
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc

def _verify_google_id_token(credential: str) -> dict[str, Any]:
    settings = get_settings()
    client_id = (settings.google_client_id or "").strip()
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLIENT_ID is not configured on the server",
        )
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="google-auth is not installed (pip install google-auth)",
        ) from exc

    try:
        info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}") from exc

    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Invalid Google token issuer")
    if not info.get("sub"):
        raise HTTPException(status_code=401, detail="Google token missing subject")
    return info

def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AuthUser:

    settings = get_settings()
    token = _extract_bearer(authorization)

    if not settings.auth_enabled:
        if not token:
            return AuthUser(id=None, label="anonymous")

        try:
            payload = _decode_session_token(token)
        except HTTPException:
            return AuthUser(id=None, label="anonymous")
        uid = uuid.UUID(str(payload["sub"]))
        result = await db.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if not user:
            return AuthUser(id=None, label="anonymous")
        return _user_from_payload(payload, user)

    if not token:
        raise HTTPException(status_code=401, detail="Sign in with Google required")

    payload = _decode_session_token(token)
    uid = uuid.UUID(str(payload["sub"]))
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found — sign in again")
    return _user_from_payload(payload, user)

async def resolve_token_user(
    db: AsyncSession,
    *,
    authorization: str | None = None,
    access_token: str | None = None,
) -> AuthUser:

    settings = get_settings()
    token = access_token or _extract_bearer(authorization)

    if not settings.auth_enabled:
        return AuthUser(id=None, label="anonymous")

    if not token:
        raise HTTPException(status_code=401, detail="Sign in with Google required")

    payload = _decode_session_token(token)
    uid = uuid.UUID(str(payload["sub"]))
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found — sign in again")
    return _user_from_payload(payload, user)

@router.get(
    "/config",
    summary="Public auth config for the frontend",
)
async def auth_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "auth_enabled": settings.auth_enabled,
        "provider": "google",
        "google_client_id": (settings.google_client_id or "").strip() or None,
    }

@router.post(
    "/google",
    summary="Exchange Google ID token for a Grounded session JWT",
)
async def auth_google(
    body: GoogleCredentialBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=400,
            detail="AUTH_ENABLED=false — turn it on to require Google Sign-In",
        )

    info = _verify_google_id_token(body.credential)
    google_sub = str(info["sub"])
    email = info.get("email")
    name = (info.get("name") or info.get("given_name") or email or "Google user").strip()
    picture = info.get("picture")

    result = await db.execute(select(User).where(User.external_id == google_sub))
    user = result.scalar_one_or_none()
    if user is None and email:

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is not None:
            user.external_id = google_sub

    if user is None:
        user = User(external_id=google_sub, email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        if email and user.email != email:
            user.email = email
            await db.commit()
            await db.refresh(user)

    token = _issue_session_token(
        user_id=user.id,
        email=user.email,
        name=name,
        picture=picture,
    )
    logger.info("Google sign-in ok user=%s email=%s", user.id, user.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "label": name,
            "picture": picture,
        },
    }

@router.get(
    "/me",
    summary="Current auth status",
)
async def auth_me(user: AuthUser = Depends(get_current_user)) -> dict[str, Any]:
    settings = get_settings()
    return {
        "auth_enabled": settings.auth_enabled,
        "provider": "google",
        "user_id": str(user.id) if user.id else None,
        "label": user.label,
        "email": user.email,
        "picture": user.picture,
    }

@router.post("/logout", summary="Client-side logout helper (stateless JWT)")
async def auth_logout() -> dict[str, str]:
    return {"status": "ok", "detail": "Discard the Bearer token on the client"}
