"""Pydantic data models and response schemas for FastAPI Control Backend."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AccountResponse(BaseModel):
    """Account state snapshot response per FRD-DASH-1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_capital: Decimal = Field(description="Current total portfolio equity in INR")
    initial_capital: Decimal = Field(description="Session or initial allocated capital in INR")
    peak_equity: Decimal = Field(description="Peak total equity achieved in INR")
    total_pnl: Decimal = Field(description="Cumulative total profit or loss in INR")
    daily_pnl: Decimal = Field(description="Session daily profit or loss in INR")
    drawdown_amount: Decimal = Field(description="Current drawdown amount in INR")
    drawdown_pct: float = Field(description="Current drawdown percentage [0.0, 100.0]")
    open_position_count: int = Field(ge=0, description="Count of open positions")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Point-in-time timestamp in UTC",
    )


class PositionItem(BaseModel):
    """Position representation in trading state response per FRD-DASH-2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str = Field(description="Instrument identifier")
    quantity: int = Field(description="Position quantity (+ for long, - for short)")
    average_entry_price: Decimal = Field(description="Average cost basis per unit")
    current_market_price: Decimal = Field(description="Latest mark-to-market unit price")
    unrealized_pnl: Decimal = Field(description="Unrealized mark-to-market P&L in INR")
    realized_pnl: Decimal = Field(description="Realized P&L in INR")


class OrderItem(BaseModel):
    """Order representation in trading state response per FRD-DASH-2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str = Field(description="Deterministic client order ID")
    broker_order_id: str | None = Field(default=None, description="Broker assigned order ID")
    instrument: str = Field(description="Instrument identifier")
    direction: str = Field(description="BUY or SELL")
    quantity: int = Field(gt=0, description="Order quantity")
    order_type: str = Field(description="LIMIT or MARKET")
    limit_price: Decimal | None = Field(default=None, description="Limit price if LIMIT order")
    status: str = Field(description="Order lifecycle status")
    submitted_at: datetime = Field(description="Order submission timestamp in UTC")


class TradeItem(BaseModel):
    """Completed trade representation per FRD-DASH-2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str = Field(description="Trade identifier")
    instrument: str = Field(description="Instrument identifier")
    direction: str = Field(description="BUY or SELL")
    quantity: int = Field(gt=0, description="Executed quantity")
    entry_price: Decimal = Field(description="Executed entry unit price")
    exit_price: Decimal | None = Field(default=None, description="Executed exit unit price")
    realized_pnl: Decimal = Field(description="Net realized profit or loss in INR")
    timestamp: datetime = Field(description="Trade execution or completion timestamp in UTC")


class TradingResponse(BaseModel):
    """Trading state snapshot response per FRD-DASH-2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    positions: list[PositionItem] = Field(
        default_factory=list, description="Currently open or active positions"
    )
    open_orders: list[OrderItem] = Field(
        default_factory=list, description="Working non-terminal orders"
    )
    completed_trades: list[TradeItem] = Field(
        default_factory=list, description="Recently completed or filled trades"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot timestamp in UTC",
    )


class AgentSignalItem(BaseModel):
    """Agent signal output item per FRD-DASH-3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(description="Unique agent identifier")
    direction: str = Field(description="Signal direction (BUY, SELL, HOLD, NO_TRADE)")
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence score [0.0, 1.0]")
    trade_quality_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Quality score [0.0, 1.0]"
    )
    reason: str | None = Field(default=None, description="Rationale description")


class AIStateResponse(BaseModel):
    """AI and market regime state snapshot response per FRD-DASH-3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime_label: str = Field(description="Composite canonical regime string")
    trend_state: str = Field(description="Trend state (e.g. TRENDING_UP, RANGING)")
    volatility_level: str = Field(description="Volatility level (LOW, NORMAL, HIGH)")
    directional_bias: str = Field(description="Directional bias (BULLISH, BEARISH, NEUTRAL)")
    liquidity_condition: str = Field(description="Liquidity condition (NORMAL, DEGRADED)")
    active_model_version: str = Field(description="Currently promoted model version tag")
    agent_signals: list[AgentSignalItem] = Field(
        default_factory=list, description="Active agent signals from roster"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot timestamp in UTC",
    )


class RiskStateResponse(BaseModel):
    """Deterministic risk boundary status response per FRD-DASH-4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_exposure: Decimal = Field(description="Currently deployed capital in INR")
    max_exposure_limit: Decimal = Field(description="Maximum allowable exposure in INR")
    daily_risk_used: Decimal = Field(description="Current session daily loss in INR")
    daily_risk_limit: Decimal = Field(description="Maximum daily loss boundary in INR")
    kill_switch_active: bool = Field(description="Whether kill switch is currently engaged")
    consecutive_losses: int = Field(ge=0, description="Consecutive losing trades count")
    session_paused: bool = Field(description="Whether session trading is paused due to streak")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot timestamp in UTC",
    )


class ComponentHealth(BaseModel):
    """Health diagnostic for an individual architectural component per TRD-OBS-4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Component name")
    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        description="Health status indicator"
    )
    message: str | None = Field(default=None, description="Diagnostic message or anomaly details")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Component-specific telemetry metrics"
    )


class HealthResponse(BaseModel):
    """Comprehensive system health diagnostics response per TRD-OBS-4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        description="Aggregated overall system health"
    )
    kill_switch_active: bool = Field(description="Whether emergency kill switch is active")
    system_phase: str = Field(description="Active market session or system phase")
    components: dict[str, ComponentHealth] = Field(
        description="Individual subsystem health metrics"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Health check timestamp in UTC",
    )


class ControlStopRequest(BaseModel):
    """Request payload for manual STOP trigger per FRD-DASH-7."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(
        default="Manual operator emergency STOP triggered via dashboard",
        description="Operator explanation for triggering emergency stop",
    )


class ControlStopResponse(BaseModel):
    """Response payload following STOP trigger execution per FRD-DASH-7."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["halted"] = Field(default="halted", description="Execution halt status")
    kill_switch_active: bool = Field(default=True, description="Confirmation of active kill switch")
    operator: str = Field(description="Operator identifier")
    reason: str = Field(description="Recorded reason for emergency stop")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Stop trigger execution timestamp in UTC",
    )


class ControlResetRequest(BaseModel):
    """Request payload for manual STOP reset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(
        default="Operator manual reset after risk review",
        description="Operator justification for resuming trading",
    )


class ControlResetResponse(BaseModel):
    """Response payload following STOP reset execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["active"] = Field(default="active", description="Execution active status")
    kill_switch_active: bool = Field(default=False, description="Confirmation of reset kill switch")
    operator: str = Field(description="Operator identifier")
    reason: str = Field(description="Recorded reason for reset")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Reset timestamp in UTC",
    )


class MarketInfo(BaseModel):
    """Metadata describing an available trading market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str = Field(description="Unique market identifier, e.g. NSE_EQUITY")
    name: str = Field(description="Display name, e.g. Indian Equities (NSE)")
    category: str = Field(description="Market category, e.g. Equities, Forex, Crypto")
    currency: str = Field(description="Base currency code, e.g. INR, USD")
    currency_symbol: str = Field(description="Currency display symbol, e.g. ₹, $")
    trading_hours: str = Field(description="Active trading hours, e.g. 09:15 - 15:30 IST")
    instruments: list[str] = Field(description="Available instrument symbols in this market")
    default_symbol: str = Field(description="Default active symbol for this market")


class MarketStateResponse(BaseModel):
    """Current active market state and list of available markets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_market_id: str = Field(description="Currently active market ID")
    active_market_name: str = Field(description="Currently active market display name")
    active_symbol: str = Field(description="Currently active instrument symbol")
    currency_symbol: str = Field(description="Active currency symbol")
    trading_hours: str = Field(description="Active trading hours")
    available_markets: list[MarketInfo] = Field(description="List of all supported markets")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Response generation timestamp in UTC",
    )


class MarketSwitchRequest(BaseModel):
    """Request payload to switch active market and symbol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str = Field(description="Target market identifier to switch to")
    symbol: str | None = Field(default=None, description="Optional target symbol within market")
