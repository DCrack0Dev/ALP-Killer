from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.broker import VerifiedAccount
from app.config import Settings
from app.db import create_database_engine, create_session_factory, initialize_database
from app.main import create_app
from app.models import BrokerConnection
from app.services.connection import validate_and_store_connection


class FakeAdapter:
    @staticmethod
    def validate_credentials(_key: str, _secret: str, _requested: str | None) -> VerifiedAccount:
        return VerifiedAccount("paper", "real-account-1234", "ACTIVE", False)


TEST_JWT_SECRET = "test-jwt-secret-with-at-least-thirty-two-characters"
TEST_PASSPHRASE = "test-passphrase-with-at-least-sixteen-characters"


def test_connection_persists_ciphertext_not_raw_secret(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'connection.db'}")
    initialize_database(engine)
    session = create_session_factory(engine)()
    settings = Settings(
        app_env="test", jwt_secret=TEST_JWT_SECRET, bootstrap_passphrase=TEST_PASSPHRASE
    )
    record = validate_and_store_connection(
        session,
        user_id="owner-id",
        api_key="key-plain",
        api_secret="secret-plain",
        requested_environment=None,
        fernet=settings.credential_fernet(),
        adapter_type=FakeAdapter,
    )
    session.commit()
    stored = session.scalar(select(BrokerConnection).where(BrokerConnection.id == record.id))
    assert stored is not None
    assert "key-plain" not in stored.encrypted_api_key
    assert "secret-plain" not in stored.encrypted_api_secret
    assert stored.environment == "paper"
    session.close()


def test_authenticated_api_has_health_risk_and_kill_switch(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        jwt_secret=TEST_JWT_SECRET,
        bootstrap_passphrase=TEST_PASSPHRASE,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        session = client.post("/api/v1/auth/session", json={"passphrase": TEST_PASSPHRASE})
        assert session.status_code == 200
        token = session.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/risk/config", headers=headers).json()["complete"] is False
        kill = client.post(
            "/api/v1/kill-switch/activate", headers=headers, json={"reason": "test emergency stop"}
        )
        assert kill.status_code == 200
        assert kill.json()["kill_switch_active"] is True
        cleared = client.post("/api/v1/kill-switch/deactivate", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["enabled"] is False


def test_session_rejects_bad_unlock_passphrase(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        jwt_secret=TEST_JWT_SECRET,
        bootstrap_passphrase=TEST_PASSPHRASE,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/auth/session", json={"passphrase": "wrong-passphrase"})
    assert response.status_code == 401


def test_live_activation_is_disabled_by_deployment_policy(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'live-disabled.db'}",
        jwt_secret=TEST_JWT_SECRET,
        bootstrap_passphrase=TEST_PASSPHRASE,
    )
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/auth/session", json={"passphrase": TEST_PASSPHRASE})
        headers = {"Authorization": f"Bearer {session.json()['access_token']}"}
        response = client.post(
            "/api/v1/automation/enable-live",
            headers=headers,
            json={
                "confirmation": "I_UNDERSTAND_LIVE_TRADING",
                "configuration_fingerprint": "a" * 64,
            },
        )
    assert response.status_code == 503
    assert "disabled by deployment policy" in response.json()["detail"]
