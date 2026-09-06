"""Environment-aware configuration loader using pydantic-settings."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.models import (
    AppConfig,
    BrokerConfig,
    DatabaseConfig,
    RiskConfig,
)


class SettingsLoader(BaseSettings):
    """Internal pydantic-settings bridge to read environment variables and dot-env files."""

    model_config = SettingsConfigDict(
        env_prefix="AI_TRADER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["research", "paper", "live", "test"] = "test"
    version: str = "0.1.0"
    log_level: str = "INFO"

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "ai_trader"
    db_pool_size: int = 10
    db_ssl_mode: str = "prefer"

    # Risk
    risk_max_daily_loss_pct: float = 0.02
    risk_max_drawdown_pct: float = 0.05
    risk_max_position_size_pct: float = 0.05
    risk_max_exposure_pct: float = 0.50
    risk_max_consecutive_losses: int = 3
    risk_initial_capital_inr: float = 10000.0

    # Broker
    broker_name: str = "zerodha"
    broker_api_key: str = "mock_key"
    broker_api_secret: str = "mock_secret"
    broker_paper_trading: bool = True
    broker_reconnection_window_s: int = 30


def load_settings(
    env_file: Path | str | None = None,
    environment_override: str | None = None,
) -> AppConfig:
    """Load, validate, and construct immutable AppConfig from environment and env files."""
    env_name = (environment_override or os.environ.get("AI_TRADER_ENV") or "test").lower()

    if env_name not in ("research", "paper", "live", "test"):
        msg = f"Invalid environment: '{env_name}'. Must be one of: research, paper, live, test"
        raise ValueError(msg)

    # Determine env file candidates
    selected_env_file: str | None = None
    if env_file is not None:
        selected_env_file = str(env_file)
    else:
        env_specific = Path(f".env.{env_name}")
        default_env = Path(".env")
        if env_specific.exists():
            selected_env_file = str(env_specific)
        elif default_env.exists():
            selected_env_file = str(default_env)

    loader = SettingsLoader(
        _env_file=selected_env_file,  # type: ignore[call-arg]
        _env_file_encoding="utf-8",
        environment=env_name,  # type: ignore[arg-type]
    )

    db_config = DatabaseConfig(
        host=loader.db_host,
        port=loader.db_port,
        user=loader.db_user,
        password=loader.db_password,  # type: ignore[arg-type]
        database=loader.db_name,
        pool_size=loader.db_pool_size,
        ssl_mode=loader.db_ssl_mode,
    )

    risk_config = RiskConfig(
        max_daily_loss_pct=loader.risk_max_daily_loss_pct,
        max_drawdown_pct=loader.risk_max_drawdown_pct,
        max_position_size_pct=loader.risk_max_position_size_pct,
        max_exposure_pct=loader.risk_max_exposure_pct,
        max_consecutive_losses=loader.risk_max_consecutive_losses,
        initial_capital_inr=loader.risk_initial_capital_inr,
    )

    broker_config = BrokerConfig(
        broker_name=loader.broker_name,
        api_key=loader.broker_api_key,  # type: ignore[arg-type]
        api_secret=loader.broker_api_secret,  # type: ignore[arg-type]
        paper_trading=loader.broker_paper_trading,
        reconnection_window_s=loader.broker_reconnection_window_s,
    )

    app_config = AppConfig(
        environment=loader.environment,
        version=loader.version,
        log_level=loader.log_level,
        db=db_config,
        risk=risk_config,
        broker=broker_config,
    )

    # Enforce TRD-DEPLOY-2 and security invariants
    _validate_live_invariants(app_config)

    return app_config


def _validate_live_invariants(config: AppConfig) -> None:
    """Ensure live environment cannot run with mock credentials or paper trading."""
    if config.environment == "live":
        if config.broker.paper_trading:
            msg = "Live environment cannot run with broker.paper_trading = True"
            raise ValueError(msg)

        api_key = config.broker.api_key.get_secret_value()
        api_secret = config.broker.api_secret.get_secret_value()
        if not api_key or api_key in ("mock_key", "test_key"):
            msg = "Live environment requires a real non-mock broker.api_key"
            raise ValueError(msg)
        if not api_secret or api_secret in ("mock_secret", "test_secret"):
            msg = "Live environment requires a real non-mock broker.api_secret"
            raise ValueError(msg)


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Cached accessor for application settings."""
    return load_settings()
