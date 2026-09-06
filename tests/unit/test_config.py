"""Unit tests for the centralized configuration engine and Pydantic models."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.config.models import (
    AppConfig,
    BrokerConfig,
    DatabaseConfig,
)
from src.config.settings import (
    _validate_live_invariants,
    get_settings,
    load_settings,
)


@pytest.mark.unit
def test_default_settings_loading() -> None:
    """Verify default settings instantiation and baseline boundaries."""
    config = load_settings(environment_override="test")
    assert config.environment == "test"
    assert config.version == "0.1.0"
    assert config.risk.initial_capital_inr == 10000.0
    assert config.risk.max_daily_loss_pct == 0.02
    assert config.risk.max_drawdown_pct == 0.05
    assert config.risk.max_position_size_pct == 0.05
    assert config.risk.max_exposure_pct == 0.50
    assert config.risk.max_consecutive_losses == 3
    assert config.broker.paper_trading is True


@pytest.mark.unit
def test_env_example_loads_cleanly() -> None:
    """Verify that the official .env.example file passes validation."""
    env_example_path = Path(".env.example")
    assert env_example_path.exists(), ".env.example must exist in repository root"

    config = load_settings(env_file=env_example_path, environment_override="test")
    assert config.db.host == "localhost"
    assert config.db.port == 5432
    assert config.db.database == "ai_trader"


@pytest.mark.unit
def test_secret_str_masking() -> None:
    """Verify that sensitive credentials are never revealed in plain text."""
    config = load_settings(environment_override="test")
    raw_str = str(config.db.password)
    assert "postgres" not in raw_str
    assert "**********" in raw_str
    assert config.db.password.get_secret_value() == "postgres"

    broker_key_str = str(config.broker.api_key)
    assert "mock_key" not in broker_key_str
    assert "**********" in broker_key_str


@pytest.mark.unit
def test_model_immutability() -> None:
    """Verify that configuration models are strictly frozen and immutable."""
    config = load_settings(environment_override="test")

    attr_env = "environment"
    with pytest.raises(ValidationError):
        setattr(config, attr_env, "live")

    attr_loss = "max_daily_loss_pct"
    with pytest.raises(ValidationError):
        setattr(config.risk, attr_loss, 0.50)

    attr_port = "port"
    with pytest.raises(ValidationError):
        setattr(config.db, attr_port, 9999)


@pytest.mark.unit
def test_live_environment_invariants() -> None:
    """Verify that live environment aborts on paper trading or mock credentials."""
    # Attempt live with paper trading enabled
    with pytest.raises(ValueError, match=r"Live environment cannot run with broker\.paper_trading"):
        load_settings(environment_override="live")

    # Invalid live with mock api_key
    with pytest.raises(
        ValueError, match=r"Live environment requires a real non-mock broker\.api_key"
    ):
        _validate_live_invariants(
            AppConfig(
                environment="live",
                broker=BrokerConfig(
                    paper_trading=False,
                    api_key=SecretStr("mock_key"),
                    api_secret=SecretStr("real_secret"),
                ),
            )
        )

    # Invalid live with mock api_secret
    with pytest.raises(
        ValueError, match=r"Live environment requires a real non-mock broker\.api_secret"
    ):
        _validate_live_invariants(
            AppConfig(
                environment="live",
                broker=BrokerConfig(
                    paper_trading=False,
                    api_key=SecretStr("real_key"),
                    api_secret=SecretStr("mock_secret"),
                ),
            )
        )

    # Valid live configuration passes
    valid_live = AppConfig(
        environment="live",
        broker=BrokerConfig(
            paper_trading=False,
            api_key=SecretStr("actual_live_api_key"),
            api_secret=SecretStr("actual_live_api_secret"),
        ),
    )
    _validate_live_invariants(valid_live)


@pytest.mark.unit
def test_database_connection_url_generation() -> None:
    """Verify dynamic construction of async and sync PostgreSQL URLs."""
    db = DatabaseConfig(
        host="127.0.0.1",
        port=5433,
        user="trader_user",
        password=SecretStr("secret_password"),
        database="market_data",
    )
    async_url = db.get_connection_url(async_driver=True)
    expected_async = "postgresql+asyncpg://trader_user:secret_password@127.0.0.1:5433/market_data"
    assert async_url == expected_async

    sync_url = db.get_connection_url(async_driver=False)
    expected_sync = "postgresql://trader_user:secret_password@127.0.0.1:5433/market_data"
    assert sync_url == expected_sync


@pytest.mark.unit
def test_invalid_environment_aborts() -> None:
    """Verify that unrecognized environment strings raise ValueError."""
    with pytest.raises(ValueError, match="Invalid environment"):
        load_settings(environment_override="unsupported_environment")


@pytest.mark.unit
def test_cached_get_settings() -> None:
    """Verify that get_settings provides singleton cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
