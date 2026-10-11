"""Runtime configuration. Production refuses insecure secret defaults."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings; no broker credential is accepted as configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    database_url: str = Field(
        default="sqlite:///./alpaca_killer.db", validation_alias="DATABASE_URL"
    )
    jwt_secret: str = Field(default="development-only-change-me", validation_alias="JWT_SECRET")
    credential_encryption_key: str = Field(default="", validation_alias="CREDENTIAL_ENCRYPTION_KEY")
    bootstrap_passphrase: str = Field(default="", validation_alias="BOOTSTRAP_PASSPHRASE")
    allow_live_trading: bool = Field(default=False, validation_alias="ALLOW_LIVE_TRADING")
    session_ttl_minutes: int = Field(
        default=30, validation_alias="SESSION_TTL_MINUTES", ge=5, le=120
    )
    allowed_origins: str = Field(default="", validation_alias="ALLOWED_ORIGINS")
    api_title: str = "Alpaca Killer Secure Trading API"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def production_secrets_are_present(self) -> Settings:
        if self.is_production:
            if len(self.jwt_secret) < 48:
                raise ValueError("JWT_SECRET must be at least 48 characters in production")
            if not self.credential_encryption_key:
                raise ValueError("CREDENTIAL_ENCRYPTION_KEY is required in production")
            if len(self.bootstrap_passphrase) < 16:
                raise ValueError(
                    "BOOTSTRAP_PASSPHRASE must be at least 16 characters in production"
                )
        return self

    def credential_fernet(self) -> Fernet:
        """Return server-side envelope cipher; development derives a deterministic local-only key."""
        raw = self.credential_encryption_key
        if not raw:
            raw = base64.urlsafe_b64encode(
                hashlib.sha256(self.jwt_secret.encode()).digest()
            ).decode()
        return Fernet(raw.encode())


@lru_cache
def get_settings() -> Settings:
    return Settings()
