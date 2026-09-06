"""Unit tests for CapitalManager and operator scaling authorization (Sprint S24.02).

Adheres strictly to BRD BR-2 (no silent capital scaling), FRD-CAP-1,
FRD-CAP-3, FRD-CAP-4, and RTLD §15.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.capital.manager import (
    CapitalManager,
    IneligibleScalingError,
    ScalingCapExceededError,
    UnauthorizedScalingError,
    WithdrawalError,
)
from src.capital.scaling_evaluator import CapitalScalingEvaluator, ScalingEvaluationInput
from src.domain.capital_event import CapitalEventType

if TYPE_CHECKING:
    from src.domain.scaling_report import CapitalScalingReport


@pytest.fixture
def valid_operator_token() -> str:
    """Fixture providing standard operator authorization token."""
    return "secure-operator-auth-token-12345"


@pytest.fixture
def eligible_scaling_report() -> CapitalScalingReport:
    """Fixture providing a valid report passing all 9 RTLD §15 criteria."""
    evaluator = CapitalScalingEvaluator()
    metrics = ScalingEvaluationInput(
        current_capital=Decimal("10000.00"),
        live_days=100,
        closed_trade_count=50,
        regime_expectancies={
            "BULL_TRENDING": Decimal("200.00"),
            "LOW_VOLATILITY": Decimal("80.00"),
        },
        max_historical_drawdown_pct=3.5,
        sortino_ratio=1.8,
        validation_passed=True,
        live_paper_divergence_pct=8.0,
        automated_rollback_count=0,
        avg_slippage_multiplier=1.1,
        duplicate_order_count=0,
        system_uptime_pct=99.9,
        unhandled_disconnect_count=0,
    )
    return evaluator.evaluate(metrics)


@pytest.fixture
def ineligible_scaling_report() -> CapitalScalingReport:
    """Fixture providing a report failing criteria."""
    evaluator = CapitalScalingEvaluator()
    metrics = ScalingEvaluationInput(
        current_capital=Decimal("10000.00"),
        live_days=40,  # Fails Criterion 1 (< 90 days)
        closed_trade_count=15,  # Fails Criterion 1 (< 30 trades)
        regime_expectancies={"BULL_TRENDING": Decimal("50.00")},
        max_historical_drawdown_pct=8.5,  # Fails Criterion 3 (>= 8.0%)
        sortino_ratio=0.7,
        validation_passed=False,
        live_paper_divergence_pct=25.0,
        automated_rollback_count=1,
        avg_slippage_multiplier=1.8,
        duplicate_order_count=1,
        system_uptime_pct=98.0,
        unhandled_disconnect_count=3,
    )
    return evaluator.evaluate(metrics)


def test_capital_manager_initial_state(valid_operator_token: str) -> None:
    """Verify default initial capital is ₹10,000 and initial history is empty."""
    mgr = CapitalManager(operator_token=valid_operator_token)
    assert mgr.current_capital == Decimal("10000.00")
    assert mgr.retained_profits == Decimal("0.00")
    assert mgr.cumulative_withdrawn == Decimal("0.00")

    state = mgr.get_capital_state()
    assert state.current_capital == Decimal("10000.00")
    assert state.peak_equity == Decimal("10000.00")
    assert len(mgr.get_history()) == 0


def test_scaling_authorization_nominal_with_profit_withdrawal(
    valid_operator_token: str, eligible_scaling_report: CapitalScalingReport
) -> None:
    """Verify operator-authorized +25% scaling with mandatory 50% profit withdrawal."""
    mgr = CapitalManager(initial_capital=Decimal("10000.00"), operator_token=valid_operator_token)

    # Accumulate ₹4,000 in realized trading profits
    mgr.record_profit(Decimal("4000.00"))
    assert mgr.retained_profits == Decimal("4000.00")

    # Authorize scaling
    event = mgr.request_scaling_authorization(
        report=eligible_scaling_report,
        operator_token=valid_operator_token,
    )

    # 1. Capital increases strictly by +25%: ₹10,000 -> ₹12,500
    assert mgr.current_capital == Decimal("12500.00")
    assert event.previous_capital == Decimal("10000.00")
    assert event.new_capital == Decimal("12500.00")
    assert event.event_type == CapitalEventType.SCALING_INCREASE

    # 2. 50% profit withdrawal mandate applied: ₹4,000 * 50% = ₹2,000
    assert event.withdrawn_amount == Decimal("2000.00")
    assert mgr.retained_profits == Decimal("2000.00")
    assert mgr.cumulative_withdrawn == Decimal("2000.00")

    # 3. Audit trail captures token hash and report ID
    assert len(event.operator_token_hash) == 64
    assert event.scaling_report_id == eligible_scaling_report.report_id
    assert len(mgr.get_history()) == 1


def test_scaling_authorization_rejected_unauthorized_token(
    valid_operator_token: str, eligible_scaling_report: CapitalScalingReport
) -> None:
    """Verify scaling is blocked when operator token is invalid."""
    mgr = CapitalManager(operator_token=valid_operator_token)

    with pytest.raises(UnauthorizedScalingError, match="Invalid or missing operator"):
        mgr.request_scaling_authorization(
            report=eligible_scaling_report,
            operator_token="wrong-token-xyz",
        )

    # Capital remains untouched
    assert mgr.current_capital == Decimal("10000.00")
    assert len(mgr.get_history()) == 0


def test_scaling_authorization_rejected_ineligible_report(
    valid_operator_token: str, ineligible_scaling_report: CapitalScalingReport
) -> None:
    """Verify scaling is blocked when report shows system is ineligible."""
    mgr = CapitalManager(operator_token=valid_operator_token)

    with pytest.raises(IneligibleScalingError, match=r"Cannot scale capital: report.*INELIGIBLE"):
        mgr.request_scaling_authorization(
            report=ineligible_scaling_report,
            operator_token=valid_operator_token,
        )

    assert mgr.current_capital == Decimal("10000.00")
    assert len(mgr.get_history()) == 0


def test_scaling_authorization_rejected_exceeds_plus_25_pct_ceiling(
    valid_operator_token: str, eligible_scaling_report: CapitalScalingReport
) -> None:
    """Verify scaling is rejected if operator requests more than +25% step increase."""
    mgr = CapitalManager(initial_capital=Decimal("10000.00"), operator_token=valid_operator_token)

    # Max allowed is 10,000 * 1.25 = 12,500. Requesting 13,000 must fail.
    with pytest.raises(ScalingCapExceededError, match="exceeds strict \\+25% step ceiling"):
        mgr.request_scaling_authorization(
            report=eligible_scaling_report,
            operator_token=valid_operator_token,
            new_capital=Decimal("13000.00"),
        )

    # Requesting less than or equal to current capital must also fail
    with pytest.raises(ScalingCapExceededError, match="must be greater than current capital"):
        mgr.request_scaling_authorization(
            report=eligible_scaling_report,
            operator_token=valid_operator_token,
            new_capital=Decimal("10000.00"),
        )


def test_profit_withdrawal_lifecycle(valid_operator_token: str) -> None:
    """Verify profit withdrawal execution, balance reduction, and overdraft blocking."""
    mgr = CapitalManager(initial_capital=Decimal("10000.00"), operator_token=valid_operator_token)

    # Accumulate ₹5,000 profit
    mgr.record_profit(Decimal("5000.00"))
    assert mgr.retained_profits == Decimal("5000.00")

    # Withdraw ₹3,000
    w_event = mgr.record_withdrawal(
        amount=Decimal("3000.00"),
        operator_token=valid_operator_token,
        justification="Quarterly profit lock-in",
    )
    assert w_event.event_type == CapitalEventType.PROFIT_WITHDRAWAL
    assert w_event.withdrawn_amount == Decimal("3000.00")
    assert mgr.retained_profits == Decimal("2000.00")
    assert mgr.cumulative_withdrawn == Decimal("3000.00")

    # Overdraft attempt (> remaining ₹2,000) raises WithdrawalError
    with pytest.raises(WithdrawalError, match="exceeds available retained profits"):
        mgr.record_withdrawal(
            amount=Decimal("2500.00"),
            operator_token=valid_operator_token,
        )

    # Zero or negative withdrawal raises WithdrawalError
    with pytest.raises(WithdrawalError, match="must be positive"):
        mgr.record_withdrawal(
            amount=Decimal("0.00"),
            operator_token=valid_operator_token,
        )


def test_record_profit_and_loss_absorption(valid_operator_token: str) -> None:
    """Verify profit and loss absorption dynamics on retained earnings and base capital."""
    mgr = CapitalManager(initial_capital=Decimal("10000.00"), operator_token=valid_operator_token)

    # Gain ₹2,000
    mgr.record_profit(Decimal("2000.00"))
    assert mgr.retained_profits == Decimal("2000.00")

    # Loss ₹1,500 absorbed by retained profits
    mgr.record_profit(Decimal("-1500.00"))
    assert mgr.retained_profits == Decimal("500.00")
    assert mgr.current_capital == Decimal("10000.00")

    # Loss ₹1,500 exhausts retained profits and draws down capital by ₹1,000
    mgr.record_profit(Decimal("-1500.00"))
    assert mgr.retained_profits == Decimal("0.00")
    assert mgr.current_capital == Decimal("9000.00")
