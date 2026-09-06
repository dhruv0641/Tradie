"""Comprehensive unit tests for PositionLedger mark-to-market accounting engine."""

from datetime import UTC, datetime
from decimal import Decimal
from threading import Thread
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.capital_state import CapitalState
from src.domain.execution import OrderFill
from src.execution.position_ledger import PositionLedger, PositionLedgerProtocol
from src.infrastructure.models import PositionModel


@pytest.fixture
def ledger() -> PositionLedger:
    """Provide a fresh PositionLedger initialized with ₹10,000."""
    return PositionLedger(initial_capital=Decimal("10000.00"))


def make_fill(
    fill_id: str,
    instrument: str,
    direction: str,
    quantity: int,
    price: str,
    *,
    commission: str = "0.00",
    client_order_id: str = "order-1",
    timestamp: datetime | None = None,
) -> OrderFill:
    """Helper to construct validated OrderFill events."""
    ts = timestamp or datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
    return OrderFill(
        fill_id=fill_id,
        client_order_id=client_order_id,
        instrument=instrument,
        direction=direction,  # type: ignore[arg-type]
        quantity=quantity,
        price=Decimal(price),
        commission=Decimal(commission),
        timestamp=ts,
    )


def test_protocol_conformance(ledger: PositionLedger) -> None:
    """Verify PositionLedger satisfies PositionLedgerProtocol."""
    assert isinstance(ledger, PositionLedgerProtocol)


def test_initialization_default_and_custom() -> None:
    """Verify initialization states and parameter validation."""
    l_def = PositionLedger()
    assert l_def.initial_capital == Decimal("10000.00")
    assert l_def.session_start_capital == Decimal("10000.00")
    assert l_def.cash == Decimal("10000.00")
    assert l_def.total_equity == Decimal("10000.00")
    assert l_def.peak_equity == Decimal("10000.00")
    assert l_def.realized_pnl == Decimal("0.00")
    assert l_def.unrealized_pnl == Decimal("0.00")
    assert l_def.cumulative_fees == Decimal("0.00")
    assert l_def.trades_today == 0
    assert len(l_def.get_open_positions()) == 0

    l_custom = PositionLedger(
        initial_capital=Decimal("50000.00"),
        session_start_capital=Decimal("48000.00"),
    )
    assert l_custom.initial_capital == Decimal("50000.00")
    assert l_custom.session_start_capital == Decimal("48000.00")
    assert l_custom.cash == Decimal("50000.00")

    with pytest.raises(ValueError, match="Initial capital must be positive"):
        PositionLedger(initial_capital=Decimal("0.00"))

    with pytest.raises(ValueError, match="Initial capital must be positive"):
        PositionLedger(initial_capital=Decimal("-100.00"))


def test_long_position_open_from_flat(ledger: PositionLedger) -> None:
    """Verify opening a long position from flat."""
    fill = make_fill("f1", "RELIANCE", "BUY", 10, "2000.00", commission="20.00")
    pos = ledger.apply_fill(fill)

    assert pos.instrument == "RELIANCE"
    assert pos.quantity == 10
    assert pos.average_entry_price == Decimal("2000.00")
    assert pos.current_market_price == Decimal("2000.00")
    assert pos.unrealized_pnl == Decimal("0.00")
    assert pos.realized_pnl == Decimal("0.00")
    assert pos.peak_unrealized_pnl == Decimal("0.00")

    # Cash = 10,000 - (10 * 2,000) - 20 = -10,020 (unleveraged check)
    assert ledger.cash == Decimal("10000.00") - Decimal("20000.00") - Decimal("20.00")
    assert ledger.cumulative_fees == Decimal("20.00")
    assert ledger.total_equity == Decimal("10000.00") - Decimal("20.00")
    assert ledger.trades_today == 0

    queried = ledger.get_position("RELIANCE")
    assert queried is not None
    assert queried.quantity == 10


def test_long_position_multi_leg_averaging(ledger: PositionLedger) -> None:
    """Verify adding to an existing long position computes weighted average entry."""
    # Leg 1: 10 shares @ ₹100
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    # Leg 2: 10 shares @ ₹120
    pos2 = ledger.apply_fill(make_fill("f2", "TCS", "BUY", 10, "120.00"))

    assert pos2.quantity == 20
    # Expected weighted average: (10 * 100 + 10 * 120) / 20 = 2200 / 20 = 110.00
    assert pos2.average_entry_price == Decimal("110.00")
    assert pos2.current_market_price == Decimal("120.00")
    # Unrealized = 20 * (120 - 110) = 200.00
    assert pos2.unrealized_pnl == Decimal("200.00")
    assert pos2.peak_unrealized_pnl == Decimal("200.00")
    assert ledger.unrealized_pnl == Decimal("200.00")


def test_long_position_partial_close(ledger: PositionLedger) -> None:
    """Verify partial close preserves entry price for remaining shares and records realized P&L."""
    ledger.apply_fill(make_fill("f1", "INFY", "BUY", 20, "100.00"))
    # Sell 8 shares @ ₹130
    pos = ledger.apply_fill(make_fill("f2", "INFY", "SELL", 8, "130.00", commission="5.00"))

    assert pos.quantity == 12
    # Average entry remains 100.00
    assert pos.average_entry_price == Decimal("100.00")
    assert pos.current_market_price == Decimal("130.00")
    # Realized P&L on 8 shares = 8 * (130 - 100) = 240.00
    assert pos.realized_pnl == Decimal("240.00")
    assert ledger.realized_pnl == Decimal("240.00")
    # Unrealized P&L on remaining 12 shares = 12 * (130 - 100) = 360.00
    assert pos.unrealized_pnl == Decimal("360.00")
    assert ledger.trades_today == 1
    assert ledger.cumulative_fees == Decimal("5.00")


def test_long_position_full_close(ledger: PositionLedger) -> None:
    """Verify full close zeroes quantity and updates cumulative realized P&L."""
    ledger.apply_fill(make_fill("f1", "INFY", "BUY", 10, "100.00"))
    pos = ledger.apply_fill(make_fill("f2", "INFY", "SELL", 10, "125.00"))

    assert pos.quantity == 0
    assert pos.average_entry_price == Decimal("0.00")
    assert pos.unrealized_pnl == Decimal("0.00")
    assert pos.realized_pnl == Decimal("250.00")
    assert ledger.realized_pnl == Decimal("250.00")
    assert ledger.unrealized_pnl == Decimal("0.00")
    assert len(ledger.get_open_positions()) == 0
    assert len(ledger.get_all_positions()) == 1
    assert ledger.trades_today == 1


def test_short_position_lifecycle(ledger: PositionLedger) -> None:
    """Verify complete short position lifecycle (open, add, partial cover, full cover)."""
    # 1. Open Short: Sell 10 @ ₹200
    p1 = ledger.apply_fill(make_fill("f1", "SBIN", "SELL", 10, "200.00"))
    assert p1.quantity == -10
    assert p1.average_entry_price == Decimal("200.00")
    assert ledger.cash == Decimal("10000.00") + Decimal("2000.00")

    # 2. Add to Short: Sell 10 @ ₹220
    p2 = ledger.apply_fill(make_fill("f2", "SBIN", "SELL", 10, "220.00"))
    assert p2.quantity == -20
    # Average entry: (10 * 200 + 10 * 220) / 20 = 210.00
    assert p2.average_entry_price == Decimal("210.00")

    # 3. Partial Cover: Buy 8 @ ₹190
    p3 = ledger.apply_fill(make_fill("f3", "SBIN", "BUY", 8, "190.00"))
    assert p3.quantity == -12
    assert p3.average_entry_price == Decimal("210.00")
    # Realized on short = 8 * (210 - 190) = 160.00
    assert p3.realized_pnl == Decimal("160.00")
    assert ledger.realized_pnl == Decimal("160.00")
    # Unrealized on remaining 12 short = 12 * (210 - 190) = 240.00
    assert p3.unrealized_pnl == Decimal("240.00")
    assert ledger.trades_today == 1

    # 4. Full Cover: Buy 12 @ ₹180
    p4 = ledger.apply_fill(make_fill("f4", "SBIN", "BUY", 12, "180.00"))
    assert p4.quantity == 0
    assert p4.average_entry_price == Decimal("0.00")
    # Realized on final leg = 12 * (210 - 180) = 360.00; Total = 160 + 360 = 520.00
    assert p4.realized_pnl == Decimal("520.00")
    assert ledger.realized_pnl == Decimal("520.00")
    assert ledger.unrealized_pnl == Decimal("0.00")
    assert ledger.trades_today == 2


def test_position_flip_long_to_short(ledger: PositionLedger) -> None:
    """Verify oversized sell flips position from long to short in a single fill."""
    # Long 10 @ ₹100
    ledger.apply_fill(make_fill("f1", "WIPRO", "BUY", 10, "100.00"))
    # Sell 15 @ ₹120 (oversized by 5)
    pos = ledger.apply_fill(make_fill("f2", "WIPRO", "SELL", 15, "120.00"))

    # Closed 10 with realized P&L: 10 * (120 - 100) = 200.00
    assert pos.realized_pnl == Decimal("200.00")
    assert ledger.realized_pnl == Decimal("200.00")
    # New short position: -5 @ ₹120
    assert pos.quantity == -5
    assert pos.average_entry_price == Decimal("120.00")
    assert pos.unrealized_pnl == Decimal("0.00")
    assert ledger.trades_today == 1


def test_position_flip_short_to_long(ledger: PositionLedger) -> None:
    """Verify oversized buy flips position from short to long in a single fill."""
    # Short 10 @ ₹200
    ledger.apply_fill(make_fill("f1", "HDFC", "SELL", 10, "200.00"))
    # Buy 15 @ ₹180 (oversized by 5)
    pos = ledger.apply_fill(make_fill("f2", "HDFC", "BUY", 15, "180.00"))

    # Closed 10 with realized P&L on short: 10 * (200 - 180) = 200.00
    assert pos.realized_pnl == Decimal("200.00")
    assert ledger.realized_pnl == Decimal("200.00")
    # New long position: +5 @ ₹180
    assert pos.quantity == 5
    assert pos.average_entry_price == Decimal("180.00")
    assert pos.unrealized_pnl == Decimal("0.00")
    assert ledger.trades_today == 1


def test_mark_to_market_price_updates(ledger: PositionLedger) -> None:
    """Verify mark_to_market updates prices, unrealized P&L, and peak values."""
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    ledger.apply_fill(make_fill("f2", "INFY", "SELL", 5, "200.00"))

    # Price rise: TCS -> 110 (gain), INFY -> 210 (loss)
    ledger.mark_to_market({"TCS": Decimal("110.00"), "INFY": Decimal("210.00")})

    tcs = ledger.get_position("TCS")
    assert tcs is not None
    assert tcs.current_market_price == Decimal("110.00")
    assert tcs.unrealized_pnl == Decimal("100.00")
    assert tcs.peak_unrealized_pnl == Decimal("100.00")

    infy = ledger.get_position("INFY")
    assert infy is not None
    assert infy.current_market_price == Decimal("210.00")
    # Short unrealized: 5 * (200 - 210) = -50.00
    assert infy.unrealized_pnl == Decimal("-50.00")

    assert ledger.unrealized_pnl == Decimal("50.00")

    # Single instrument update with string
    ledger.mark_to_market("TCS", Decimal("130.00"))
    tcs2 = ledger.get_position("TCS")
    assert tcs2 is not None
    assert tcs2.unrealized_pnl == Decimal("300.00")
    assert tcs2.peak_unrealized_pnl == Decimal("300.00")

    # Negative price validation
    with pytest.raises(ValueError, match="Market price must be positive"):
        ledger.mark_to_market("TCS", Decimal("-10.00"))

    with pytest.raises(ValueError, match="Price must be provided"):
        ledger.mark_to_market("TCS", None)


def test_peak_equity_tracking(ledger: PositionLedger) -> None:
    """Verify peak equity tracks highest portfolio equity monotonically."""
    assert ledger.peak_equity == Decimal("10000.00")

    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    # Price surges to 150 -> equity = 10,000 + 500 = 10,500
    ledger.mark_to_market("TCS", Decimal("150.00"))
    assert ledger.total_equity == Decimal("10500.00")
    assert ledger.peak_equity == Decimal("10500.00")

    # Price drops to 80 -> equity = 10,000 - 200 = 9,800; peak remains 10,500
    ledger.mark_to_market("TCS", Decimal("80.00"))
    assert ledger.total_equity == Decimal("9800.00")
    assert ledger.peak_equity == Decimal("10500.00")


def test_get_capital_state_derivation(ledger: PositionLedger) -> None:
    """Verify get_capital_state derives valid CapitalState satisfying all invariants."""
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    ledger.apply_fill(make_fill("f2", "INFY", "BUY", 5, "200.00"))
    ledger.mark_to_market({"TCS": Decimal("110.00"), "INFY": Decimal("220.00")})

    cap = ledger.get_capital_state()
    assert isinstance(cap, CapitalState)
    assert cap.open_position_count == 2
    assert cap.session_start_capital == Decimal("10000.00")
    # Deployed = 10 * 110 + 5 * 220 = 1100 + 1100 = 2200.00
    assert cap.currently_deployed == Decimal("2200.00")
    assert cap.currently_deployed <= cap.current_capital
    assert cap.current_capital == ledger.total_equity


def test_session_reset(ledger: PositionLedger) -> None:
    """Verify session reset updates start capital and resets trade counter."""
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    ledger.apply_fill(make_fill("f2", "TCS", "SELL", 10, "150.00"))

    assert ledger.trades_today == 1
    assert ledger.total_equity == Decimal("10500.00")

    ledger.reset_session()
    assert ledger.trades_today == 0
    assert ledger.session_start_capital == Decimal("10500.00")

    # Explicit override
    ledger.reset_session(Decimal("12000.00"))
    assert ledger.session_start_capital == Decimal("12000.00")


def test_thread_concurrency_safety(ledger: PositionLedger) -> None:
    """Verify thread safety when concurrent fills and mark-to-market events execute."""
    errors: list[Exception] = []

    def run_fills() -> None:
        try:
            for i in range(25):
                ledger.apply_fill(make_fill(f"f_{i}", "TCS", "BUY", 1, "100.00"))
                ledger.apply_fill(make_fill(f"fc_{i}", "TCS", "SELL", 1, "105.00"))
        except Exception as e:
            errors.append(e)

    def run_mtm() -> None:
        try:
            for i in range(50):
                ledger.mark_to_market("TCS", Decimal("100.00") + Decimal(i % 10))
        except Exception as e:
            errors.append(e)

    t1 = Thread(target=run_fills)
    t2 = Thread(target=run_mtm)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
    assert ledger.trades_today == 25
    pos = ledger.get_position("TCS")
    assert pos is not None
    assert pos.quantity == 0


@pytest.mark.anyio
async def test_transactional_db_persistence_new_position(ledger: PositionLedger) -> None:
    """Verify atomic DB persistence when inserting a new position into DB."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    fill = make_fill("f1", "RELIANCE", "BUY", 10, "2500.00")
    pos = await ledger.record_fill_transactional(fill, mock_session)

    assert pos.quantity == 10
    assert pos.average_entry_price == Decimal("2500.00")
    mock_session.add.assert_called_once()
    added_model = mock_session.add.call_args[0][0]
    assert isinstance(added_model, PositionModel)
    assert added_model.instrument == "RELIANCE"
    assert added_model.quantity == 10
    assert added_model.average_entry_price == Decimal("2500.00")
    mock_session.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_transactional_db_persistence_existing_position(ledger: PositionLedger) -> None:
    """Verify atomic DB persistence when updating an existing DB position."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    existing_db_pos = PositionModel(
        instrument="TCS",
        quantity=10,
        average_entry_price=Decimal("100.00"),
        current_market_price=Decimal("100.00"),
        unrealized_pnl=Decimal("0.00"),
        realized_pnl=Decimal("0.00"),
        peak_unrealized_pnl=Decimal("0.00"),
        opened_at=datetime(2026, 9, 6, 9, 15, tzinfo=UTC),
        last_updated_at=datetime(2026, 9, 6, 9, 15, tzinfo=UTC),
    )
    mock_result.scalar_one_or_none.return_value = existing_db_pos
    mock_session.execute.return_value = mock_result

    # First fill
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))
    # Second fill via transactional persistence (adding 10 @ 120)
    fill2 = make_fill("f2", "TCS", "BUY", 10, "120.00")
    pos2 = await ledger.record_fill_transactional(fill2, mock_session)

    assert pos2.quantity == 20
    assert pos2.average_entry_price == Decimal("110.00")
    # Verify existing DB model updated in-place
    assert existing_db_pos.quantity == 20
    assert existing_db_pos.average_entry_price == Decimal("110.00")
    mock_session.add.assert_not_called()
    mock_session.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_transactional_db_failure_in_memory_rollback(ledger: PositionLedger) -> None:
    """Verify atomic in-memory rollback when database persistence fails (TRD-DATA-2)."""
    # Establish initial state
    ledger.apply_fill(make_fill("f1", "INFY", "BUY", 10, "100.00"))
    cash_before = ledger.cash
    equity_before = ledger.total_equity

    # Mock failing session
    mock_session = AsyncMock()
    mock_session.execute.side_effect = RuntimeError("Simulated DB connection failure")

    failing_fill = make_fill("f2", "INFY", "BUY", 10, "150.00")

    with pytest.raises(RuntimeError, match="Simulated DB connection failure"):
        await ledger.record_fill_transactional(failing_fill, mock_session)

    # In-memory state must be completely untouched/restored
    assert ledger.cash == cash_before
    assert ledger.total_equity == equity_before
    infy_pos = ledger.get_position("INFY")
    assert infy_pos is not None
    assert infy_pos.quantity == 10  # not 20!
    assert infy_pos.average_entry_price == Decimal("100.00")


def test_mark_to_market_naive_datetime_and_untracked_symbol(ledger: PositionLedger) -> None:
    """Verify mark_to_market handles naive datetime conversion and untracked symbols gracefully."""
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 10, "100.00"))

    naive_ts = datetime(2026, 9, 6, 10, 0, 0)  # No tzinfo
    # Mark untracked symbol and tracked symbol
    ledger.mark_to_market(
        {"TCS": Decimal("105.00"), "UNTRACKED": Decimal("500.00")},
        timestamp=naive_ts,
    )

    tcs = ledger.get_position("TCS")
    assert tcs is not None
    assert tcs.updated_at.tzinfo == UTC
    assert tcs.current_market_price == Decimal("105.00")
    assert ledger.get_position("UNTRACKED") is None


def test_capital_state_deployed_clamping(ledger: PositionLedger) -> None:
    """Verify deployed capital is defensively clamped if deployed exceeds current capital."""
    # Open position with 90% capital and ₹100 commission
    ledger.apply_fill(make_fill("f1", "TCS", "BUY", 90, "100.00", commission="100.00"))
    # Incur heavy loss of ₹990
    ledger.apply_fill(make_fill("f2", "LOSS_STOCK", "BUY", 10, "100.00"))
    ledger.apply_fill(make_fill("f3", "LOSS_STOCK", "SELL", 10, "1.00"))

    # Net cash is -90. TCS value at 105 is 9,450.
    # Total equity is 9,450 - 90 = 9,360.
    # Deployed gross value is 9,450, which exceeds total equity 9,360.
    ledger.mark_to_market("TCS", Decimal("105.00"))
    cap = ledger.get_capital_state()
    assert cap.currently_deployed <= cap.current_capital
    assert cap.currently_deployed == cap.current_capital
    assert cap.currently_deployed == Decimal("9360.00")
