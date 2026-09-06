"""Risk configuration binding RTLD §14 Numeric Parameter Register."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RiskConfig(BaseModel):
    """Externalized, versioned configuration parameter register adhering to RTLD §14."""

    model_config = ConfigDict(frozen=True, extra="allow")

    # RTLD-1: Initial Capital
    initial_live_capital: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="RTLD-1: Initial live capital allocation in INR (₹10,000)",
    )
    initial_capital_inr: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="Alias for initial_live_capital for backwards compatibility",
    )

    # RTLD-2: Extreme-case tolerance ceiling
    extreme_tolerance_ceiling: Decimal = Field(
        default=Decimal("1000.00"),
        gt=Decimal("0"),
        description="RTLD-2: Extreme-case tolerance ceiling (₹1,000, 10% of capital)",
    )

    # RTLD-3: Max Risk Per Trade
    max_risk_per_trade_pct: Decimal = Field(
        default=Decimal("0.01"),
        gt=Decimal("0"),
        le=Decimal("0.05"),
        description="RTLD-3: Maximum capital risk per trade (1% = ₹100)",
    )

    # RTLD-4: Max Daily Loss
    max_daily_loss_pct: Decimal = Field(
        default=Decimal("0.03"),
        gt=Decimal("0"),
        le=Decimal("0.10"),
        description="RTLD-4: Maximum loss per trading session (3% = ₹300)",
    )

    # RTLD-5: Hard Drawdown Halt
    hard_drawdown_halt_pct: Decimal = Field(
        default=Decimal("0.08"),
        gt=Decimal("0"),
        le=Decimal("0.15"),
        description="RTLD-5: Hard drawdown halt threshold requiring manual resume (8% = ₹800)",
    )
    max_drawdown_pct: Decimal = Field(
        default=Decimal("0.08"),
        gt=Decimal("0"),
        le=Decimal("0.20"),
        description="Alias for hard_drawdown_halt_pct for backwards compatibility",
    )

    # RTLD-6: Extreme-Loss Killswitch Trigger
    extreme_loss_killswitch_pct: Decimal = Field(
        default=Decimal("0.10"),
        gt=Decimal("0"),
        le=Decimal("0.20"),
        description=(
            "RTLD-6: Extreme-loss circuit breaker automatically triggering kill switch (10%)"
        ),
    )

    # RTLD-7: Max Portfolio Exposure
    max_portfolio_exposure_pct: Decimal = Field(
        default=Decimal("0.50"),
        gt=Decimal("0"),
        le=Decimal("1.00"),
        description="RTLD-7: Maximum total portfolio capital exposure (50% = ₹5,000)",
    )
    max_exposure_pct: Decimal = Field(
        default=Decimal("0.50"),
        gt=Decimal("0"),
        le=Decimal("1.00"),
        description="Alias for max_portfolio_exposure_pct for backwards compatibility",
    )

    # RTLD-8: Max Single Position Size
    max_position_size_pct: Decimal = Field(
        default=Decimal("0.20"),
        gt=Decimal("0"),
        le=Decimal("0.50"),
        description="RTLD-8: Maximum single position size (20% = ₹2,000)",
    )

    # RTLD-9: Max Simultaneous Positions
    max_simultaneous_positions: int = Field(
        default=3,
        gt=0,
        le=10,
        description="RTLD-9: Maximum simultaneous open positions (3)",
    )

    # RTLD-10: Max Trades Per Day
    max_trades_per_day: int = Field(
        default=5,
        gt=0,
        le=20,
        description="RTLD-10: Maximum trades allowed per trading session (5)",
    )

    # RTLD-11: Consecutive Loss Size Reduction
    consec_loss_reduce_trigger: int = Field(
        default=3,
        gt=0,
        description="RTLD-11: Consecutive losses triggering 50% size reduction (3 losses)",
    )
    max_consecutive_losses: int = Field(
        default=3,
        gt=0,
        description="Alias for consec_loss_reduce_trigger for backwards compatibility",
    )

    # RTLD-12: Consecutive Loss Session Pause
    consec_loss_pause_trigger: int = Field(
        default=5,
        gt=0,
        description="RTLD-12: Consecutive losses triggering session pause (5 losses)",
    )

    # RTLD-13 & RTLD-14: Volatility Multiples
    vol_reduce_multiple: Decimal = Field(
        default=Decimal("2.0"),
        gt=Decimal("1.0"),
        description=(
            "RTLD-13: Abnormal volatility threshold triggering 50% size reduction (2.0x avg)"
        ),
    )
    vol_block_multiple: Decimal = Field(
        default=Decimal("3.0"),
        gt=Decimal("1.0"),
        description="RTLD-14: Extreme volatility threshold blocking new entries (3.0x avg)",
    )

    # RTLD-15: Broker Reconnect Window
    broker_reconnect_window_sec: int = Field(
        default=30,
        gt=0,
        description="RTLD-15: Broker reconnection window before emergency escalation (30s)",
    )

    # RTLD-16: Model Confidence Threshold
    min_confidence_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="RTLD-16: Minimum composite confidence/quality score to approve entry (0.60)",
    )

    # RTLD-17: Kill Switch Max Latency
    killswitch_max_latency_sec: float = Field(
        default=2.0,
        gt=0.0,
        description="RTLD-17: Kill switch activation latency target (<2.0s)",
    )

    # Active Config Version Tag
    version: str = Field(
        default="1.0.0",
        min_length=1,
        description="Version tag of active RiskConfig for immutable audit trail",
    )
