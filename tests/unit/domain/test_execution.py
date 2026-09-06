"""Unit tests for execution orders, positions, and model governance domain models."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.execution import OrderFill, OrderSubmission, Position
from src.domain.governance import ModelVersion


@pytest.mark.unit
def test_order_submission_lifecycle() -> None:
    """Verify order submission model, state transitions, and price validation."""
    now = datetime(2026, 9, 6, 9, 20, 0, tzinfo=UTC)
    order = OrderSubmission(
        client_order_id="ORD-20260906-001",
        broker_order_id="ZER-998822",
        instrument="NSE:INFY",
        direction="BUY",
        order_type="LIMIT",
        quantity=100,
        limit_price=Decimal("1850.50"),
        status="PENDING",
        submitted_at=now,
        updated_at=now,
    )
    assert order.client_order_id == "ORD-20260906-001"
    assert order.status == "PENDING"
    assert order.quantity == 100

    # Negative quantity rejected
    with pytest.raises(ValidationError):
        OrderSubmission(
            client_order_id="ORD-INVALID",
            instrument="NSE:INFY",
            direction="BUY",
            order_type="MARKET",
            quantity=-10,
            submitted_at=now,
            updated_at=now,
        )


@pytest.mark.unit
def test_position_tracking() -> None:
    """Verify position holding tracking with Decimal precision."""
    now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    pos = Position(
        instrument="NSE:HDFCBANK",
        quantity=75,
        average_entry_price=Decimal("1620.00"),
        current_market_price=Decimal("1650.00"),
        unrealized_pnl=Decimal("2250.00"),
        realized_pnl=Decimal("0.00"),
        updated_at=now,
    )
    assert pos.quantity == 75
    assert pos.unrealized_pnl == Decimal("2250.00")


@pytest.mark.unit
def test_model_version_governance() -> None:
    """Verify ML model version metadata, validation metrics, and promotion status."""
    now = datetime(2026, 9, 6, 8, 0, 0, tzinfo=UTC)
    model = ModelVersion(
        model_id="trend_classifier_xgb",
        model_name="GradientBoostedTrendClassifier",
        version_tag="v1.2.0",
        model_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        trained_at=now,
        status="promoted",
        validation_metrics={
            "sharpe_ratio": 2.15,
            "win_rate": 0.58,
            "max_drawdown": 0.042,
        },
        promoted_by="Agent 08 — Self-Learning",
        promotion_timestamp=now,
    )
    assert model.status == "promoted"
    assert model.validation_metrics["sharpe_ratio"] == 2.15
    assert len(model.model_hash) >= 32


@pytest.mark.unit
def test_execution_naive_timestamp_rejections() -> None:
    """Verify that execution models reject naive timestamps without timezone."""
    naive_dt = datetime(2026, 9, 6, 9, 0, 0)
    now_utc = datetime(2026, 9, 6, 9, 0, 0, tzinfo=UTC)

    # OrderSubmission naive submitted_at
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        OrderSubmission(
            client_order_id="ORD-1",
            instrument="NSE:INFY",
            direction="BUY",
            order_type="MARKET",
            quantity=10,
            submitted_at=naive_dt,
            updated_at=now_utc,
        )

    # Position naive updated_at
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        Position(
            instrument="NSE:INFY",
            quantity=10,
            updated_at=naive_dt,
        )

    # OrderFill naive timestamp
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        OrderFill(
            fill_id="f1",
            client_order_id="c1",
            instrument="NSE:INFY",
            direction="BUY",
            quantity=10,
            price=Decimal("1500.00"),
            timestamp=naive_dt,
        )

    # ModelVersion naive trained_at
    with pytest.raises(ValidationError, match="Timestamp must be timezone-aware UTC"):
        ModelVersion(
            model_id="m1",
            model_name="Model 1",
            version_tag="v1.0.0",
            model_hash="0123456789abcdef0123456789abcdef",
            trained_at=naive_dt,
            validation_metrics={"sharpe": 1.5},
        )


@pytest.mark.unit
def test_order_fill_model_valid() -> None:
    """Verify OrderFill entity instantiation and attributes."""
    now = datetime(2026, 9, 6, 9, 30, 0, tzinfo=UTC)
    fill = OrderFill(
        fill_id="fill-001",
        client_order_id="ORD-001",
        instrument="NSE:TCS",
        direction="BUY",
        quantity=50,
        price=Decimal("3500.25"),
        commission=Decimal("15.50"),
        timestamp=now,
    )
    assert fill.fill_id == "fill-001"
    assert fill.instrument == "NSE:TCS"
    assert fill.direction == "BUY"
    assert fill.quantity == 50
    assert fill.price == Decimal("3500.25")
    assert fill.commission == Decimal("15.50")
    assert fill.timestamp == now
