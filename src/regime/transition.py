"""Market regime transition detection and hysteresis filtering engine.

Implements stateful 2-cycle hysteresis filtering across 5 canonical dimensions
per MLD §5.2, ADD §5, and FRD-REGIME-2 to suppress boundary oscillation noise.
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.config.models import RegimeConfig
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    RegimeTransitionEvent,
    RiskSentiment,
    TrendState,
    VolatilityLevel,
)

logger = structlog.get_logger("regime.transition")


@dataclass
class _DimensionCandidate:
    """Internal candidate tracker for a proposed dimension change pending confirmation."""

    value: Any = None
    count: int = 0


@dataclass
class _StreamState:
    """Internal state maintained per (instrument, timeframe) market data stream."""

    confirmed_classification: RegimeClassification
    candidates: dict[str, _DimensionCandidate] = field(default_factory=dict)
    last_transition_event: RegimeTransitionEvent | None = None


class RegimeTransitionFilter:
    """Stateful hysteresis filter and transition detector for market regimes (MLD §5.2).

    Enforces a minimum consecutive cycle requirement (default: 2 cycles) before
    confirming regime transitions across canonical dimensions, suppressing false
    positive state flips caused by noisy threshold boundary oscillations.
    """

    def __init__(
        self,
        config: RegimeConfig | None = None,
        hysteresis_cycles: int | None = None,
    ) -> None:
        """Initialize transition filter with configuration parameters.

        Args:
            config: RegimeConfig instance or defaults.
            hysteresis_cycles: Optional explicit cycle override (must be >= 1).

        Raises:
            ValueError: If hysteresis_cycles is less than 1.
        """
        self.config = config or RegimeConfig()
        if hysteresis_cycles is not None:
            if hysteresis_cycles < 1:
                msg = "hysteresis_cycles must be >= 1"
                raise ValueError(msg)
            self.hysteresis_cycles = hysteresis_cycles
        else:
            self.hysteresis_cycles = self.config.hysteresis_cycles

        self._streams: dict[tuple[str, str], _StreamState] = {}
        self._events: dict[tuple[str, str], list[RegimeTransitionEvent]] = {}
        self._logger = logger.bind(component="RegimeTransitionFilter")

    def filter(self, raw: RegimeClassification) -> RegimeClassification:
        """Process a raw point-in-time classification through hysteresis filtering.

        Args:
            raw: Raw RegimeClassification output from RegimeDetector.

        Returns:
            RegimeClassification reflecting confirmed states, with is_transition
            flagged True and previous_regime populated only on confirmation cycles.
        """
        key = (raw.instrument, raw.timeframe)
        if key not in self._streams:
            return self._init_stream(key, raw)

        stream = self._streams[key]
        next_dims, transitioned_dims = self._evaluate_dimensions(stream, raw)

        if transitioned_dims:
            return self._handle_transition(key, stream, raw, next_dims, transitioned_dims)
        return self._handle_steady_state(stream, raw)

    def _init_stream(self, key: tuple[str, str], raw: RegimeClassification) -> RegimeClassification:
        """Initialize baseline state on first observation of a stream."""
        candidates = {
            "trend_state": _DimensionCandidate(),
            "volatility_level": _DimensionCandidate(),
            "directional_bias": _DimensionCandidate(),
            "liquidity_condition": _DimensionCandidate(),
            "risk_sentiment": _DimensionCandidate(),
        }
        baseline = RegimeClassification(
            classification_id=raw.classification_id,
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            timestamp=raw.timestamp,
            trend_state=raw.trend_state,
            volatility_level=raw.volatility_level,
            directional_bias=raw.directional_bias,
            liquidity_condition=raw.liquidity_condition,
            risk_sentiment=raw.risk_sentiment,
            regime_label=raw.regime_label,
            is_transition=False,
            previous_regime=None,
            metrics=raw.metrics,
            feature_set_id=raw.feature_set_id,
        )
        self._streams[key] = _StreamState(
            confirmed_classification=baseline,
            candidates=candidates,
        )
        self._logger.debug(
            "regime_stream_initialized",
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            regime=raw.regime_label,
        )
        return baseline

    def _process_dimension(
        self,
        cand: _DimensionCandidate,
        raw_val: Any,
        confirmed_val: Any,
    ) -> tuple[Any, bool]:
        """Apply hysteresis logic to a single regime dimension."""
        if raw_val == confirmed_val:
            cand.value = None
            cand.count = 0
            return confirmed_val, False

        if cand.value == raw_val:
            cand.count += 1
        else:
            cand.value = raw_val
            cand.count = 1

        if cand.count >= self.hysteresis_cycles:
            cand.value = None
            cand.count = 0
            return raw_val, True

        return confirmed_val, False

    def _evaluate_dimensions(
        self, stream: _StreamState, raw: RegimeClassification
    ) -> tuple[dict[str, Any], list[str]]:
        """Evaluate hysteresis and MLD §5.1 invariants across all dimensions."""
        confirmed = stream.confirmed_classification
        transitioned_dims: list[str] = []
        next_dims: dict[str, Any] = {}

        dim_names = (
            "trend_state",
            "volatility_level",
            "directional_bias",
            "liquidity_condition",
            "risk_sentiment",
        )

        for dim in dim_names:
            val, transitioned = self._process_dimension(
                stream.candidates[dim],
                getattr(raw, dim),
                getattr(confirmed, dim),
            )
            next_dims[dim] = val
            if transitioned:
                transitioned_dims.append(dim)

        # Enforce non-negotiable MLD §5.1 invariant: DirectionalBias.NEUTRAL when RANGING
        if (
            next_dims["trend_state"] == TrendState.RANGING
            and next_dims["directional_bias"] != DirectionalBias.NEUTRAL
        ):
            next_dims["directional_bias"] = DirectionalBias.NEUTRAL
            if (
                "directional_bias" not in transitioned_dims
                and confirmed.directional_bias != DirectionalBias.NEUTRAL
            ):
                transitioned_dims.append("directional_bias")
            stream.candidates["directional_bias"].value = None
            stream.candidates["directional_bias"].count = 0

        return next_dims, transitioned_dims

    def _handle_transition(
        self,
        key: tuple[str, str],
        stream: _StreamState,
        raw: RegimeClassification,
        next_dims: dict[str, Any],
        transitioned_dims: list[str],
    ) -> RegimeClassification:
        """Construct transition classification and emit RegimeTransitionEvent."""
        confirmed = stream.confirmed_classification
        prev_label = confirmed.regime_label
        next_trend: TrendState = next_dims["trend_state"]
        next_vol: VolatilityLevel = next_dims["volatility_level"]
        next_bias: DirectionalBias = next_dims["directional_bias"]
        next_liq: LiquidityCondition = next_dims["liquidity_condition"]
        next_risk: RiskSentiment = next_dims["risk_sentiment"]

        new_label = f"{next_trend.value}_{next_vol.value}_{next_bias.value}_{next_liq.value}"

        filtered = RegimeClassification(
            classification_id=raw.classification_id,
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            timestamp=raw.timestamp,
            trend_state=next_trend,
            volatility_level=next_vol,
            directional_bias=next_bias,
            liquidity_condition=next_liq,
            risk_sentiment=next_risk,
            regime_label=new_label,
            is_transition=True,
            previous_regime=prev_label,
            metrics=raw.metrics,
            feature_set_id=raw.feature_set_id,
        )
        event = RegimeTransitionEvent(
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            timestamp=raw.timestamp,
            previous_regime=prev_label,
            current_regime=new_label,
            transitioned_dimensions=transitioned_dims,
            classification=filtered,
        )
        stream.last_transition_event = event
        if key not in self._events:
            self._events[key] = []
        self._events[key].append(event)
        stream.confirmed_classification = filtered

        self._logger.info(
            "regime_transition_confirmed",
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            previous_regime=prev_label,
            new_regime=new_label,
            transitioned_dimensions=transitioned_dims,
        )
        return filtered

    def _handle_steady_state(
        self, stream: _StreamState, raw: RegimeClassification
    ) -> RegimeClassification:
        """Output confirmed steady state with current timestamp and metrics."""
        confirmed = stream.confirmed_classification
        filtered = RegimeClassification(
            classification_id=raw.classification_id,
            instrument=raw.instrument,
            timeframe=raw.timeframe,
            timestamp=raw.timestamp,
            trend_state=confirmed.trend_state,
            volatility_level=confirmed.volatility_level,
            directional_bias=confirmed.directional_bias,
            liquidity_condition=confirmed.liquidity_condition,
            risk_sentiment=confirmed.risk_sentiment,
            regime_label=confirmed.regime_label,
            is_transition=False,
            previous_regime=None,
            metrics=raw.metrics,
            feature_set_id=raw.feature_set_id,
        )
        stream.confirmed_classification = filtered
        return filtered

    def get_confirmed_classification(
        self, instrument: str, timeframe: str
    ) -> RegimeClassification | None:
        """Get the current confirmed regime classification for a stream."""
        state = self._streams.get((instrument, timeframe))
        return state.confirmed_classification if state else None

    def get_last_transition_event(
        self, instrument: str, timeframe: str
    ) -> RegimeTransitionEvent | None:
        """Get the most recent confirmed transition event for a stream."""
        state = self._streams.get((instrument, timeframe))
        return state.last_transition_event if state else None

    def get_transition_events(
        self, instrument: str | None = None, timeframe: str | None = None
    ) -> list[RegimeTransitionEvent]:
        """Get list of confirmed transition events, optionally filtered by stream."""
        if instrument is not None and timeframe is not None:
            return list(self._events.get((instrument, timeframe), []))
        all_events: list[RegimeTransitionEvent] = []
        for events in self._events.values():
            all_events.extend(events)
        all_events.sort(key=lambda e: e.timestamp)
        return all_events

    def reset(self, instrument: str | None = None, timeframe: str | None = None) -> None:
        """Reset transition filter state for a stream or globally across all streams."""
        if instrument is not None and timeframe is not None:
            self._streams.pop((instrument, timeframe), None)
            self._events.pop((instrument, timeframe), None)
        else:
            self._streams.clear()
            self._events.clear()
