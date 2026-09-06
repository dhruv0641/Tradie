"""Trading Brain autonomous market-hours runner and lifecycle orchestrator.

Adheres strictly to SOW §6.5 (V4), PRD §13, HLD §7, EDD §12, and TRD-COMPUTE-1.
"""

import signal
import threading
from collections import defaultdict, deque
from datetime import UTC, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.agents.base import TradingAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.momentum import MomentumAgent
from src.agents.price_action import PriceActionAgent
from src.agents.trend import TrendAgent
from src.aggregation.aggregator import SignalAggregator
from src.decision.supervisor import Supervisor
from src.domain.agent_signal import AgentSignalOutput, SignalDirection
from src.domain.aggregation_result import AggregationResult
from src.domain.decision import Decision, DecisionRecord
from src.domain.execution import OrderFill
from src.domain.market_data import OHLCVCandle
from src.domain.regime import RegimeClassification, VolatilityLevel
from src.domain.risk import CandidateTrade, MarketState
from src.execution.broker_adapter import BrokerAdapter
from src.execution.connection_monitor import ConnectionMonitor
from src.execution.idempotency import IdempotentOrderDispatcher, generate_client_order_id
from src.execution.order_manager import OrderManager
from src.execution.position_ledger import PositionLedger
from src.features.engine import FeatureEngine
from src.regime.detector import RegimeDetector
from src.regime.transition import RegimeTransitionFilter
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import InMemoryKillSwitch, KillSwitchProtocol
from src.risk.streak_tracker import StreakTracker

logger = structlog.get_logger("core.runner")

IST = ZoneInfo("Asia/Kolkata")


class MarketSessionPhase(StrEnum):
    """Trading session phases for Indian Equity Markets (NSE)."""

    INITIALIZING = "INITIALIZING"
    PRE_MARKET = "PRE_MARKET"
    REGULAR_HOURS = "REGULAR_HOURS"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"


class RunnerConfig(BaseModel):
    """Configuration for TradingBrainRunner execution parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enforce_market_hours: bool = Field(
        default=False,
        description="If True, enforce IST market hours; if False, allow processing anytime",
    )
    timeframe: str = Field(default="15m", description="Primary candle timeframe (e.g. '15m')")
    warmup_bars: int = Field(
        default=20, ge=1, description="Minimum candles required before trade generation"
    )
    cycle_interval_seconds: float = Field(
        default=1.0, ge=0.01, description="Continuous loop polling interval in seconds"
    )
    auto_cancel_eod: bool = Field(
        default=True, description="Cancel open working orders during post-market"
    )
    risk_reward_ratio: Decimal = Field(
        default=Decimal("2.0"), ge=Decimal("1.0"), description="Default Risk:Reward ratio"
    )
    default_stop_loss_pct: Decimal = Field(
        default=Decimal("0.01"), ge=Decimal("0.001"), description="Protective stop distance (1.0%)"
    )
    git_commit: str = Field(default="live", description="Active git commit hash for audit lineage")


class CycleResult(BaseModel):
    """Immutable audit outcome of a single evaluation cycle on a candle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str = Field(default_factory=lambda: f"CYC-{uuid4().hex[:12].upper()}")
    timestamp: datetime
    instrument: str
    candle: OHLCVCandle
    phase: MarketSessionPhase
    regime: RegimeClassification | None = None
    agent_signals: list[AgentSignalOutput] = Field(default_factory=list)
    aggregation: AggregationResult | None = None
    decision: Decision | None = None
    decision_record: DecisionRecord | None = None
    executed_fill: OrderFill | None = None
    equity: Decimal = Decimal("10000.00")
    cash: Decimal = Decimal("10000.00")
    reason: str | None = None


class SessionSummary(BaseModel):
    """End-of-day or end-of-simulation comprehensive performance summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(default_factory=lambda: f"SESS-{uuid4().hex[:12].upper()}")
    start_time: datetime
    end_time: datetime
    total_cycles: int = 0
    orders_placed: int = 0
    fills_executed: int = 0
    initial_capital: Decimal = Decimal("10000.00")
    final_equity: Decimal = Decimal("10000.00")
    realized_pnl: Decimal = Decimal("0.00")
    unrealized_pnl: Decimal = Decimal("0.00")
    net_pnl: Decimal = Decimal("0.00")
    total_costs: Decimal = Decimal("0.00")
    net_return_pct: float = 0.0
    open_positions_count: int = 0
    closed_trades_count: int = 0


class TradingBrainRunner:
    """Autonomous market-hours runner executing the full Trading Brain loop.

    Integrates:
    Feed / Buffer -> Features -> Regime -> Agents -> Aggregator ->
    Risk Engine -> Supervisor Decision Gate -> Order Dispatcher -> Broker.
    """

    def __init__(
        self,
        *,
        broker: BrokerAdapter,
        feature_engine: FeatureEngine | None = None,
        regime_detector: RegimeDetector | None = None,
        regime_filter: RegimeTransitionFilter | None = None,
        agents: list[TradingAgent] | None = None,
        aggregator: SignalAggregator | None = None,
        risk_engine: RiskEngine | None = None,
        kill_switch: KillSwitchProtocol | None = None,
        supervisor: Supervisor | None = None,
        order_dispatcher: IdempotentOrderDispatcher | None = None,
        order_manager: OrderManager | None = None,
        position_ledger: PositionLedger | None = None,
        streak_tracker: StreakTracker | None = None,
        connection_monitor: ConnectionMonitor | None = None,
        config: RunnerConfig | None = None,
        audit_service: Any | None = None,
        trade_evaluator: Any | None = None,
        reconciler: Any | None = None,
    ) -> None:
        self.config = config or RunnerConfig()
        self.broker = broker
        self.audit_service = audit_service
        self.trade_evaluator = trade_evaluator
        self.reconciler = reconciler
        self._evaluations: list[Any] = []

        self.feature_engine = feature_engine or FeatureEngine()
        self.regime_detector = regime_detector or RegimeDetector()
        self.regime_filter = regime_filter or RegimeTransitionFilter()

        self.agents: list[TradingAgent] = (
            agents
            if agents is not None
            else [
                TrendAgent("trend_v1"),
                MomentumAgent("mom_v1"),
                MeanReversionAgent("mr_v1"),
                PriceActionAgent("pa_v1"),
            ]
        )
        self.aggregator = aggregator or SignalAggregator()

        self.kill_switch = kill_switch or InMemoryKillSwitch()
        self.risk_engine = risk_engine or RiskEngine(RiskConfig(), self.kill_switch)
        self.supervisor = supervisor or Supervisor(self.risk_engine, self.kill_switch)

        self.order_dispatcher = order_dispatcher or IdempotentOrderDispatcher()
        self.order_manager = order_manager or OrderManager()
        self.position_ledger = position_ledger or PositionLedger()
        self.streak_tracker = streak_tracker or StreakTracker()
        self.connection_monitor = connection_monitor

        self._candle_buffers: dict[str, deque[OHLCVCandle]] = defaultdict(lambda: deque(maxlen=200))
        self._last_realized_pnl: dict[str, Decimal] = {}
        self._total_cycles = 0
        self._orders_placed = 0
        self._fills_executed = 0
        self._closed_trades_count = 0
        self._stop_event: threading.Event | None = None

        self._log = logger.bind(component="TradingBrainRunner")

    @property
    def total_cycles(self) -> int:
        """Total evaluation cycles processed."""
        return self._total_cycles

    @property
    def orders_placed(self) -> int:
        """Total orders dispatched to broker."""
        return self._orders_placed

    @property
    def fills_executed(self) -> int:
        """Total trade fills recorded."""
        return self._fills_executed

    @property
    def evaluations(self) -> list[Any]:
        """Total post-trade evaluations recorded."""
        return list(self._evaluations)

    def get_market_session_phase(self, dt: datetime) -> MarketSessionPhase:
        """Determine Indian Market session phase for a given timestamp in IST."""
        if not self.config.enforce_market_hours:
            return MarketSessionPhase.REGULAR_HOURS

        ist_dt = dt.astimezone(IST)
        if ist_dt.weekday() >= 5:
            return MarketSessionPhase.CLOSED

        t = ist_dt.time()
        if time(9, 0) <= t < time(9, 15):
            return MarketSessionPhase.PRE_MARKET
        if time(9, 15) <= t < time(15, 30):
            return MarketSessionPhase.REGULAR_HOURS
        if time(15, 30) <= t < time(16, 0):
            return MarketSessionPhase.POST_MARKET
        return MarketSessionPhase.CLOSED

    def pre_market_reconciliation(self, timestamp: datetime | None = None) -> None:
        """Perform pre-market connectivity and position reconciliation."""
        ts = timestamp or datetime.now(UTC)
        self._log.info("Executing pre-market reconciliation", timestamp=ts.isoformat())

        # 1. Broker connectivity check
        is_alive = (
            self.broker.heartbeat()
            if hasattr(self.broker, "heartbeat")
            else (self.broker.ping() if hasattr(self.broker, "ping") else True)
        )
        if not is_alive:
            self._log.warning("Broker heartbeat failed during pre-market reconciliation")

        # 2. Reconcile broker positions
        try:
            broker_positions = self.broker.get_positions()
            self._log.info(
                "Broker positions queried for pre-market reconciliation",
                count=len(broker_positions),
            )
        except Exception as e:
            self._log.error("Failed to query broker positions", error=str(e))

        # 3. Startup position & order reconciliation gate
        if self.reconciler is not None:
            rec_result = self.reconciler.reconcile()
            if not rec_result.reconciled:
                self._log.critical(
                    "Pre-market startup reconciliation mismatch; live trading suppressed",
                    discrepancies=len(rec_result.discrepancies),
                )

        # 4. Inform streak tracker of new session
        self.streak_tracker.on_session_start(ts.date())

    def post_market_reconciliation(
        self,
        timestamp: datetime | None = None,
    ) -> SessionSummary:
        """Cancel working orders, reconcile end-of-day balances, and produce summary."""
        ts = timestamp or datetime.now(UTC)
        self._log.info("Executing post-market reconciliation", timestamp=ts.isoformat())

        if self.config.auto_cancel_eod:
            self._cancel_working_orders()

        initial_cap = Decimal("10000.00")
        final_equity = self.position_ledger.total_equity
        realized = self.position_ledger.realized_pnl
        unrealized = self.position_ledger.unrealized_pnl
        net_pnl = realized + unrealized
        net_ret = (
            float((final_equity - initial_cap) / initial_cap) * 100.0
            if initial_cap > Decimal("0")
            else 0.0
        )

        open_positions = self.position_ledger.get_open_positions()

        summary = SessionSummary(
            start_time=ts,
            end_time=ts,
            total_cycles=self._total_cycles,
            orders_placed=self._orders_placed,
            fills_executed=self._fills_executed,
            initial_capital=initial_cap,
            final_equity=final_equity,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            net_pnl=net_pnl,
            total_costs=getattr(self.broker, "total_costs", Decimal("0.00")),
            net_return_pct=round(net_ret, 4),
            open_positions_count=len(open_positions),
            closed_trades_count=self._closed_trades_count,
        )

        self._log.info(
            "Session summary compiled",
            final_equity=str(final_equity),
            net_pnl=str(net_pnl),
            return_pct=summary.net_return_pct,
            total_cycles=self._total_cycles,
        )
        return summary

    def process_candle(self, candle: OHLCVCandle) -> CycleResult:
        """Process a closed candle through the full Trading Brain evaluation loop."""
        phase = self.get_market_session_phase(candle.timestamp)
        if phase != MarketSessionPhase.REGULAR_HOURS:
            return CycleResult(
                timestamp=candle.timestamp,
                instrument=candle.instrument,
                candle=candle,
                phase=phase,
                equity=self.position_ledger.total_equity,
                cash=self.position_ledger.cash,
                reason=f"Outside regular trading hours (phase: {phase.value})",
            )

        # 1. Update candle buffer
        buf = self._candle_buffers[candle.instrument]
        buf.append(candle)

        # 2. Update broker and ledger market price, match working limit orders on tick
        self._update_market_valuation(candle)

        # 3. Check pending timeouts in order manager
        self.order_manager.check_pending_timeouts(auto_cancel=True)

        # 4. Check warm-up buffer sufficiency
        if len(buf) < self.config.warmup_bars:
            return CycleResult(
                timestamp=candle.timestamp,
                instrument=candle.instrument,
                candle=candle,
                phase=phase,
                equity=self.position_ledger.total_equity,
                cash=self.position_ledger.cash,
                reason=f"Buffering warm-up bars ({len(buf)}/{self.config.warmup_bars})",
            )

        # 5. Check connection monitor liveness suppression
        if self.connection_monitor and self.connection_monitor.should_suppress_trading():
            self._total_cycles += 1
            return CycleResult(
                timestamp=candle.timestamp,
                instrument=candle.instrument,
                candle=candle,
                phase=phase,
                equity=self.position_ledger.total_equity,
                cash=self.position_ledger.cash,
                reason="Trading suppressed by connection monitor",
            )

        # 6. Check startup reconciliation lock
        if self.reconciler is not None and not self.reconciler.can_submit_orders():
            self._total_cycles += 1
            return CycleResult(
                timestamp=candle.timestamp,
                instrument=candle.instrument,
                candle=candle,
                phase=phase,
                equity=self.position_ledger.total_equity,
                cash=self.position_ledger.cash,
                reason="Trading suppressed: startup reconciliation failed or pending",
            )

        # 7. Execute full evaluation pipeline
        return self._evaluate_and_execute_cycle(candle, buf, phase)

    def run_session(self, candles: list[OHLCVCandle]) -> SessionSummary:
        """Execute a full session over a sequence of candles in fast-forward mode."""
        if not candles:
            now = datetime.now(UTC)
            return SessionSummary(
                start_time=now,
                end_time=now,
                initial_capital=self.position_ledger.cash,
                final_equity=self.position_ledger.total_equity,
            )

        start_time = candles[0].timestamp
        self.pre_market_reconciliation(start_time)

        for candle in candles:
            self.process_candle(candle)

        end_time = candles[-1].timestamp
        summary = self.post_market_reconciliation(end_time)
        return summary.model_copy(update={"start_time": start_time, "end_time": end_time})

    def run_continuous(self, stop_event: threading.Event | None = None) -> None:
        """Run continuous market-hours loop with graceful signal traps."""
        event = stop_event or threading.Event()
        self._stop_event = event

        def _handle_signal(signum: int, _frame: Any) -> None:
            self._log.warning("Interrupt signal received; stopping gracefully", signal=signum)
            event.set()

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

        self._log.info("TradingBrainRunner continuous loop started")
        last_phase = None

        while not event.is_set():
            now = datetime.now(UTC)
            phase = self.get_market_session_phase(now)

            if phase != last_phase:
                self._log.info(
                    "Market session phase changed",
                    from_phase=str(last_phase),
                    to_phase=phase.value,
                )
                last_phase = phase

                if phase == MarketSessionPhase.PRE_MARKET:
                    self.pre_market_reconciliation(now)
                elif phase == MarketSessionPhase.POST_MARKET:
                    self.post_market_reconciliation(now)

            event.wait(self.config.cycle_interval_seconds)

        self._log.info("TradingBrainRunner continuous loop stopped cleanly")

    def _update_market_valuation(self, candle: OHLCVCandle) -> None:
        """Update market price on broker and ledger, matching resting orders."""
        if hasattr(self.broker, "set_market_price"):
            self.broker.set_market_price(candle.instrument, candle.close)

        if hasattr(self.broker, "on_tick"):
            tick_fills = self.broker.on_tick(candle.instrument, candle.close)
            for fill in tick_fills:
                self.position_ledger.apply_fill(fill)
                self._on_fill_executed(fill)

        self.position_ledger.mark_to_market(
            candle.instrument, candle.close, timestamp=candle.timestamp
        )

    def _evaluate_and_execute_cycle(
        self,
        candle: OHLCVCandle,
        buf: deque[OHLCVCandle],
        phase: MarketSessionPhase,
    ) -> CycleResult:
        """Perform quantitative feature extraction, signal aggregation, and order dispatch."""
        self._total_cycles += 1

        # 1. Feature computation
        df = self._candles_to_df(buf)
        features = self.feature_engine.compute_features(
            df,
            instrument=candle.instrument,
            timeframe=candle.timeframe,
            cutoff_time=candle.timestamp,
        )

        # 2. Regime detection & hysteresis filtering
        raw_regime = self.regime_detector.classify(features)
        filtered_regime = self.regime_filter.filter(raw_regime)

        # 3. Multi-agent evaluation
        signals = [
            agent.evaluate(candle.instrument, candle.timeframe, features, filtered_regime)
            for agent in self.agents
        ]

        # 4. Signal aggregation
        agg = self.aggregator.aggregate(
            signals, timestamp=candle.timestamp, timeframe=candle.timeframe
        )

        # 5. Candidate formulation & risk / supervisor gate
        candidate = self._formulate_candidate(candle, agg)
        capital = self.position_ledger.get_capital_state()
        streak = self.streak_tracker.get_state()
        curr_vol = (
            Decimal("2.00")
            if filtered_regime.volatility_level == VolatilityLevel.HIGH
            else Decimal("1.00")
        )
        avg_vol = Decimal("1.50")
        market = MarketState(
            instrument=candle.instrument,
            current_volatility=curr_vol,
            trailing_20session_avg_volatility=avg_vol,
            data_quality="VALIDATED",
            exchange_condition="NORMAL",
        )
        pos = self.position_ledger.get_position(candle.instrument)
        has_open_pos = pos is not None and pos.quantity != 0

        decision = self.supervisor.decide(candidate, capital, streak, market, has_open_pos)

        # 6. Audit decision record
        agent_scores = {
            s.agent_id: s.confidence
            * (
                1.0
                if s.direction in (SignalDirection.LONG, "BUY")
                else (-1.0 if s.direction in (SignalDirection.SHORT, "SELL") else 0.0)
            )
            for s in signals
        }
        regime_str = f"{filtered_regime.trend_state.value}_{filtered_regime.volatility_level.value}"
        record = self.supervisor.build_decision_record(
            decision,
            candle.instrument,
            regime=regime_str,
            agent_scores=agent_scores,
            aggregated_score=agg.weighted_score,
            git_commit=self.config.git_commit,
        )

        # 7. Order execution if trade approved
        executed_fill = None
        if decision.is_trade_approved and decision.approved_quantity > 0:
            executed_fill = self._execute_approved_trade(candle, decision, record)

        return CycleResult(
            timestamp=candle.timestamp,
            instrument=candle.instrument,
            candle=candle,
            phase=phase,
            regime=filtered_regime,
            agent_signals=signals,
            aggregation=agg,
            decision=decision,
            decision_record=record,
            executed_fill=executed_fill,
            equity=self.position_ledger.total_equity,
            cash=self.position_ledger.cash,
            reason=decision.reason,
        )

    def _formulate_candidate(
        self,
        candle: OHLCVCandle,
        agg: AggregationResult,
    ) -> CandidateTrade | None:
        """Formulate a CandidateTrade from consensus direction with protective stop loss."""
        if not agg.passed or agg.direction not in ("BUY", "SELL"):
            return None

        entry_price = candle.close
        stop_dist = max(
            entry_price * self.config.default_stop_loss_pct,
            Decimal("0.05"),
        )

        if agg.direction == "BUY":
            stop_price = (entry_price - stop_dist).quantize(Decimal("0.05"), rounding=ROUND_HALF_UP)
        else:
            stop_price = (entry_price + stop_dist).quantize(Decimal("0.05"), rounding=ROUND_HALF_UP)

        expected_value = (
            (stop_dist * self.config.risk_reward_ratio * Decimal(str(round(agg.score, 4))))
            - (stop_dist * (Decimal("1.0") - Decimal(str(round(agg.score, 4)))))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return CandidateTrade(
            instrument=candle.instrument,
            direction=agg.direction,
            entry_price=entry_price,
            stop_price=stop_price,
            timeframe=candle.timeframe,
            trade_quality_score=agg.score,
            expected_value=expected_value,
            confidence=agg.score,
            timestamp=candle.timestamp,
        )

    def _execute_approved_trade(
        self,
        candle: OHLCVCandle,
        decision: Decision,
        record: DecisionRecord,
    ) -> OrderFill | None:
        """Dispatch risk-approved order and record execution fill."""
        client_order_id = generate_client_order_id(str(record.decision_record_id))
        direction: Literal["BUY", "SELL"] = "BUY" if decision.outcome == "BUY" else "SELL"
        submission = self.order_dispatcher.dispatch_order(
            broker=self.broker,
            client_order_id=client_order_id,
            instrument=candle.instrument,
            direction=direction,
            quantity=decision.approved_quantity,
            order_type="LIMIT",
            price=candle.close,
        )

        if not self.order_manager.get_order(client_order_id):
            self.order_manager.register_order(submission)

        self._orders_placed += 1

        if submission.status == "FILLED":
            fill = None
            if hasattr(self.broker, "fills") and self.broker.fills:
                for f in reversed(self.broker.fills):
                    if f.client_order_id == client_order_id:
                        fill = f
                        break
            if fill is None:
                fill = OrderFill(
                    fill_id=f"FILL-{uuid4().hex[:12].upper()}",
                    client_order_id=client_order_id,
                    instrument=candle.instrument,
                    direction=direction,
                    quantity=decision.approved_quantity,
                    price=candle.close,
                    commission=Decimal("0.00"),
                    timestamp=candle.timestamp,
                )
            self.position_ledger.apply_fill(fill)
            self._on_fill_executed(fill)
            return fill

        return None

    def _on_fill_executed(self, fill: OrderFill) -> None:
        """Update internal state and streak tracker on executed fill."""
        self._fills_executed += 1
        pos = self.position_ledger.get_position(fill.instrument)
        if pos and pos.realized_pnl != Decimal("0.00"):
            prior = self._last_realized_pnl.get(fill.instrument, Decimal("0.00"))
            diff = pos.realized_pnl - prior
            if diff != Decimal("0.00"):
                self.streak_tracker.record_trade(
                    diff, trade_id=fill.fill_id, exit_time=fill.timestamp
                )
                self._last_realized_pnl[fill.instrument] = pos.realized_pnl
                self._closed_trades_count += 1

    def _cancel_working_orders(self) -> None:
        """Cancel working orders across the order book."""
        working = self.order_manager.get_orders_by_status("SUBMITTED")
        for o in working:
            try:
                self.broker.cancel_order(o.client_order_id)
                self.order_manager.transition_to(
                    o.client_order_id,
                    "CANCELLED",
                    reason="Post-market EOD auto-cancel",
                )
            except Exception as e:
                self._log.error(
                    "Failed to cancel working order",
                    client_order_id=o.client_order_id,
                    error=str(e),
                )

    @staticmethod
    def _candles_to_df(candles: deque[OHLCVCandle]) -> pd.DataFrame:
        """Convert candle deque to pandas DataFrame required by FeatureEngine."""
        records = [
            {
                "timestamp": c.timestamp,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": c.volume,
            }
            for c in candles
        ]
        return pd.DataFrame(records)
