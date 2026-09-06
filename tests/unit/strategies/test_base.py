"""Unit tests for BaseStrategy abstract class and helper methods."""

from datetime import UTC, datetime
from decimal import Decimal

from src.backtesting.engine import BacktestEngine, OrderIntent
from src.domain.market_data import OHLCVCandle
from src.strategies.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    """Concrete test dummy implementation of BaseStrategy."""

    def on_bar(
        self,
        engine: BacktestEngine,
        bar_idx: int,
        candle: OHLCVCandle,
    ) -> list[OrderIntent]:
        _ = (engine, bar_idx, candle)
        return []


def _make_candle(price: Decimal = Decimal("100.00")) -> OHLCVCandle:
    return OHLCVCandle(
        instrument="TCS",
        timeframe="15m",
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        open=price,
        high=price + Decimal("2.00"),
        low=price - Decimal("2.00"),
        close=price,
        volume=10000,
        turnover=price * Decimal("10000"),
    )


def test_base_strategy_initialization_and_reset() -> None:
    """Verify parameters, candle buffer, and reset behavior."""
    strat = DummyStrategy(name="test_strat", parameters={"p1": 10})
    assert strat.name == "test_strat"
    assert strat.parameters == {"p1": 10}
    assert len(strat._candles) == 0

    engine = BacktestEngine()
    candle = _make_candle()
    strat(engine, 0, candle)
    assert len(strat._candles) == 1

    strat.reset()
    assert len(strat._candles) == 0


def test_base_strategy_position_helpers() -> None:
    """Verify has_position and get_position helpers query portfolio correctly."""
    strat = DummyStrategy(name="test_strat")
    engine = BacktestEngine()

    assert not strat.has_position(engine, "TCS")
    assert strat.get_position(engine, "TCS") is None

    # Open a position manually in engine
    engine.portfolio.open_position(
        symbol="TCS",
        direction="BUY",
        quantity=10,
        fill_price=Decimal("100.00"),
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        entry_cost=Decimal("20.00"),
    )

    assert strat.has_position(engine, "TCS")
    pos = strat.get_position(engine, "TCS")
    assert pos is not None
    assert pos.quantity == 10


def test_calculate_position_size_risk_and_cash_constraints() -> None:
    """Verify sizing respects both cash margin limits and risk-defined stop distance."""
    strat = DummyStrategy(name="test_strat")

    # Zero or invalid inputs
    assert (
        strat.calculate_position_size(
            available_cash=Decimal("0"),
            price=Decimal("100.00"),
            risk_amount=Decimal("100.00"),
            stop_distance=Decimal("5.00"),
        )
        == 0
    )
    assert (
        strat.calculate_position_size(
            available_cash=Decimal("10000.00"),
            price=Decimal("0"),
            risk_amount=Decimal("100.00"),
            stop_distance=Decimal("5.00"),
        )
        == 0
    )

    # Cash constraint is tighter: cash = 500, price = 100 -> ~4 shares;
    # risk = 100, stop = 2 -> 50 shares
    qty = strat.calculate_position_size(
        available_cash=Decimal("500.00"),
        price=Decimal("100.00"),
        risk_amount=Decimal("100.00"),
        stop_distance=Decimal("2.00"),
    )
    assert qty == 4

    # Risk constraint is tighter: cash = 10000, price = 100 -> ~98 shares;
    # risk = 100, stop = 5 -> 20 shares
    qty2 = strat.calculate_position_size(
        available_cash=Decimal("10000.00"),
        price=Decimal("100.00"),
        risk_amount=Decimal("100.00"),
        stop_distance=Decimal("5.00"),
    )
    assert qty2 == 20

    # No stop distance provided (stop_distance = 0) -> fallback to cash
    qty3 = strat.calculate_position_size(
        available_cash=Decimal("1000.00"),
        price=Decimal("100.00"),
        risk_amount=Decimal("100.00"),
        stop_distance=Decimal("0.00"),
    )
    assert qty3 == 9  # 980 / 100 = 9
