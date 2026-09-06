"""Unit tests for continuous degradation monitor and automated model rollback.

Conforms to FRD-LEARN-6, FRD-LEARN-7, ADD §8.4, SLD §7.2, §8, and SOW §6.8:
- Drawdown breach automated rollback
- Consecutive losses circuit breaker
- Win rate collapse detection
- Rolling Sharpe statistical deterioration trigger
- Promotion throttle after repeated rollbacks
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from src.domain.evaluation import TradeEvaluation
from src.domain.governance import ModelVersion
from src.governance.rollback_monitor import (
    RollbackMonitor,
    RollbackMonitorConfig,
)


def _make_model(
    model_id: str,
    *,
    sharpe: float = 1.8,
    status: Literal["candidate", "promoted", "rolled_back", "rejected", "superseded"] = "promoted",
) -> ModelVersion:
    """Create a ModelVersion for rollback monitoring."""
    return ModelVersion(
        model_id=model_id,
        model_name=f"Model_{model_id}",
        version_tag="v1.0.0",
        model_hash="b" * 64,
        trained_at=datetime.now(UTC),
        status=status,
        validation_metrics={"sharpe_ratio": sharpe, "max_drawdown_pct": 5.0},
    )


def _make_trade(pnl: Decimal, offset_minutes: int = 0) -> TradeEvaluation:
    """Create a single evaluated trade."""
    now = datetime.now(UTC)
    is_win = pnl > Decimal("0")
    return TradeEvaluation(
        trade_id=uuid4(),
        entry_decision_id=uuid4(),
        exit_decision_id=uuid4(),
        instrument="NSE:RELIANCE",
        direction="BUY",
        entry_price=Decimal("2500.00"),
        exit_price=Decimal("2510.00") if is_win else Decimal("2490.00"),
        quantity=10,
        gross_pnl=pnl + Decimal("5.00"),
        net_pnl=pnl,
        total_slippage=Decimal("2.50"),
        statutory_costs=Decimal("2.50"),
        variance_driver="good_trade" if is_win else "bad_timing",
        rule_adherence=True,
        entry_timestamp=now - timedelta(minutes=offset_minutes + 10),
        exit_timestamp=now - timedelta(minutes=offset_minutes),
        evaluated_at=now,
    )


def test_healthy_trade_stream_no_rollback() -> None:
    """Test that a healthy, profitable trade stream produces no rollback events."""
    monitor = RollbackMonitor()
    active_model = _make_model("active_v2")
    fallback_model = _make_model("fallback_v1")

    for i in range(15):
        pnl = Decimal("100.00") if i % 3 != 0 else Decimal("-30.00")
        trade = _make_trade(pnl, offset_minutes=15 - i)
        event = monitor.process_completed_trade(
            trade, active_model=active_model, fallback_model=fallback_model
        )
        assert event is None

    assert active_model.status == "promoted"
    assert len(monitor.rollback_history) == 0


def test_drawdown_breach_triggers_immediate_rollback() -> None:
    """Test that exceeding the max drawdown ceiling immediately reverts the model."""
    config = RollbackMonitorConfig(max_drawdown_limit_pct=8.0)
    monitor = RollbackMonitor(config=config)
    active_model = _make_model("active_v2")
    fallback_model = _make_model("fallback_v1", status="superseded")

    # Start with ₹10,000. Inject a single severe loss of ₹900 (9.0% drawdown)
    big_loss_trade = _make_trade(Decimal("-900.00"))
    event = monitor.process_completed_trade(
        big_loss_trade, active_model=active_model, fallback_model=fallback_model
    )

    assert event is not None
    assert event.trigger_reason == "DRAWDOWN_BREACH"
    assert event.failed_model_id == "active_v2"
    assert event.restored_model_id == "fallback_v1"
    assert active_model.status == "rolled_back"
    assert fallback_model.status == "promoted"
    assert len(monitor.rollback_history) == 1


def test_consecutive_losses_triggers_rollback() -> None:
    """Test that hitting the consecutive losses limit triggers rollback."""
    config = RollbackMonitorConfig(max_consecutive_losses=5, max_drawdown_limit_pct=20.0)
    monitor = RollbackMonitor(config=config)
    active_model = _make_model("active_v2")
    fallback_model = _make_model("fallback_v1")

    # Inject 4 losses (should not trigger yet)
    for i in range(4):
        event = monitor.process_completed_trade(
            _make_trade(Decimal("-50.00"), offset_minutes=10 - i),
            active_model=active_model,
            fallback_model=fallback_model,
        )
        assert event is None

    # 5th consecutive loss triggers rollback
    fifth_loss = _make_trade(Decimal("-50.00"))
    event = monitor.process_completed_trade(
        fifth_loss, active_model=active_model, fallback_model=fallback_model
    )

    assert event is not None
    assert event.trigger_reason == "CONSECUTIVE_LOSSES"
    assert event.evidence["consecutive_losses"] == 5
    assert active_model.status == "rolled_back"


def test_win_rate_collapse_triggers_rollback() -> None:
    """Test that a collapse in win rate across the window triggers rollback."""
    config = RollbackMonitorConfig(
        window_size=10,
        min_rolling_win_rate=0.30,
        max_drawdown_limit_pct=25.0,
        max_consecutive_losses=10,
    )
    monitor = RollbackMonitor(config=config)
    active_model = _make_model("active_v2")
    fallback_model = _make_model("fallback_v1")

    # Inject 10 trades with only 2 wins (20% win rate, below 30% floor)
    # Win pattern: L, W, L, L, W, L, L, L, L, L
    pnl_sequence = [
        Decimal("-10.00"),
        Decimal("20.00"),
        Decimal("-10.00"),
        Decimal("-10.00"),
        Decimal("20.00"),
        Decimal("-10.00"),
        Decimal("-10.00"),
        Decimal("-10.00"),
        Decimal("-10.00"),
        Decimal("-10.00"),
    ]

    event = None
    for pnl in pnl_sequence:
        event = monitor.process_completed_trade(
            _make_trade(pnl),
            active_model=active_model,
            fallback_model=fallback_model,
        )
        if event is not None:
            break

    assert event is not None
    assert event.trigger_reason == "WIN_RATE_COLLAPSE"
    assert active_model.status == "rolled_back"


def test_rolling_sharpe_drop_triggers_rollback() -> None:
    """Test that rolling Sharpe dropping across consecutive windows triggers rollback."""
    config = RollbackMonitorConfig(
        window_size=10,
        consecutive_degraded_windows=2,
        min_rolling_win_rate=0.0,  # disable win rate trigger to isolate Sharpe
        max_drawdown_limit_pct=50.0,
        max_consecutive_losses=20,
    )
    monitor = RollbackMonitor(config=config)
    # Model expected Sharpe = 2.5
    active_model = _make_model("active_v2", sharpe=2.5)
    fallback_model = _make_model("fallback_v1")

    # Inject trades with alternating tiny wins and losses that produce negative or near-zero Sharpe
    event = None
    for i in range(12):
        pnl = Decimal("5.00") if i % 2 == 0 else Decimal("-6.00")
        event = monitor.process_completed_trade(
            _make_trade(pnl),
            active_model=active_model,
            fallback_model=fallback_model,
        )
        if event is not None:
            break

    assert event is not None
    assert event.trigger_reason == "ROLLING_SHARPE_DROP"
    assert active_model.status == "rolled_back"


def test_repeated_rollbacks_halt_candidate_promotions() -> None:
    """Test that 2 rollbacks within 90 days set promotion_halted=True."""
    config = RollbackMonitorConfig(
        max_rollbacks_per_90_days=2,
        max_drawdown_limit_pct=5.0,
    )
    monitor = RollbackMonitor(config=config)
    active_m1 = _make_model("active_m1")
    fallback = _make_model("fallback")

    # Rollback 1
    monitor.process_completed_trade(
        _make_trade(Decimal("-600.00")),
        active_model=active_m1,
        fallback_model=fallback,
    )
    assert monitor.promotion_halted is False

    # Reset for model 2
    monitor.reset_for_new_promotion()
    active_m2 = _make_model("active_m2")

    # Rollback 2
    monitor.process_completed_trade(
        _make_trade(Decimal("-600.00")),
        active_model=active_m2,
        fallback_model=fallback,
    )

    assert monitor.promotion_halted is True


def test_rollback_without_fallback_model() -> None:
    """Test rollback behavior when no fallback model exists."""
    config = RollbackMonitorConfig(max_drawdown_limit_pct=5.0)
    monitor = RollbackMonitor(config=config)
    active_m = _make_model("first_live_model")

    event = monitor.process_completed_trade(
        _make_trade(Decimal("-600.00")),
        active_model=active_m,
        fallback_model=None,
    )

    assert event is not None
    assert event.restored_model_id == "SAFE_BASELINE_FALLBACK"
    assert active_m.status == "rolled_back"


def test_calculate_rolling_sharpe_edge_cases() -> None:
    """Test static Sharpe helper with edge cases."""
    # 0 or 1 trade
    assert RollbackMonitor._calculate_rolling_sharpe([]) == 0.0
    single_trade = [_make_trade(Decimal("10.00"))]
    assert RollbackMonitor._calculate_rolling_sharpe(single_trade) == 0.0

    # Zero variance (all trades equal positive PnL)
    two_equal_trades = [
        _make_trade(Decimal("50.00")),
        _make_trade(Decimal("50.00")),
    ]
    assert RollbackMonitor._calculate_rolling_sharpe(two_equal_trades) == 3.0

    # Zero variance (all trades equal negative PnL)
    two_neg_trades = [
        _make_trade(Decimal("-50.00")),
        _make_trade(Decimal("-50.00")),
    ]
    assert RollbackMonitor._calculate_rolling_sharpe(two_neg_trades) == 0.0
