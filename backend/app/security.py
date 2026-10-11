"""Authentication, encrypted credential storage helpers, and response-safe redaction."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

bearer = HTTPBearer(auto_error=False)


def utcnow() -> datetime:
    return datetime.now(UTC)


def issue_session_token(settings: Settings, subject: str) -> str:
    expires = utcnow() + timedelta(minutes=settings.session_ttl_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expires, "scope": "single-user"},
        settings.jwt_secret,
        algorithm="HS256",
    )


def authenticate_bootstrap_passphrase(passphrase: str, settings: Settings) -> bool:
    """Constant-time comparison; passphrase lives only in the backend environment."""
    return bool(settings.bootstrap_passphrase) and hmac.compare_digest(
        passphrase, settings.bootstrap_passphrase
    )


def require_session(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    settings: Settings = request.app.state.settings
    try:
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session"
        ) from exc
    if claims.get("scope") != "single-user" or not isinstance(claims.get("sub"), str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session scope"
        )
    return str(claims["sub"])


def encrypt_secret(value: str, fernet: Fernet) -> str:
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str, fernet: Fernet) -> str:
    return fernet.decrypt(value.encode("utf-8")).decode("utf-8")


def mask_identifier(value: str | None) -> str:
    if not value:
        return "****"
    return f"****{value[-4:]}"


def redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    """Remove known secret-shaped fields before audit or structured logging."""
    sensitive = {"api_key", "api_secret", "secret", "token", "authorization", "password"}
    return {key: "[REDACTED]" if key.lower() in sensitive else item for key, item in value.items()}
