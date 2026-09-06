"""Unit tests for secrets management, credential audit, and TLS enforcement (Sprint S23.01)."""

import pytest
from pydantic import SecretStr

from src.utils.secrets import (
    SecretsManager,
    SecurityError,
    enforce_tls_transport,
    get_secret,
    mask_secret,
    validate_live_credentials,
)


def test_mask_secret_nominal_and_edge_cases() -> None:
    """Verify mask_secret masks sensitive values and redacts short strings."""
    assert mask_secret(None) == "[NONE]"
    assert mask_secret("") == "[REDACTED]"
    assert mask_secret("short") == "[REDACTED]"
    assert mask_secret(SecretStr("abcdefghij"), prefix_len=2, suffix_len=2) == "ab...ij"
    assert mask_secret("1234567890", prefix_len=3, suffix_len=3) == "123...890"


def test_get_secret_nominal_and_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_secret retrieves from environment and raises on missing required."""
    monkeypatch.setenv("TEST_APP_SECRET", "super-secret-key-123")
    sec = get_secret("TEST_APP_SECRET", required=True)
    assert sec.get_secret_value() == "super-secret-key-123"

    # Default fallback when optional
    sec_def = get_secret("NON_EXISTENT_VAR", default="fallback-val")
    assert sec_def.get_secret_value() == "fallback-val"

    # Missing required raises ValueError
    with pytest.raises(ValueError, match="Required secret 'MISSING_SECRET' is missing"):
        get_secret("MISSING_SECRET", required=True)


def test_get_secret_blocks_insecure_defaults_in_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_secret rejects known placeholder credentials when environment='live'."""
    monkeypatch.setenv("LIVE_BROKER_KEY", "mock_key")
    with pytest.raises(SecurityError, match="Insecure placeholder credential detected"):
        get_secret("LIVE_BROKER_KEY", environment="live")

    # In test environment, insecure values are permitted
    sec_test = get_secret("LIVE_BROKER_KEY", environment="test")
    assert sec_test.get_secret_value() == "mock_key"


def test_validate_live_credentials_audit() -> None:
    """Verify validate_live_credentials detects insecure default patterns in live mode."""
    # Passes in test or non-live environment even with placeholders
    validate_live_credentials({"api_key": "mock_key"}, environment="paper")

    # Passes in live mode with valid production credentials
    validate_live_credentials(
        {"api_key": SecretStr("prod_kite_live_9981249120938"), "db_pwd": "StrongProdSecret!#99"},
        environment="live",
    )

    # Fails in live mode with insecure defaults
    with pytest.raises(SecurityError, match="contains insecure placeholder"):
        validate_live_credentials(
            {"api_key": SecretStr("mock_secret")},
            environment="live",
        )

    with pytest.raises(SecurityError, match="contains insecure placeholder"):
        validate_live_credentials(
            {"token": "operator-secret-token"},
            environment="live",
        )


def test_enforce_tls_transport_rules() -> None:
    """Verify enforce_tls_transport mandates TLS verification and HTTPS/WSS in live."""
    # In live mode, verify=False is unconditionally blocked (TRD-SEC-2, NFR-SEC-2)
    with pytest.raises(SecurityError, match=r"TLS certificate verification.*cannot be disabled"):
        enforce_tls_transport("https://api.kite.trade", verify=False, environment="live")

    # In live mode, remote plaintext HTTP / WS is blocked
    with pytest.raises(SecurityError, match="Insecure plaintext transport scheme"):
        enforce_tls_transport("http://api.kite.trade", verify=True, environment="live")

    with pytest.raises(SecurityError, match="Insecure plaintext transport scheme"):
        enforce_tls_transport("ws://ws.kite.trade", verify=True, environment="live")

    # In live mode, HTTPS and WSS with verify=True succeed
    enforce_tls_transport("https://api.kite.trade", verify=True, environment="live")
    enforce_tls_transport("wss://ws.kite.trade", verify=True, environment="live")

    # Local loopback is permitted for local service communication
    enforce_tls_transport("http://127.0.0.1:8000/api", verify=True, environment="live")
    enforce_tls_transport("http://localhost:5432", verify=True, environment="live")

    # In test/research mode, verify=False and http are permitted
    enforce_tls_transport("http://mock-broker.internal", verify=False, environment="test")


def test_secrets_manager_lifecycle() -> None:
    """Verify SecretsManager registration, rotation age tracking, and inventory audit."""
    mgr = SecretsManager(environment="test")
    mgr.register_secret("broker_api_key", "sec-abcdef123456")
    mgr.register_secret("db_password", SecretStr("db-strong-pass-789"))

    # Retrieval
    assert mgr.get("broker_api_key").get_secret_value() == "sec-abcdef123456"
    assert mgr.get("db_password").get_secret_value() == "db-strong-pass-789"

    # Age calculation
    age = mgr.get_rotation_age_days("broker_api_key")
    assert age >= 0.0

    # Unregistered key raises KeyError
    with pytest.raises(KeyError, match="Secret 'unknown_key' not found"):
        mgr.get("unknown_key")

    with pytest.raises(KeyError, match="has no recorded rotation timestamp"):
        mgr.get_rotation_age_days("unknown_key")

    # Audit inventory contains masked representations
    audit = mgr.audit_inventory()
    assert "broker_api_key" in audit
    assert audit["broker_api_key"]["masked"] == "se...56"
    assert "db_password" in audit

    # Live environment SecretsManager blocks registering insecure defaults
    live_mgr = SecretsManager(environment="live")
    with pytest.raises(SecurityError, match="contains insecure placeholder"):
        live_mgr.register_secret("bad_key", "mock_key")
