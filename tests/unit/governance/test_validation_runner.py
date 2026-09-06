"""Unit tests for multi-stage model validation pipeline runner.

Conforms to FRD-LEARN-3, FRD-LEARN-8, ADD §8.2, and MLD §9, §10:
- Validates 6-stage sequential execution
- Verifies fail-fast halting and candidate rejection
- Verifies candidate pass state when all 6 gates pass
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import pytest

from src.domain.evaluation import TradeEvaluation
from src.domain.governance import ModelVersion
from src.domain.market_data import OHLCVCandle
from src.governance.validation_runner import (
    ValidationRunner,
    ValidationRunnerConfig,
)


def _make_candidate(
    *,
    status: Literal[
        "candidate",
        "promoted",
        "rolled_back",
        "rejected",
        "superseded",
    ] = "candidate",
    metrics: dict[str, Any] | None = None,
) -> ModelVersion:
    """Create a candidate ModelVersion for testing."""
    default_metrics = {
        "sharpe_ratio": 1.8,
        "max_drawdown": 0.08,
        "oos_sharpe_ratio": 1.4,
        "oos_max_drawdown": 0.09,
        "walk_forward_efficiency": 0.65,
        "stress_max_drawdown": 0.12,
        "stress_kill_switch_triggered": False,
        "robustness_degradation": 0.05,
        "paper_trades_count": 35,
        "paper_win_rate": 0.60,
    }
    if metrics:
        default_metrics.update(metrics)

    return ModelVersion(
        model_id="test_model_v2",
        model_name="MomentumPredictor",
        version_tag="v2.0.0",
        model_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        trained_at=datetime.now(UTC),
        status=status,
        validation_metrics=default_metrics,
    )


def _make_dummy_candles(count: int = 100, step: float = 1.0) -> list[OHLCVCandle]:
    """Create a synthetic sequence of OHLCV candles."""
    now = datetime.now(UTC)
    candles = []
    base_price = 1000.0
    for i in range(count):
        price = base_price + (i * step)
        candles.append(
            OHLCVCandle(
                instrument="NSE:RELIANCE",
                timestamp=now - timedelta(minutes=(count - i) * 5),
                open=Decimal(str(price)),
                high=Decimal(str(price + 2.0)),
                low=Decimal(str(price - 2.0)),
                close=Decimal(str(price + 0.5)),
                volume=10000,
                turnover=Decimal("1000000.00"),
                timeframe="5m",
                quality_state="VALIDATED",
            )
        )
    return candles


def _make_paper_trades(count: int = 35, win_count: int = 20) -> list[TradeEvaluation]:
    """Create a list of evaluated paper trades."""
    trades = []
    now = datetime.now(UTC)
    for i in range(count):
        is_win = i < win_count
        pnl = Decimal("150.00") if is_win else Decimal("-75.00")
        trades.append(
            TradeEvaluation(
                trade_id=uuid4(),
                entry_decision_id=uuid4(),
                exit_decision_id=uuid4(),
                instrument="NSE:RELIANCE",
                direction="BUY",
                entry_price=Decimal("2500.00"),
                exit_price=Decimal("2510.00") if is_win else Decimal("2490.00"),
                quantity=10,
                gross_pnl=pnl + Decimal("10.00"),
                net_pnl=pnl,
                total_slippage=Decimal("5.00"),
                statutory_costs=Decimal("5.00"),
                variance_driver="good_trade" if is_win else "bad_timing",
                rule_adherence=True,
                entry_timestamp=now - timedelta(hours=count - i),
                exit_timestamp=now - timedelta(hours=count - i - 1),
                evaluated_at=now,
            )
        )
    return trades


def test_all_stages_pass_promotes_candidate() -> None:
    """Test standard happy path: all 6 validation stages pass successfully."""
    runner = ValidationRunner()
    candidate = _make_candidate()

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is True
    assert record.halted_stage_index is None
    assert record.rejection_reason is None
    assert len(record.stages) == 6
    assert all(s.passed for s in record.stages)
    assert candidate.status == "candidate"


def test_stage_1_backtest_fails_sharpe_low() -> None:
    """Test Stage 1 failure when backtest Sharpe ratio is below threshold."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"sharpe_ratio": 0.85})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 1
    assert "Historical backtest failed: Sharpe=0.85" in (record.rejection_reason or "")
    assert len(record.stages) == 1
    assert candidate.status == "rejected"


def test_stage_1_backtest_fails_drawdown_high() -> None:
    """Test Stage 1 failure when backtest max drawdown exceeds 15%."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"max_drawdown": 0.18})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 1
    assert "MaxDD=18.00%" in (record.rejection_reason or "")
    assert len(record.stages) == 1
    assert candidate.status == "rejected"


def test_stage_1_backtest_with_provided_candles() -> None:
    """Test Stage 1 calculation using explicit historical candle sequence."""
    runner = ValidationRunner()
    candles = _make_dummy_candles(count=50, step=2.0)
    candidate = _make_candidate()

    record = runner.run_validation(candidate=candidate, historical_candles=candles)

    assert len(record.stages) >= 1
    assert record.stages[0].stage_name == "HISTORICAL_BACKTEST"
    assert record.stages[0].metrics["candle_count"] == 50


def test_stage_2_oos_fails_sharpe_low() -> None:
    """Test Stage 2 OOS failure when OOS Sharpe ratio is below threshold."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"oos_sharpe_ratio": 0.65})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 2
    assert "Out-of-sample testing failed: OOS Sharpe=0.65" in (record.rejection_reason or "")
    assert len(record.stages) == 2
    assert record.stages[0].passed is True
    assert record.stages[1].passed is False
    assert candidate.status == "rejected"


def test_stage_2_oos_fails_drawdown_high() -> None:
    """Test Stage 2 OOS failure when OOS drawdown exceeds threshold."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"oos_max_drawdown": 0.22})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 2
    assert "OOS MaxDD=22.00%" in (record.rejection_reason or "")
    assert candidate.status == "rejected"


def test_stage_2_oos_with_candles_slicing() -> None:
    """Test Stage 2 when candles are chronologically sliced 70/30."""
    runner = ValidationRunner()
    candles = _make_dummy_candles(count=100, step=1.0)
    candidate = _make_candidate()

    record = runner.run_validation(candidate=candidate, historical_candles=candles)

    assert len(record.stages) >= 2
    assert record.stages[1].stage_name == "OUT_OF_SAMPLE"
    assert record.stages[1].metrics["candle_count"] == 30


def test_stage_3_walk_forward_fails_wfer_low() -> None:
    """Test Stage 3 Walk-Forward failure when WFER < 0.50."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"walk_forward_efficiency": 0.42})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 3
    assert "WFER=0.42 (min 0.50" in (record.rejection_reason or "")
    assert len(record.stages) == 3
    assert candidate.status == "rejected"


def test_stage_4_stress_test_fails_drawdown_high() -> None:
    """Test Stage 4 Stress Test failure when max stress drawdown exceeds 20%."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"stress_max_drawdown": 0.24})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 4
    assert "Stress testing failed: WorstDD=24.00%" in (record.rejection_reason or "")
    assert len(record.stages) == 4
    assert candidate.status == "rejected"


def test_stage_4_stress_test_fails_kill_switch_triggered() -> None:
    """Test Stage 4 Stress Test failure when simulated kill switch triggers."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"stress_kill_switch_triggered": True})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 4
    assert "kill_switch_breached=True" in (record.rejection_reason or "")
    assert candidate.status == "rejected"


def test_stage_5_robustness_perturbation_fails_high_degradation() -> None:
    """Test Stage 5 Robustness failure when parameter perturbation causes >25% drop."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"robustness_degradation": 0.32})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 5
    assert "Robustness parameter perturbation (+/-10%) failed: degradation=32.00%" in (
        record.rejection_reason or ""
    )
    assert len(record.stages) == 5
    assert candidate.status == "rejected"


def test_stage_6_paper_trading_fails_insufficient_trades() -> None:
    """Test Stage 6 Sandboxed Paper Trading failure when trades count < 30."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"paper_trades_count": 22, "paper_win_rate": 0.65})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 6
    assert "Sandboxed paper trading failed: trades=22 (min 30)" in (record.rejection_reason or "")
    assert len(record.stages) == 6
    assert candidate.status == "rejected"


def test_stage_6_paper_trading_fails_win_rate_low() -> None:
    """Test Stage 6 Sandboxed Paper Trading failure when win rate < 40%."""
    runner = ValidationRunner()
    candidate = _make_candidate(metrics={"paper_trades_count": 40, "paper_win_rate": 0.35})

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 6
    assert "win_rate=35.0% (min 40.0%)" in (record.rejection_reason or "")
    assert len(record.stages) == 6
    assert candidate.status == "rejected"


def test_stage_6_paper_trading_with_trade_evaluation_list() -> None:
    """Test Stage 6 using an explicit list of TradeEvaluation objects."""
    runner = ValidationRunner()
    candidate = _make_candidate()
    paper_trades = _make_paper_trades(count=35, win_count=21)  # 60% win rate

    record = runner.run_validation(candidate=candidate, paper_trades=paper_trades)

    assert record.overall_passed is True
    assert record.stages[5].metrics["trades_count"] == 35
    assert record.stages[5].metrics["win_rate"] == pytest.approx(0.60, abs=0.01)


def test_custom_config_thresholds() -> None:
    """Test runner with custom tighter thresholds."""
    config = ValidationRunnerConfig(
        min_backtest_sharpe=2.0,
        max_backtest_drawdown_pct=5.0,
        min_oos_sharpe=1.8,
        min_wfer=0.80,
        min_paper_trades=50,
    )
    runner = ValidationRunner(config=config)
    candidate = _make_candidate()  # has sharpe 1.8, so should fail stage 1

    record = runner.run_validation(candidate=candidate)

    assert record.overall_passed is False
    assert record.halted_stage_index == 1


def test_stage_metrics_override_feature() -> None:
    """Test overriding specific stage metrics during validation."""
    runner = ValidationRunner()
    candidate = _make_candidate()

    record = runner.run_validation(
        candidate=candidate,
        stage_metrics_override={
            "WALK_FORWARD": {"wfer": 0.35},
        },
    )

    assert record.overall_passed is False
    assert record.halted_stage_index == 3
    assert "WFER=0.35" in (record.rejection_reason or "")
