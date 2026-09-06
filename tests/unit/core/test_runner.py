"""Unit tests for TradingBrainRunner and market-hours lifecycle orchestration."""

import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from src.core.runner import (
    MarketSessionPhase,
    RunnerConfig,
    SessionSummary,
    TradingBrainRunner,
)
from src.domain.aggregation_result import AggregationResult
from src.domain.decision import Decision
from src.domain.execution import OrderSubmission
from src.domain.market_data import OHLCVCandle
from src.domain.risk import RiskCheckResult
from src.execution.connection_monitor import ConnectionMonitor, ConnectionMonitorConfig
from src.execution.paper_adapter import PaperBrokerAdapter, PaperBrokerConfig
from src.risk.kill_switch import InMemoryKillSwitch

IST = ZoneInfo("Asia/Kolkata")


def create_test_candle(
    timestamp: datetime,
    close_price: Decimal = Decimal("2500.00"),
    instrument: str = "NSE:RELIANCE",
    timeframe: str = "15m",
) -> OHLCVCandle:
    """Helper to construct valid OHLCVCandle instances."""
    return OHLCVCandle(
        instrument=instrument,
        timeframe=timeframe,
        timestamp=timestamp,
        open=close_price - Decimal("2.00"),
        high=close_price + Decimal("5.00"),
        low=close_price - Decimal("4.00"),
        close=close_price,
        volume=10000,
        turnover=close_price * Decimal("10000"),
    )


class TestMarketSessionPhases:
    """Test market session phase classification under IST boundaries."""

    def test_enforce_market_hours_disabled(self) -> None:
        """When enforcement is disabled, all timestamps evaluate to REGULAR_HOURS."""
        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=False)
        runner = TradingBrainRunner(broker=broker, config=config)

        # Sunday midnight IST
        sunday_dt = datetime(2026, 9, 6, 0, 0, tzinfo=IST)
        assert runner.get_market_session_phase(sunday_dt) == MarketSessionPhase.REGULAR_HOURS

        # Weekday midnight IST
        weekday_dt = datetime(2026, 9, 7, 2, 0, tzinfo=IST)
        assert runner.get_market_session_phase(weekday_dt) == MarketSessionPhase.REGULAR_HOURS

    def test_enforce_market_hours_weekdays(self) -> None:
        """Verify PRE_MARKET, REGULAR_HOURS, POST_MARKET, and CLOSED on weekdays."""
        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=True)
        runner = TradingBrainRunner(broker=broker, config=config)

        # Monday 2026-09-07
        monday = datetime(2026, 9, 7, tzinfo=IST)

        # 08:30 IST -> CLOSED
        assert (
            runner.get_market_session_phase(monday.replace(hour=8, minute=30))
            == MarketSessionPhase.CLOSED
        )

        # 09:05 IST -> PRE_MARKET
        assert (
            runner.get_market_session_phase(monday.replace(hour=9, minute=5))
            == MarketSessionPhase.PRE_MARKET
        )

        # 09:15 IST -> REGULAR_HOURS
        assert (
            runner.get_market_session_phase(monday.replace(hour=9, minute=15))
            == MarketSessionPhase.REGULAR_HOURS
        )

        # 14:00 IST -> REGULAR_HOURS
        assert (
            runner.get_market_session_phase(monday.replace(hour=14, minute=0))
            == MarketSessionPhase.REGULAR_HOURS
        )

        # 15:30 IST -> POST_MARKET
        assert (
            runner.get_market_session_phase(monday.replace(hour=15, minute=30))
            == MarketSessionPhase.POST_MARKET
        )

        # 15:59 IST -> POST_MARKET
        assert (
            runner.get_market_session_phase(monday.replace(hour=15, minute=59))
            == MarketSessionPhase.POST_MARKET
        )

        # 16:00 IST -> CLOSED
        assert (
            runner.get_market_session_phase(monday.replace(hour=16, minute=0))
            == MarketSessionPhase.CLOSED
        )

    def test_enforce_market_hours_weekends(self) -> None:
        """Verify that weekends are always CLOSED regardless of time."""
        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=True)
        runner = TradingBrainRunner(broker=broker, config=config)

        # Saturday 2026-09-12 at 11:00 IST
        sat = datetime(2026, 9, 12, 11, 0, tzinfo=IST)
        assert runner.get_market_session_phase(sat) == MarketSessionPhase.CLOSED

        # Sunday 2026-09-13 at 14:00 IST
        sun = datetime(2026, 9, 13, 14, 0, tzinfo=IST)
        assert runner.get_market_session_phase(sun) == MarketSessionPhase.CLOSED


class TestPreAndPostMarketReconciliation:
    """Test pre-market health checks and post-market EOD reconciliations."""

    def test_pre_market_reconciliation_healthy(self) -> None:
        """Verify pre-market reconciliation checks broker ping and streak start."""
        broker = PaperBrokerAdapter()
        streak_tracker = MagicMock()
        runner = TradingBrainRunner(broker=broker, streak_tracker=streak_tracker)

        runner.pre_market_reconciliation(datetime(2026, 9, 7, 9, 5, tzinfo=UTC))
        streak_tracker.on_session_start.assert_called_once()

    def test_pre_market_reconciliation_broker_error_handled(self) -> None:
        """Verify broker exceptions during pre-market queries are handled gracefully."""
        broker = MagicMock()
        broker.heartbeat.return_value = False
        broker.get_positions.side_effect = RuntimeError("Broker down")
        streak_tracker = MagicMock()

        runner = TradingBrainRunner(broker=broker, streak_tracker=streak_tracker)
        # Should not raise exception
        runner.pre_market_reconciliation()
        streak_tracker.on_session_start.assert_called_once()

    def test_post_market_reconciliation_cancels_working_orders(self) -> None:
        """Verify post-market reconciliation cancels working orders and compiles summary."""
        broker = PaperBrokerAdapter(
            config=PaperBrokerConfig(fill_mode="QUOTE_DRIVEN"),
        )
        runner = TradingBrainRunner(
            broker=broker,
            config=RunnerConfig(auto_cancel_eod=True),
        )

        # Manually register a working order
        sub = broker.place_order(
            client_order_id="TEST-ORD-001",
            instrument="NSE:RELIANCE",
            direction="BUY",
            quantity=5,
            order_type="LIMIT",
            price=Decimal("2400.00"),
        )
        runner.order_manager.register_order(sub)
        assert len(runner.order_manager.get_orders_by_status("SUBMITTED")) == 1

        summary = runner.post_market_reconciliation()
        assert isinstance(summary, SessionSummary)
        assert len(runner.order_manager.get_orders_by_status("SUBMITTED")) == 0
        assert summary.initial_capital == Decimal("10000.00")
        assert summary.final_equity == Decimal("10000.00")


class TestProcessCandlePipeline:
    """Test candle ingestion, warm-up buffering, suppression, and execution."""

    def test_process_candle_outside_market_hours(self) -> None:
        """Candles received outside regular hours are rejected with reason."""
        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=True)
        runner = TradingBrainRunner(broker=broker, config=config)

        # 08:30 IST candle
        candle = create_test_candle(datetime(2026, 9, 7, 8, 30, tzinfo=IST).astimezone(UTC))
        res = runner.process_candle(candle)

        assert res.phase == MarketSessionPhase.CLOSED
        assert res.decision is None
        assert "Outside regular trading hours" in (res.reason or "")

    def test_process_candle_warmup_buffering(self) -> None:
        """Candles received during warm-up phase accumulate in buffer without trading."""
        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=False, warmup_bars=5)
        runner = TradingBrainRunner(broker=broker, config=config)

        base_time = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
        for i in range(4):
            candle = create_test_candle(base_time + timedelta(minutes=15 * i))
            res = runner.process_candle(candle)
            assert res.decision is None
            assert f"Buffering warm-up bars ({i + 1}/5)" in (res.reason or "")

        assert runner.total_cycles == 0

    def test_process_candle_connection_monitor_suppression(self) -> None:
        """When connection monitor signals failure, cycles are suppressed."""
        broker = PaperBrokerAdapter()
        monitor = ConnectionMonitor(
            config=ConnectionMonitorConfig(max_consecutive_failures=1),
        )
        monitor.record_heartbeat_failure()
        assert monitor.should_suppress_trading() is True

        config = RunnerConfig(enforce_market_hours=False, warmup_bars=3)
        runner = TradingBrainRunner(
            broker=broker,
            connection_monitor=monitor,
            config=config,
        )

        base_time = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
        # Buffer 2 candles (< warmup_bars=3)
        runner.process_candle(create_test_candle(base_time))
        runner.process_candle(create_test_candle(base_time + timedelta(minutes=15)))

        # 3rd candle reaches warmup, should be suppressed by connection monitor
        res = runner.process_candle(create_test_candle(base_time + timedelta(minutes=30)))
        assert res.reason == "Trading suppressed by connection monitor"
        assert res.decision is None
        assert runner.total_cycles == 1

    def test_process_candle_kill_switch_active_forces_no_trade(self) -> None:
        """When kill switch is active, supervisor emits NO_TRADE."""
        kill_switch = InMemoryKillSwitch()
        kill_switch.activate(source="Test", reason="Risk limit breach")

        broker = PaperBrokerAdapter()
        config = RunnerConfig(enforce_market_hours=False, warmup_bars=5)
        runner = TradingBrainRunner(
            broker=broker,
            kill_switch=kill_switch,
            config=config,
        )

        base_time = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
        # Buffer 4 bars (< warmup_bars=5)
        for i in range(4):
            runner.process_candle(create_test_candle(base_time + timedelta(minutes=15 * i)))

        # 5th bar completes warmup (satisfies FeatureEngine min_bars=5)
        res = runner.process_candle(create_test_candle(base_time + timedelta(minutes=60)))
        assert res.decision is not None
        assert res.decision.kill_switch_active is True
        assert res.decision.outcome in ("NO_TRADE", "HOLD")
        assert runner.orders_placed == 0

    def test_candidate_formulation_buy_and_sell(self) -> None:
        """Verify candidate trade formulation computes tick-rounded stops and targets."""
        broker = PaperBrokerAdapter()
        runner = TradingBrainRunner(
            broker=broker,
            config=RunnerConfig(
                default_stop_loss_pct=Decimal("0.02"), risk_reward_ratio=Decimal("2.0")
            ),
        )
        candle = create_test_candle(datetime.now(UTC), close_price=Decimal("1000.00"))

        # BUY candidate
        buy_agg = AggregationResult(
            timestamp=candle.timestamp,
            selected_timeframe="15m",
            weighted_score=0.8,
            direction="BUY",
            score=0.8,
            disagreement=0.0,
            passed=True,
            reason="Strong bullish consensus",
        )
        cand_buy = runner._formulate_candidate(candle, buy_agg)
        assert cand_buy is not None
        assert cand_buy.direction == "BUY"
        assert cand_buy.entry_price == Decimal("1000.00")
        assert cand_buy.stop_price == Decimal("980.00")  # 2% below
        assert cand_buy.timeframe == "15m"
        assert cand_buy.expected_value > Decimal("0")

        # SELL candidate
        sell_agg = AggregationResult(
            timestamp=candle.timestamp,
            selected_timeframe="15m",
            weighted_score=-0.75,
            direction="SELL",
            score=0.75,
            disagreement=0.0,
            passed=True,
            reason="Strong bearish consensus",
        )
        cand_sell = runner._formulate_candidate(candle, sell_agg)
        assert cand_sell is not None
        assert cand_sell.direction == "SELL"
        assert cand_sell.entry_price == Decimal("1000.00")
        assert cand_sell.stop_price == Decimal("1020.00")  # 2% above
        assert cand_sell.timeframe == "15m"

        # Non-passed candidate
        noop_agg = AggregationResult(
            timestamp=candle.timestamp,
            selected_timeframe="15m",
            weighted_score=0.1,
            direction=None,
            score=0.1,
            disagreement=0.0,
            passed=False,
            reason="Below threshold",
        )
        assert runner._formulate_candidate(candle, noop_agg) is None


class TestSessionExecution:
    """Test full session fast-forward run and continuous execution."""

    def test_run_session_empty_candles(self) -> None:
        """Empty candle list returns valid zeroed summary."""
        broker = PaperBrokerAdapter()
        runner = TradingBrainRunner(broker=broker)

        summary = runner.run_session([])
        assert summary.total_cycles == 0
        assert summary.orders_placed == 0
        assert summary.final_equity == Decimal("10000.00")

    def test_run_session_with_candle_stream(self) -> None:
        """Run simulated multi-bar session through full Trading Brain loop."""
        broker = PaperBrokerAdapter()
        runner = TradingBrainRunner(
            broker=broker,
            config=RunnerConfig(enforce_market_hours=False, warmup_bars=10),
        )

        base_time = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
        candles = [
            create_test_candle(
                base_time + timedelta(minutes=15 * i),
                close_price=Decimal(str(2500.0 + (i * 2.5))),
            )
            for i in range(25)
        ]

        summary = runner.run_session(candles)
        assert isinstance(summary, SessionSummary)
        assert summary.total_cycles == 16  # 25 total - 9 warmup (len < 10)
        assert summary.initial_capital == Decimal("10000.00")
        assert summary.final_equity > Decimal("0")

    def test_run_continuous_stops_on_event(self) -> None:
        """Continuous execution loop terminates gracefully upon event trigger."""
        broker = PaperBrokerAdapter()
        runner = TradingBrainRunner(
            broker=broker,
            config=RunnerConfig(cycle_interval_seconds=0.01),
        )

        event = threading.Event()
        # Trigger stop after brief delay
        timer = threading.Timer(0.05, event.set)
        timer.start()

        runner.run_continuous(stop_event=event)
        assert event.is_set() is True
        timer.join()

    def test_candles_to_df_conversion(self) -> None:
        """Static helper accurately converts candle deque to dataframe."""
        base_time = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
        c1 = create_test_candle(base_time, close_price=Decimal("100.00"))
        c2 = create_test_candle(base_time + timedelta(minutes=15), close_price=Decimal("105.00"))

        buf = deque([c1, c2])
        df = TradingBrainRunner._candles_to_df(buf)

        assert len(df) == 2
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert df.iloc[0]["close"] == 100.0
        assert df.iloc[1]["close"] == 105.0

    def test_execute_approved_trade_and_closed_trade_accounting(self) -> None:
        """Verify approved trade dispatch, fill recording, and closed-trade PnL accounting."""
        broker = PaperBrokerAdapter()
        runner = TradingBrainRunner(broker=broker)

        candle_buy = create_test_candle(datetime.now(UTC), close_price=Decimal("2500.00"))
        decision_buy = Decision(
            outcome="BUY",
            reason="Approved by supervisor",
            risk_check=RiskCheckResult(
                passed=True,
                failed_check=None,
                rtld_param_id=None,
                reason="all checks passed",
                config_version="v1.0",
                approved_quantity=2,
                stop_loss_price=Decimal("2450.00"),
            ),
            kill_switch_active=False,
            approved_quantity=2,
            stop_loss_price=Decimal("2450.00"),
        )
        record_buy = runner.supervisor.build_decision_record(
            decision_buy,
            candle_buy.instrument,
            regime="TRENDING_UP_NORMAL",
            agent_scores={"trend_v1": 0.8},
            aggregated_score=0.8,
            git_commit="live",
        )

        fill_buy = runner._execute_approved_trade(candle_buy, decision_buy, record_buy)
        assert fill_buy is not None
        assert runner.orders_placed == 1
        assert runner.fills_executed == 1
        pos_buy = runner.position_ledger.get_position("NSE:RELIANCE")
        assert pos_buy is not None
        assert pos_buy.quantity == 2

        # Execute closing SELL trade
        candle_sell = create_test_candle(
            candle_buy.timestamp + timedelta(minutes=15), close_price=Decimal("2550.00")
        )
        decision_sell = Decision(
            outcome="SELL",
            reason="Take profit approved",
            risk_check=RiskCheckResult(
                passed=True,
                failed_check=None,
                rtld_param_id=None,
                reason="all checks passed",
                config_version="v1.0",
                approved_quantity=2,
                stop_loss_price=Decimal("2600.00"),
            ),
            kill_switch_active=False,
            approved_quantity=2,
            stop_loss_price=Decimal("2600.00"),
        )
        record_sell = runner.supervisor.build_decision_record(
            decision_sell,
            candle_sell.instrument,
            regime="TRENDING_UP_NORMAL",
            agent_scores={"trend_v1": -0.8},
            aggregated_score=-0.8,
            git_commit="live",
        )

        fill_sell = runner._execute_approved_trade(candle_sell, decision_sell, record_sell)
        assert fill_sell is not None
        assert runner.orders_placed == 2
        assert runner.fills_executed == 2
        pos_sell = runner.position_ledger.get_position("NSE:RELIANCE")
        assert pos_sell is not None
        assert pos_sell.quantity == 0
        assert runner._closed_trades_count == 1
        assert runner.position_ledger.realized_pnl > Decimal("0")

    def test_on_tick_limit_order_fill(self) -> None:
        """Verify resting limit orders match and fill upon subsequent candle tick."""
        broker = PaperBrokerAdapter(config=PaperBrokerConfig(fill_mode="QUOTE_DRIVEN"))
        runner = TradingBrainRunner(broker=broker)

        sub = broker.place_order(
            client_order_id="TEST-TICK-001",
            instrument="NSE:RELIANCE",
            direction="BUY",
            quantity=1,
            order_type="LIMIT",
            price=Decimal("2400.00"),
        )
        runner.order_manager.register_order(sub)
        assert runner.fills_executed == 0

        # Market price dips below 2400 limit price, matching the resting order
        candle = create_test_candle(datetime.now(UTC), close_price=Decimal("2390.00"))
        runner._update_market_valuation(candle)
        assert runner.fills_executed == 1
        pos_tick = runner.position_ledger.get_position("NSE:RELIANCE")
        assert pos_tick is not None
        assert pos_tick.quantity == 1

    def test_cancel_working_order_exception_handled(self) -> None:
        """Verify broker exceptions during EOD order cancellation are trapped and logged."""
        broker = MagicMock()
        broker.cancel_order.side_effect = RuntimeError("Broker network timeout")
        runner = TradingBrainRunner(broker=broker)

        sub = OrderSubmission(
            client_order_id="FAIL-ORD-001",
            broker_order_id="B-FAIL-001",
            instrument="NSE:RELIANCE",
            direction="BUY",
            order_type="LIMIT",
            quantity=1,
            status="SUBMITTED",
            submitted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        runner.order_manager.register_order(sub)
        # Should not raise exception
        runner._cancel_working_orders()
