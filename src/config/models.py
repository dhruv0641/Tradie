"""Canonical configuration models with strict typing and secret masking."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.risk.config import RiskConfig

__all__ = [
    "AggregatorConfig",
    "ApiConfig",
    "AppConfig",
    "BrokerConfig",
    "DataConfig",
    "DatabaseConfig",
    "RegimeConfig",
    "RiskConfig",
]


class DatabaseConfig(BaseModel):
    """PostgreSQL and TimescaleDB storage configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(default="localhost", description="Database host address")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    user: str = Field(default="postgres", min_length=1, description="Database username")
    password: SecretStr = Field(
        default=SecretStr("postgres"), description="Database password (masked)"
    )
    database: str = Field(default="ai_trader", min_length=1, description="Database name")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    ssl_mode: str = Field(default="prefer", description="PostgreSQL SSL mode")

    def get_connection_url(self, async_driver: bool = True) -> str:
        """Construct database connection URL with unmasked credentials."""
        driver = "postgresql+asyncpg" if async_driver else "postgresql"
        pwd = self.password.get_secret_value()
        return f"{driver}://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"


class BrokerConfig(BaseModel):
    """Broker API configuration supporting paper and live trading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_name: str = Field(default="zerodha", description="Broker identifier")
    api_key: SecretStr = Field(default=SecretStr("mock_key"), description="Broker API key (masked)")
    api_secret: SecretStr = Field(
        default=SecretStr("mock_secret"), description="Broker API secret (masked)"
    )
    base_url: str = Field(
        default="https://api.kite.trade", description="Broker REST API base endpoint"
    )
    access_token: SecretStr | None = Field(
        default=None, description="Active broker session access token (masked)"
    )
    totp_secret: SecretStr | None = Field(
        default=None, description="Broker 2FA TOTP secret key (masked)"
    )
    timeout_seconds: float = Field(
        default=10.0, ge=1.0, le=60.0, description="HTTP request timeout in seconds"
    )
    paper_trading: bool = Field(
        default=True, description="Flag indicating simulated paper execution vs live execution"
    )
    reconnection_window_s: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Reconnection deadline in seconds upon broker disconnection (RTLD-15)",
    )


class DataConfig(BaseModel):
    """Market data validation, staleness SLA, and pipeline configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_staleness_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        description="Maximum allowable market feed staleness in seconds (NFR-DATA-1)",
    )
    max_price_jump_pct: float = Field(
        default=0.20,
        ge=0.01,
        le=1.0,
        description="Single-bar percentage return threshold for anomaly filtering (FRD-DATA-7)",
    )
    allow_zero_volume: bool = Field(
        default=True,
        description="Whether zero-volume bars are permitted without quarantine",
    )


class RegimeConfig(BaseModel):
    """Market regime classification and transition detection parameters (MLD §5, §11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adx_threshold: float = Field(
        default=25.0,
        gt=0.0,
        le=100.0,
        description="ADX threshold separating trending from ranging states (MLD §5.1)",
    )
    volatility_window: int = Field(
        default=200,
        ge=20,
        le=1000,
        description="Trailing window for percentile volatility calculation (MLD §5.1, §11)",
    )
    volatility_low_percentile: float = Field(
        default=33.0,
        ge=1.0,
        le=50.0,
        description="Percentile cutoff for LOW volatility classification",
    )
    volatility_high_percentile: float = Field(
        default=67.0,
        ge=50.0,
        le=99.0,
        description="Percentile cutoff for HIGH volatility classification",
    )
    liquidity_volume_ratio_threshold: float = Field(
        default=0.50,
        gt=0.0,
        le=2.0,
        description="Volume ratio below which liquidity is classified DEGRADED (MLD §5.1)",
    )
    hysteresis_cycles: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Consecutive cycles required to confirm a regime transition (MLD §5.2, §11)",
    )


class AggregatorConfig(BaseModel):
    """Configuration settings for multi-agent signal aggregation and dynamic timeframe selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "trend_agent": 0.25,
            "momentum_agent": 0.25,
            "mean_reversion_agent": 0.25,
            "price_action_agent": 0.25,
        },
        description="Initial baseline weighting scheme across the agent roster (MLD §7.1)",
    )
    min_quality_threshold: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="Minimum trade quality score Q threshold to pass opportunity (FRD-AGG-6)",
    )
    candidate_timeframes: list[str] = Field(
        default_factory=lambda: ["5m", "15m", "1h"],
        description="List of candidate timeframes evaluated for dynamic selection (FRD-AGG-3)",
    )


class ApiConfig(BaseModel):
    """FastAPI Control Backend and Operator Dashboard configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(default="127.0.0.1", description="API host address")
    port: int = Field(default=8000, ge=1, le=65535, description="API listen port")
    operator_token: SecretStr = Field(
        default=SecretStr("operator-secret-token"),
        description="Bearer token required for operator control endpoints (masked)",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
        ],
        description="Allowed CORS origin URLs",
    )
    docs_enabled: bool = Field(
        default=True, description="Whether OpenAPI / Swagger UI documentation is enabled"
    )
    static_ui_dir: str = Field(
        default="ui", description="Directory path containing operator dashboard static assets"
    )


class AppConfig(BaseModel):
    """Master application configuration encapsulating all architectural subsystems."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: Literal["research", "paper", "live", "test"] = Field(
        default="test", description="Target execution environment"
    )
    version: str = Field(default="0.1.0", description="Application release version")
    log_level: str = Field(default="INFO", description="Log verbosity level")
    db: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Database settings")
    risk: RiskConfig = Field(default_factory=RiskConfig, description="Risk boundaries")
    broker: BrokerConfig = Field(default_factory=BrokerConfig, description="Broker settings")
    data: DataConfig = Field(
        default_factory=DataConfig, description="Market data pipeline settings"
    )
    regime: RegimeConfig = Field(
        default_factory=RegimeConfig, description="Market regime intelligence settings"
    )
    aggregator: AggregatorConfig = Field(
        default_factory=AggregatorConfig,
        description="Multi-agent signal aggregation settings",
    )
    api: ApiConfig = Field(
        default_factory=ApiConfig,
        description="FastAPI control backend and dashboard settings",
    )
