"""Unit tests for statistical pattern extraction and variance attribution engine.

Conforms to FRD-LEARN-2, SLD §5.2, §10, and MLD §8.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from src.domain.decision import DecisionRecord
from src.domain.evaluation import TradeEvaluation
from src.domain.pattern import ObservedPattern
from src.research.pattern_detector import (
    PatternExtractionConfig,
    PatternExtractionEngine,
)


def _make_dummy_decision(
    *,
    decision_id: Any = None,
    regime: str = "LOW_VOLATILITY",
    primary_agent: str = "trend_agent",
    disagreement: float = 0.1,
) -> DecisionRecord:
    """Create a valid mock DecisionRecord."""
    now = datetime.now(UTC)
    agent_scores = {
        "trend_agent": 0.2,
        "mean_reversion_agent": 0.2,
        "momentum_agent": 0.2,
        "price_action_agent": 0.2,
    }
    agent_scores[primary_agent] = 0.9

    return DecisionRecord(
        decision_record_id=decision_id or uuid4(),
        timestamp=now,
        instrument="NSE:NIFTY50",
        decision="BUY",
        regime=regime,
        agent_scores=agent_scores,
        aggregated_score=0.85,
        risk_result={"approved": True},
        approved_quantity=10,
        disagreement_metric=disagreement,
    )


def _make_dummy_trade(
    *,
    entry_dec_id: Any,
    net_pnl: float,
    variance_driver: str = "good_trade",
) -> TradeEvaluation:
    """Create a valid mock TradeEvaluation."""
    now = datetime.now(UTC)
    pnl_dec = Decimal(str(round(net_pnl, 2)))
    return TradeEvaluation(
        trade_id=uuid4(),
        entry_decision_id=entry_dec_id,
        exit_decision_id=uuid4(),
        instrument="NSE:NIFTY50",
        direction="BUY",
        entry_price=Decimal("100.0"),
        exit_price=Decimal("105.0") if net_pnl > 0 else Decimal("95.0"),
        quantity=10,
        gross_pnl=pnl_dec,
        net_pnl=pnl_dec,
        variance_driver=variance_driver,  # type: ignore[arg-type]
        evaluated_at=now,
    )


class TestObservedPatternDomain:
    """Domain model invariant tests for ObservedPattern."""

    def test_valid_pattern_construction(self) -> None:
        pattern = ObservedPattern(
            pattern_type="REGIME_FAILURE",
            target_dimension="regime",
            target_value="HIGH_VOLATILITY",
            sample_size=35,
            total_trades_analyzed=100,
            failure_count=25,
            win_rate=0.285,
            baseline_win_rate=0.60,
            mean_pnl=Decimal("-150.0"),
            baseline_mean_pnl=Decimal("120.0"),
            p_value=0.001,
            confidence=0.999,
            is_statistically_significant=True,
            status="CONFIRMED_HYPOTHESIS",
            description="High volatility underperformance cluster",
        )
        assert pattern.is_statistically_significant
        assert pattern.status == "CONFIRMED_HYPOTHESIS"
        assert pattern.detected_at.tzinfo is not None

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            ObservedPattern(
                pattern_type="REGIME_FAILURE",
                target_dimension="regime",
                target_value="HIGH_VOLATILITY",
                sample_size=35,
                total_trades_analyzed=100,
                failure_count=25,
                win_rate=0.285,
                baseline_win_rate=0.60,
                mean_pnl=Decimal("-150.0"),
                baseline_mean_pnl=Decimal("120.0"),
                p_value=0.001,
                confidence=0.999,
                is_statistically_significant=True,
                status="CONFIRMED_HYPOTHESIS",
                description="High volatility underperformance cluster",
                detected_at=datetime(2026, 9, 6, 12, 0, 0),  # Naive
            )


class TestPatternExtractionEngine:
    """Statistical pattern extraction and noise filtering unit tests."""

    @pytest.fixture
    def engine(self) -> PatternExtractionEngine:
        return PatternExtractionEngine(
            config=PatternExtractionConfig(
                min_sample_size=30,
                significance_level=0.05,
                min_batch_size=30,
                underperformance_margin=0.05,
            )
        )

    def test_hypothesis_starvation_below_min_batch_size(
        self, engine: PatternExtractionEngine
    ) -> None:
        """Verify engine outputs empty list on insufficient trade volume (SLD §9)."""
        dec = _make_dummy_decision()
        trades = [
            _make_dummy_trade(entry_dec_id=dec.decision_record_id, net_pnl=-50.0) for _ in range(15)
        ]
        patterns = engine.extract_patterns(trades=trades, decisions=[dec])
        assert patterns == []

    def test_statistically_significant_regime_failure(
        self, engine: PatternExtractionEngine
    ) -> None:
        """Verify detection of confirmed failure cluster (N >= 30, p <= 0.05)."""
        dec_normal = _make_dummy_decision(regime="NORMAL_VOLATILITY")
        dec_shock = _make_dummy_decision(regime="EXTREME_VOLATILITY")

        trades: list[TradeEvaluation] = []
        # 60 normal trades: 75% win rate
        for i in range(60):
            pnl = 100.0 if i < 45 else -50.0
            trades.append(
                _make_dummy_trade(entry_dec_id=dec_normal.decision_record_id, net_pnl=pnl)
            )

        # 40 shock trades: 20% win rate (injected severe underperformance)
        for i in range(40):
            pnl = 100.0 if i < 8 else -150.0
            trades.append(_make_dummy_trade(entry_dec_id=dec_shock.decision_record_id, net_pnl=pnl))

        decisions = [dec_normal, dec_shock]
        patterns = engine.extract_patterns(trades=trades, decisions=decisions)

        assert len(patterns) >= 1
        regime_pat = next((p for p in patterns if p.target_value == "EXTREME_VOLATILITY"), None)
        assert regime_pat is not None
        assert regime_pat.status == "CONFIRMED_HYPOTHESIS"
        assert regime_pat.is_statistically_significant
        assert regime_pat.sample_size == 40
        assert regime_pat.win_rate == pytest.approx(0.20)
        assert regime_pat.p_value < 0.01

    def test_insignificant_small_sample_is_unconfirmed(
        self, engine: PatternExtractionEngine
    ) -> None:
        """Verify sub-30 sample underperformance is surfaced as OBSERVED_UNCONFIRMED."""
        dec_base = _make_dummy_decision(regime="NORMAL_VOLATILITY")
        dec_small = _make_dummy_decision(primary_agent="experimental_agent")

        trades: list[TradeEvaluation] = []
        # 70 baseline trades: 70% win rate
        for i in range(70):
            pnl = 50.0 if i < 49 else -30.0
            trades.append(_make_dummy_trade(entry_dec_id=dec_base.decision_record_id, net_pnl=pnl))

        # 10 experimental agent trades: 10% win rate (N=10 < 30)
        for i in range(10):
            pnl = 50.0 if i < 1 else -40.0
            trades.append(_make_dummy_trade(entry_dec_id=dec_small.decision_record_id, net_pnl=pnl))

        decisions = [dec_base, dec_small]
        patterns = engine.extract_patterns(trades=trades, decisions=decisions)

        agent_pat = next((p for p in patterns if p.target_value == "experimental_agent"), None)
        assert agent_pat is not None
        assert agent_pat.status == "OBSERVED_UNCONFIRMED"
        assert not agent_pat.is_statistically_significant
        assert agent_pat.sample_size == 10

    def test_variance_driver_cluster(self, engine: PatternExtractionEngine) -> None:
        """Verify clustering of specific variance drivers (e.g. bad_timing)."""
        dec = _make_dummy_decision()
        trades: list[TradeEvaluation] = []

        # 40 baseline trades
        for _ in range(40):
            trades.append(
                _make_dummy_trade(
                    entry_dec_id=dec.decision_record_id,
                    net_pnl=100.0,
                    variance_driver="good_trade",
                )
            )

        # 35 bad timing failure trades
        for _ in range(35):
            trades.append(
                _make_dummy_trade(
                    entry_dec_id=dec.decision_record_id,
                    net_pnl=-80.0,
                    variance_driver="bad_timing",
                )
            )

        patterns = engine.extract_patterns(trades=trades, decisions=[dec])
        timing_pat = next((p for p in patterns if p.target_value == "bad_timing"), None)
        assert timing_pat is not None
        assert timing_pat.status == "CONFIRMED_HYPOTHESIS"
        assert timing_pat.win_rate == 0.0

    def test_disagreement_failure_cluster(self, engine: PatternExtractionEngine) -> None:
        """Verify detection of high disagreement failure clusters."""
        dec_agree = _make_dummy_decision(disagreement=0.1)
        dec_disagree = _make_dummy_decision(disagreement=0.8)

        trades: list[TradeEvaluation] = []
        # 50 agreed trades: 80% win rate
        for i in range(50):
            pnl = 100.0 if i < 40 else -50.0
            trades.append(_make_dummy_trade(entry_dec_id=dec_agree.decision_record_id, net_pnl=pnl))

        # 35 high disagreement trades: 20% win rate
        for i in range(35):
            pnl = 100.0 if i < 7 else -120.0
            trades.append(
                _make_dummy_trade(entry_dec_id=dec_disagree.decision_record_id, net_pnl=pnl)
            )

        patterns = engine.extract_patterns(trades=trades, decisions=[dec_agree, dec_disagree])
        disagree_pat = next((p for p in patterns if p.target_value == "HIGH_DISAGREEMENT"), None)
        assert disagree_pat is not None
        assert disagree_pat.status == "CONFIRMED_HYPOTHESIS"
        assert disagree_pat.win_rate == pytest.approx(0.20)

    def test_clean_market_no_underperformance(self, engine: PatternExtractionEngine) -> None:
        """Verify zero patterns surfaced when all trades are uniformly profitable."""
        dec = _make_dummy_decision()
        trades = [
            _make_dummy_trade(entry_dec_id=dec.decision_record_id, net_pnl=100.0) for _ in range(50)
        ]
        patterns = engine.extract_patterns(trades=trades, decisions=[dec])
        assert len(patterns) == 0
