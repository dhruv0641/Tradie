"""Unit tests for TradingAgent protocol and BaseAgent fault-tolerant execution contract."""

from datetime import UTC, datetime
from uuid import uuid4
import pytest

from src.agents.base import BaseAgent, TradingAgent
from src.domain.agent_signal import SignalDirection
from src.domain.features import FeatureSet
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)


def _make_context() -> tuple[FeatureSet, RegimeClassification]:
    """Helper to construct minimal FeatureSet and RegimeClassification."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fs = FeatureSet(
        feature_set_id=uuid4(),
        instrument="NSE:NIFTY50",
        timestamp=now,
        timeframe="15m",
        features={"sma_20": 100.0},
    )
    regime = RegimeClassification(
        instrument="NSE:NIFTY50",
        timeframe="15m",
        timestamp=now,
        trend_state=TrendState.TRENDING_UP,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.BULLISH,
        liquidity_condition=LiquidityCondition.NORMAL,
        risk_sentiment=RiskSentiment.RISK_ON,
        regime_label="TRENDING_UP_NORMAL_BULLISH_NORMAL",
    )
    return fs, regime


class DummySuccessAgent(BaseAgent):
    """Test agent emitting valid LONG signal."""

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        return SignalDirection.LONG, 0.75, {"sma_20": 100.0}, 1.25


class DummyOverconfidentAgent(BaseAgent):
    """Test agent emitting unnormalized confidence > 1.0."""

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        return SignalDirection.LONG, 2.5, {"sma_20": 100.0}, 2.5


class DummyNegativeConfidenceAgent(BaseAgent):
    """Test agent emitting negative confidence."""

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        return SignalDirection.SHORT, -0.4, {}, -0.4


class DummyNoViewNonZeroAgent(BaseAgent):
    """Test agent emitting NO_VIEW with attempted non-zero confidence."""

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        return SignalDirection.NO_VIEW, 0.65, {}, None


class DummyFailingAgent(BaseAgent):
    """Test agent throwing unhandled exception during calculation."""

    def _compute_signal(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> tuple[SignalDirection, float, dict[str, float], float | None]:
        msg = "Unexpected divide by zero or missing feature key"
        raise KeyError(msg)


def test_trading_agent_protocol_conformance() -> None:
    """Verify BaseAgent instances satisfy runtime checkable TradingAgent protocol."""
    agent = DummySuccessAgent(agent_id="test_protocol")
    assert isinstance(agent, TradingAgent)
    assert agent.agent_id == "test_protocol"


def test_empty_agent_id_raises() -> None:
    """Verify empty or whitespace agent_id raises ValueError."""
    with pytest.raises(ValueError, match="non-empty string"):
        DummySuccessAgent(agent_id="")
    with pytest.raises(ValueError, match="non-empty string"):
        DummySuccessAgent(agent_id="   ")


def test_successful_evaluation() -> None:
    """Verify normal signal evaluation produces valid AgentSignalOutput."""
    agent = DummySuccessAgent(agent_id="agent_1")
    fs, regime = _make_context()

    sig = agent.evaluate("NSE:NIFTY50", "15m", fs, regime)

    assert sig.agent_id == "agent_1"
    assert sig.direction == SignalDirection.LONG
    assert sig.confidence == 0.75
    assert sig.inputs_used["sma_20"] == 100.0
    assert sig.raw_score == 1.25
    assert sig.timestamp == fs.timestamp


def test_confidence_clamping_upper_bound() -> None:
    """Verify confidence > 1.0 is clamped strictly to 1.0."""
    agent = DummyOverconfidentAgent(agent_id="agent_over")
    fs, regime = _make_context()

    sig = agent.evaluate("NSE:NIFTY50", "15m", fs, regime)

    assert sig.confidence == 1.0
    assert sig.direction == SignalDirection.LONG


def test_confidence_clamping_lower_bound() -> None:
    """Verify negative confidence is clamped strictly to 0.0."""
    agent = DummyNegativeConfidenceAgent(agent_id="agent_neg")
    fs, regime = _make_context()

    sig = agent.evaluate("NSE:NIFTY50", "15m", fs, regime)

    assert sig.confidence == 0.0
    assert sig.direction == SignalDirection.SHORT


def test_no_view_forces_zero_confidence() -> None:
    """Verify NO_VIEW direction forces confidence to 0.0 regardless of calculation."""
    agent = DummyNoViewNonZeroAgent(agent_id="agent_no_view")
    fs, regime = _make_context()

    sig = agent.evaluate("NSE:NIFTY50", "15m", fs, regime)

    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0


def test_fault_tolerant_exception_isolation() -> None:
    """Verify exceptions in agent logic are caught safely, returning NO_VIEW with 0.0 (FRD-SIG-3)."""
    agent = DummyFailingAgent(agent_id="failing_agent")
    fs, regime = _make_context()

    sig = agent.evaluate("NSE:NIFTY50", "15m", fs, regime)

    assert sig.agent_id == "failing_agent"
    assert sig.direction == SignalDirection.NO_VIEW
    assert sig.confidence == 0.0
    assert sig.inputs_used == {}
    assert sig.raw_score is None
    assert sig.timestamp == fs.timestamp
