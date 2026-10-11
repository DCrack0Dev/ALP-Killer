"""Server-side connection validation, environment verification, and encrypted persistence."""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker import AlpacaAdapter, VerifiedAccount
from app.models import AccountEnvironment, BrokerConnection
from app.security import decrypt_secret, encrypt_secret, mask_identifier
from app.services.audit import record_audit


def validate_and_store_connection(
    db: Session,
    *,
    user_id: str,
    api_key: str,
    api_secret: str,
    requested_environment: str | None,
    fernet: Fernet,
    adapter_type: type[AlpacaAdapter] = AlpacaAdapter,
) -> BrokerConnection:
    """Store a credential pair only after a successful server-side official SDK validation."""
    verified: VerifiedAccount = adapter_type.validate_credentials(
        api_key, api_secret, requested_environment
    )
    existing = db.scalar(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == "alpaca",
            BrokerConnection.environment == verified.environment,
        )
    )
    if existing is None:
        connection = BrokerConnection(
            user_id=user_id,
            broker="alpaca",
            environment=verified.environment,
            account_id_masked=mask_identifier(verified.account_id),
            account_status=verified.account_status,
            trading_blocked=verified.trading_blocked,
            automation_enabled=False,
            encrypted_api_key=encrypt_secret(api_key, fernet),
            encrypted_api_secret=encrypt_secret(api_secret, fernet),
        )
        db.add(connection)
        db.flush()
    else:
        connection = existing
        connection.account_id_masked = mask_identifier(verified.account_id)
        connection.account_status = verified.account_status
        connection.trading_blocked = verified.trading_blocked
        connection.encrypted_api_key = encrypt_secret(api_key, fernet)
        connection.encrypted_api_secret = encrypt_secret(api_secret, fernet)
    db.add(
        AccountEnvironment(
            connection_id=connection.id,
            environment=verified.environment,
            server_verified=True,
            account_payload={
                "account_id_masked": connection.account_id_masked,
                "account_status": verified.account_status,
                "trading_blocked": verified.trading_blocked,
            },
        )
    )
    record_audit(
        db,
        event_type="BROKER_CONNECTION_VERIFIED",
        actor=user_id,
        environment=verified.environment,
        payload={
            "broker": "alpaca",
            "environment": verified.environment,
            "account": connection.account_id_masked,
        },
    )
    return connection


def adapter_for_connection(connection: BrokerConnection, fernet: Fernet) -> AlpacaAdapter:
    """Decrypt only in the backend execution path; callers must never serialize this adapter."""
    return AlpacaAdapter(
        decrypt_secret(connection.encrypted_api_key, fernet),
        decrypt_secret(connection.encrypted_api_secret, fernet),
        connection.environment,
    )


def disconnect_connection(db: Session, connection: BrokerConnection, actor: str) -> None:
    """Destroy encrypted credential ciphertext and disable the associated automation state."""
    connection.encrypted_api_key = ""
    connection.encrypted_api_secret = ""
    connection.automation_enabled = False
    record_audit(
        db,
        event_type="BROKER_CONNECTION_DISCONNECTED",
        actor=actor,
        environment=connection.environment,
        payload={"connection_id": connection.id},
    )
