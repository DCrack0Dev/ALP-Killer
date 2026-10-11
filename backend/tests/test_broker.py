from types import SimpleNamespace

import pytest

from app.broker import AlpacaAdapter, BrokerError, EnvironmentMismatchError


class Factory:
    def __init__(self, paper_ok: bool, live_ok: bool) -> None:
        self.paper_ok = paper_ok
        self.live_ok = live_ok

    def __call__(self, _key: str, _secret: str, *, paper: bool):
        allowed = self.paper_ok if paper else self.live_ok
        if not allowed:
            raise RuntimeError("unauthorized")
        return SimpleNamespace(
            get_account=lambda: SimpleNamespace(
                id="account-1234", status="ACTIVE", trading_blocked=False
            )
        )


def test_detects_paper_from_successful_official_client_probe() -> None:
    verified = AlpacaAdapter.validate_credentials(
        "key", "secret", client_factory=Factory(True, False)
    )
    assert verified.environment == "paper"
    assert verified.account_id == "account-1234"


def test_rejects_user_selected_environment_mismatch() -> None:
    with pytest.raises(EnvironmentMismatchError):
        AlpacaAdapter.validate_credentials(
            "key", "secret", "live", client_factory=Factory(True, False)
        )


def test_rejects_invalid_credentials_without_disclosing_secret() -> None:
    with pytest.raises(BrokerError) as error:
        AlpacaAdapter.validate_credentials(
            "key", "secret-value", client_factory=Factory(False, False)
        )
    assert "secret-value" not in str(error.value)


def test_rejects_ambiguous_environment() -> None:
    with pytest.raises(BrokerError, match="Ambiguous"):
        AlpacaAdapter.validate_credentials("key", "secret", client_factory=Factory(True, True))
