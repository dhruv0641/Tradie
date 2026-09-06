"""SQLAlchemy 2.0 relational and time-series ORM models conforming to DDD §6 and TRD §6."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base declarative class for all database tables."""

    pass


# Use JSONB for PostgreSQL dialect when available, falling back to JSON for standard SQL
JsonType = JSON().with_variant(JSONB, "postgresql")


class OHLCVCandleModel(Base):
    """TimescaleDB hypertable model for canonical OHLCV candle streams (DDD §6)."""

    __tablename__ = "ohlcv_candles"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    instrument: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    turnover: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quality_state: Mapped[str] = mapped_column(String(16), default="RAW", nullable=False)


class DecisionRecordModel(Base):
    """Immutable append-only decision audit record table (BRD BR-7, DDD §6)."""

    __tablename__ = "decision_records"

    decision_record_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    data_quality_state: Mapped[str] = mapped_column(String(16), nullable=False)
    regime_classification: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    agent_outputs: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    trade_quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    disagreement_metric: Mapped[float] = mapped_column(Float, nullable=False)
    risk_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failed_check: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rtld_param_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    final_decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("idx_dec_inst_time", "instrument", timestamp.desc()),
        Index("idx_dec_decision", "final_decision", timestamp.desc()),
    )


class TradeEvaluationModel(Base):
    """Post-trade attribution and variance evaluation record (DDD §6)."""

    __tablename__ = "trade_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    decision_record_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("decision_records.decision_record_id"),
        nullable=False,
    )
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_cost_drag: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    pnl_variance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    variance_driver: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelVersionModel(Base):
    """Machine learning model artifact registry and governance metadata (DDD §6)."""

    __tablename__ = "model_versions"

    model_version_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    architecture_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    git_commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_in_production: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ValidationRunModel(Base):
    """Model validation run record across promotion gates (DDD §6, BTD §8)."""

    __tablename__ = "validation_runs"

    validation_run_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    model_version_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("model_versions.model_version_id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    sortino_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    walk_forward_efficiency_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_stage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_payload_json: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)


class OrderSubmissionModel(Base):
    """Order lifecycle execution and fill tracking table (TRD-EXEC-2, DDD §6)."""

    __tablename__ = "order_submissions"

    client_order_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    decision_record_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("decision_records.decision_record_id"),
        nullable=True,
    )
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_fill_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PositionModel(Base):
    """Live open and closed portfolio position tracking table (DDD §6)."""

    __tablename__ = "positions"

    instrument: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    current_market_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    peak_unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
