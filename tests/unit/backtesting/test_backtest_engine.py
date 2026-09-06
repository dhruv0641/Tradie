"""Unit and known-answer validation tests for BacktestEngine (BTD §7, NFR-TEST-4)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.cost_model import CostModelConfig
from src.backtesting.engine import BacktestConfig, BacktestEngine, OrderIntent
from src.backtesting.slippage_model import SlippageConfig
from src.domain.market_data import OHLCVCandle


def _create_candle(
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    *,
    volume: float = 100_000.0,
    symbol: str = "TCS",
) -> OHLCVCandle:
    """Helper to generate sequential synthetic test candles."""
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC) + timedelta(minutes=15 * index)
    return OHLCVCandle(
        instrument=symbol,
        timeframe="15m",
        timestamp=base_time,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=int(volume),
        turnover=Decimal(str(round(float(close_price) * volume, 2))),
    )


def test_lookahead_violation_guards() -> None:
    """Verify engine blocks lookahead violations on order generation and execution."""
    engine = BacktestEngine()
    candle0 = _create_candle(
        0, Decimal("100.00"), Decimal("105.00"), Decimal("98.00"), Decimal("102.00")
    )
    candle1 = _create_candle(
        1, Decimal("102.00"), Decimal("106.00"), Decimal("101.00"), Decimal("105.00")
    )

    engine.process_bar(candle0, 0)

    # Order marked as generated at bar 1 while engine is at bar 0
    invalid_order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=10,
        generated_at_bar_index=1,
        generated_at_time=candle1.timestamp,
    )
    with pytest.raises(ValueError, match="Look-ahead violation"):
        engine.submit_order(invalid_order)

    # Non-monotonic bar index
    with pytest.raises(ValueError, match="Non-monotonic bar index"):
        engine.process_bar(candle1, 0)


def test_next_bar_open_fill_timing() -> None:
    """Verify order generated on bar T close executes strictly on bar T+1 open (BTD §7)."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("101.00")
    )
    c1 = _create_candle(
        1, Decimal("103.00"), Decimal("107.00"), Decimal("102.00"), Decimal("106.00")
    )

    engine.process_bar(c0, 0)
    assert len(engine.portfolio.positions) == 0

    # Decision at bar 0 close
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    assert len(engine.portfolio.positions) == 0  # Still not filled!

    # Bar 1 arrives: order must fill at bar 1 open (103.00 + half spread & slippage)
    engine.process_bar(c1, 1)
    assert "TCS" in engine.portfolio.positions
    pos = engine.portfolio.positions["TCS"]
    # With 5 bps base slippage + 2.5 bps half spread = 7.5 bps adverse drag on 103.00 ~ 103.08
    assert pos.entry_price > Decimal("103.00")
    assert pos.entry_time == c1.timestamp


def test_gap_open_execution() -> None:
    """Verify large overnight gap fills at gapped open rather than requested/prev close."""
    engine = BacktestEngine(BacktestConfig(gap_threshold_pct=Decimal("0.02")))
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("100.00")
    )
    # Next day gaps up 10% from 100.00 to 110.00
    c1 = _create_candle(
        1, Decimal("110.00"), Decimal("115.00"), Decimal("109.00"), Decimal("112.00")
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)

    engine.process_bar(c1, 1)
    pos = engine.portfolio.positions["TCS"]
    # Fill price must be based on gapped open (110.00), not previous close (100.00)
    assert pos.entry_price >= Decimal("110.00")


def test_intrabar_stop_loss_hit() -> None:
    """Verify stop-loss executes when candle low breaches stop price."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("101.00"), Decimal("99.00"), Decimal("100.00")
    )
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("101.00")
    )
    # Bar 2 low drops to 93.00, breaching stop loss at 95.00
    c2 = _create_candle(2, Decimal("100.00"), Decimal("101.00"), Decimal("93.00"), Decimal("96.00"))

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        stop_loss=Decimal("95.00"),
        take_profit=Decimal("115.00"),
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    engine.process_bar(c1, 1)
    assert "TCS" in engine.portfolio.positions

    engine.process_bar(c2, 2)
    assert "TCS" not in engine.portfolio.positions
    assert len(engine.portfolio.trades) == 1
    trade = engine.portfolio.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price <= Decimal("95.00")  # Executed at stop loss minus slippage


def test_intrabar_take_profit_hit() -> None:
    """Verify take-profit executes when candle high breaches target price."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("101.00"), Decimal("99.00"), Decimal("100.00")
    )
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("101.00")
    )
    # Bar 2 high rises to 112.00, breaching target at 110.00
    c2 = _create_candle(
        2, Decimal("101.00"), Decimal("112.00"), Decimal("100.00"), Decimal("108.00")
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        stop_loss=Decimal("90.00"),
        take_profit=Decimal("110.00"),
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    engine.process_bar(c1, 1)

    engine.process_bar(c2, 2)
    assert "TCS" not in engine.portfolio.positions
    assert len(engine.portfolio.trades) == 1
    trade = engine.portfolio.trades[0]
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.exit_price >= Decimal("109.00")  # Near 110.00 minus adverse sell drag


def test_conservative_tie_breaking() -> None:
    """Verify conservative tie-breaking: stop-loss executes first if both touched."""
    # Test with conservative_tie_breaking=True (Default)
    engine_conservative = BacktestEngine(BacktestConfig(conservative_tie_breaking=True))
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("101.00"), Decimal("99.00"), Decimal("100.00")
    )
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("100.00")
    )
    # Wild bar: Low hits 90 (below stop 95), High hits 115 (above target 110)
    c2_wild = _create_candle(
        2, Decimal("100.00"), Decimal("115.00"), Decimal("90.00"), Decimal("102.00")
    )

    engine_conservative.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        stop_loss=Decimal("95.00"),
        take_profit=Decimal("110.00"),
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine_conservative.submit_order(order)
    engine_conservative.process_bar(c1, 1)

    engine_conservative.process_bar(c2_wild, 2)
    assert len(engine_conservative.portfolio.trades) == 1
    trade_conservative = engine_conservative.portfolio.trades[0]
    assert trade_conservative.exit_reason == "STOP_LOSS"

    # Test with conservative_tie_breaking=False
    engine_optimistic = BacktestEngine(BacktestConfig(conservative_tie_breaking=False))
    engine_optimistic.process_bar(c0, 0)
    engine_optimistic.submit_order(order)
    engine_optimistic.process_bar(c1, 1)
    engine_optimistic.process_bar(c2_wild, 2)
    assert len(engine_optimistic.portfolio.trades) == 1
    trade_optimistic = engine_optimistic.portfolio.trades[0]
    assert trade_optimistic.exit_reason == "TAKE_PROFIT"


def test_limit_order_unfilled_behavior() -> None:
    """Verify limit BUY orders do not fill if execution price exceeds limit."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("99.00"), Decimal("100.00")
    )
    c1 = _create_candle(
        1, Decimal("105.00"), Decimal("108.00"), Decimal("104.00"), Decimal("106.00")
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=5,
        order_type="LIMIT",
        limit_price=Decimal("102.00"),  # Limit is 102.00, but open is 105.00
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)

    engine.process_bar(c1, 1)
    # Position should not open because 105 > 102
    assert len(engine.portfolio.positions) == 0


def test_slippage_rejection_in_engine() -> None:
    """Verify orders exceeding liquidity limits are rejected by slippage model in engine."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("101.00"), Decimal("99.00"), Decimal("100.00"), volume=100.0
    )
    # Low volume bar: 100 shares. Order quantity 10 shares = 10% volume > 5% limit!
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("101.00"), Decimal("99.00"), Decimal("100.00"), volume=100.0
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=10,  # 10% of 100 volume
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)

    engine.process_bar(c1, 1)
    # Must be rejected due to excessive volume share
    assert len(engine.portfolio.positions) == 0


def test_known_answer_synthetic_series_run() -> None:
    """Verify complete end-to-end backtest against known-answer synthetic price sequence."""
    config = BacktestConfig(
        strategy_id="known_answer_test",
        initial_capital=Decimal("10000.00"),
        cost_config=CostModelConfig(),
        slippage_config=SlippageConfig(),
        force_close_at_end=True,
    )
    engine = BacktestEngine(config)

    # 4 sequential candles
    candles = [
        _create_candle(
            0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
        ),
        _create_candle(
            1, Decimal("100.00"), Decimal("105.00"), Decimal("99.00"), Decimal("104.00")
        ),
        _create_candle(
            2, Decimal("105.00"), Decimal("110.00"), Decimal("103.00"), Decimal("108.00")
        ),
        _create_candle(
            3, Decimal("108.00"), Decimal("112.00"), Decimal("106.00"), Decimal("110.00")
        ),
    ]

    def simple_strategy(
        _eng: BacktestEngine, bar_idx: int, candle: OHLCVCandle
    ) -> list[OrderIntent]:
        # On bar 0 close: Buy 10 shares of TCS
        if bar_idx == 0:
            return [
                OrderIntent(
                    symbol="TCS",
                    direction="BUY",
                    quantity=10,
                    generated_at_bar_index=bar_idx,
                    generated_at_time=candle.timestamp,
                )
            ]
        return []

    result = engine.run(candles, simple_strategy)

    assert result.strategy_id == "known_answer_test"
    assert result.initial_capital == Decimal("10000.00")
    # Position bought at bar 1 open (~100.08) and force-closed at bar 3 close (~109.92)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "TCS"
    assert trade.quantity == 10
    assert trade.exit_reason == "END_OF_DATA"
    assert trade.gross_pnl > Decimal("0")  # Profitable trade
    assert trade.net_pnl > Decimal("0")
    assert trade.total_costs > Decimal("0")

    # Metrics verification
    assert result.metrics.total_trades == 1
    assert result.metrics.winning_trades == 1
    assert result.metrics.losing_trades == 0
    assert result.metrics.win_rate == Decimal("100.00")
    assert result.final_equity > Decimal("10000.00")
    assert len(result.equity_curve) == 4


def test_engine_run_validations() -> None:
    """Verify engine.run validations for empty and non-chronological candles."""
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="cannot be empty"):
        engine.run([])

    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )
    c1_old = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )

    with pytest.raises(ValueError, match="strictly chronological"):
        engine.run([c0, c1_old])


def test_engine_current_bar_index_and_lookahead_execution_guard() -> None:
    """Verify current_bar_index access and internal lookahead execution guard."""
    engine = BacktestEngine()
    assert engine.current_bar_index == -1

    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )
    engine.process_bar(c0, 0)
    assert engine.current_bar_index == 0

    # Inject order directly into pending to verify internal guard
    illegal_order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=1,
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine._pending_orders.append(illegal_order)
    with pytest.raises(RuntimeError, match="cannot execute on bar"):
        engine._execute_pending_orders(c0)


def test_engine_limit_sell_unfilled() -> None:
    """Verify limit SELL order does not fill if execution price is below limit."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )
    c1 = _create_candle(1, Decimal("95.00"), Decimal("97.00"), Decimal("94.00"), Decimal("96.00"))

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="SELL",
        quantity=5,
        order_type="LIMIT",
        limit_price=Decimal("98.00"),  # Open is 95.00 < 98.00 limit
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    engine.process_bar(c1, 1)
    assert len(engine._pending_orders) == 1  # Unfilled


def test_engine_insufficient_cash_on_fill() -> None:
    """Verify order fails to open when portfolio cash is insufficient at fill time."""
    # Start with ₹100 cash
    engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("100.00")))
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="TCS",
        direction="BUY",
        quantity=10,  # 10 * 100 = 1000 > 100 cash
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    engine.process_bar(c1, 1)

    assert len(engine.portfolio.positions) == 0
    assert any(h.get("status") == "FAILED" for h in engine._order_history)


def test_engine_run_without_callback_and_no_force_close() -> None:
    """Verify run without strategy callback and without force close at end."""
    engine = BacktestEngine(BacktestConfig(force_close_at_end=False))
    candles = [
        _create_candle(
            0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00")
        ),
        _create_candle(
            1, Decimal("101.00"), Decimal("103.00"), Decimal("99.00"), Decimal("102.00")
        ),
    ]

    result = engine.run(candles, strategy_callback=None)
    assert len(result.trades) == 0
    assert len(result.equity_curve) == 2


def test_engine_multisymbol_candle_skips_unmatched_symbols() -> None:
    """Verify intra-bar checks skip positions for different symbols."""
    engine = BacktestEngine()
    c0 = _create_candle(
        0, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00"), symbol="INFY"
    )
    c1 = _create_candle(
        1, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00"), symbol="INFY"
    )
    c2_tcs = _create_candle(
        2, Decimal("100.00"), Decimal("102.00"), Decimal("98.00"), Decimal("100.00"), symbol="TCS"
    )

    engine.process_bar(c0, 0)
    order = OrderIntent(
        symbol="INFY",
        direction="BUY",
        quantity=5,
        stop_loss=Decimal("95.00"),
        generated_at_bar_index=0,
        generated_at_time=c0.timestamp,
    )
    engine.submit_order(order)
    engine.process_bar(c1, 1)
    assert "INFY" in engine.portfolio.positions

    # Bar 2 is for TCS, so INFY position should not be touched
    engine.process_bar(c2_tcs, 2)
    assert "INFY" in engine.portfolio.positions
