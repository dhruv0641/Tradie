"""Unit tests for PaperBrokerAdapter fulfilling BrokerAdapter protocol.

Verifies:
- Protocol compliance (src.execution.broker_adapter.BrokerAdapter)
- Indian market statutory taxes and charges deduction via CostModel (BTD §6)
- Virtual cash, margin, and portfolio accounting (BRD BR-2)
- Immediate and quote-driven limit order matching with realistic slippage
- Order modification, cancellation, and position flip dynamics
"""

from decimal import Decimal

import pytest

from src.execution.broker_adapter import (
    BrokerAdapter,
    BrokerAuthenticationError,
    BrokerOrderError,
    BrokerOrderNotFoundError,
)
from src.execution.paper_adapter import PaperBrokerAdapter, PaperBrokerConfig


def test_paper_broker_protocol_runtime_check() -> None:
    """Verify PaperBrokerAdapter satisfies BrokerAdapter runtime protocol."""
    adapter = PaperBrokerAdapter()
    assert isinstance(adapter, BrokerAdapter)


def test_paper_broker_initial_state() -> None:
    """Verify initial virtual cash, zero realized P&L, and healthy connection."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(initial_cash=Decimal("10000.00")))
    assert adapter.cash == Decimal("10000.00")
    assert adapter.realized_pnl == Decimal("0.00")
    assert adapter.total_costs == Decimal("0.00")
    assert adapter.equity == Decimal("10000.00")
    assert adapter.get_positions() == []
    assert adapter.fills == []
    assert adapter.heartbeat() is True


def test_connection_toggling_and_authentication() -> None:
    """Verify heartbeat responds to connection toggling and authentication."""
    adapter = PaperBrokerAdapter()
    adapter.set_connection_alive(False)
    assert adapter.heartbeat() is False

    adapter.set_connection_alive(True)
    assert adapter.heartbeat() is True

    # Test authentication call
    assert adapter.authenticate() is True
    assert adapter.heartbeat() is True


def test_place_order_offline_or_unauthenticated_raises_error() -> None:
    """Verify placing orders fails when adapter is offline or unauthenticated."""
    adapter = PaperBrokerAdapter()
    adapter.set_connection_alive(False)

    with pytest.raises(BrokerOrderError, match="connection is offline"):
        adapter.place_order("ORD-FAIL", "RELIANCE", "BUY", 1, price=Decimal("2500.00"))

    adapter.set_connection_alive(True)
    adapter._is_authenticated = False
    with pytest.raises(BrokerAuthenticationError, match="not authenticated"):
        adapter.place_order("ORD-FAIL", "RELIANCE", "BUY", 1, price=Decimal("2500.00"))


def test_place_order_parameter_validation() -> None:
    """Verify invalid quantities, missing prices, and duplicate orders are rejected."""
    adapter = PaperBrokerAdapter()

    with pytest.raises(BrokerOrderError, match="quantity must be positive"):
        adapter.place_order("ORD-1", "RELIANCE", "BUY", 0, price=Decimal("2500.00"))

    with pytest.raises(BrokerOrderError, match="LIMIT order requires positive limit price"):
        adapter.place_order("ORD-2", "RELIANCE", "BUY", 10, order_type="LIMIT", price=None)

    with pytest.raises(BrokerOrderError, match="No market price known"):
        adapter.place_order("ORD-3", "RELIANCE", "BUY", 10, order_type="MARKET")

    # Duplicate order idempotency
    res1 = adapter.place_order("ORD-DUP", "RELIANCE", "BUY", 2, price=Decimal("2500.00"))
    assert res1.status == "FILLED"
    res2 = adapter.place_order("ORD-DUP", "RELIANCE", "BUY", 2, price=Decimal("2500.00"))
    assert res2.broker_order_id == res1.broker_order_id


def test_immediate_buy_order_fills_with_slippage_and_deducts_charges() -> None:
    """Verify immediate BUY order deducts cash, pays statutory taxes, and updates position."""
    config = PaperBrokerConfig(
        initial_cash=Decimal("10000.00"),
        slippage_bps=Decimal("10.0"),  # 0.10% slippage
        fill_mode="IMMEDIATE",
    )
    adapter = PaperBrokerAdapter(config)

    # Buy 2 shares of RELIANCE at ₹2,500
    order = adapter.place_order(
        "ORD-BUY-1",
        "RELIANCE",
        "BUY",
        2,
        order_type="LIMIT",
        price=Decimal("2500.00"),
    )

    assert order.status == "FILLED"
    assert order.client_order_id == "ORD-BUY-1"

    # Fill price = 2500 * 1.0010 = 2502.50
    # Turnover = 2 * 2502.50 = 5005.00
    fills = adapter.fills
    assert len(fills) == 1
    assert fills[0].price == Decimal("2502.50")
    assert fills[0].quantity == 2
    assert fills[0].commission > Decimal("0")

    # Cash must be reduced by turnover + commission
    total_outflow = Decimal("5005.00") + fills[0].commission
    assert adapter.cash == Decimal("10000.00") - total_outflow
    assert adapter.total_costs == fills[0].commission

    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument == "RELIANCE"
    assert positions[0].quantity == 2
    assert positions[0].average_entry_price == Decimal("2502.50")


def test_insufficient_cash_rejects_buy_order() -> None:
    """Verify BUY order exceeding virtual cash balance is rejected with BrokerOrderError."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(initial_cash=Decimal("1000.00")))

    # 10 shares of ₹2,500 = ₹25,000 > ₹1,000 cash
    with pytest.raises(BrokerOrderError, match="Insufficient virtual cash"):
        adapter.place_order("ORD-TOO-EXPENSIVE", "RELIANCE", "BUY", 10, price=Decimal("2500.00"))


def test_immediate_sell_short_order() -> None:
    """Verify SELL order on flat portfolio opens short position with cash increase."""
    config = PaperBrokerConfig(
        initial_cash=Decimal("10000.00"),
        slippage_bps=Decimal("10.0"),  # 0.10% slippage downwards on sell
        fill_mode="IMMEDIATE",
    )
    adapter = PaperBrokerAdapter(config)

    # Short 2 shares of INFY at ₹1,500
    order = adapter.place_order(
        "ORD-SHORT-1",
        "INFY",
        "SELL",
        2,
        order_type="LIMIT",
        price=Decimal("1500.00"),
    )
    assert order.status == "FILLED"

    # Fill price = 1500 * (1 - 0.0010) = 1498.50
    # Turnover = 2 * 1498.50 = 2997.00
    fills = adapter.fills
    assert fills[0].price == Decimal("1498.50")

    # Cash increases by turnover - commission
    net_inflow = Decimal("2997.00") - fills[0].commission
    assert adapter.cash == Decimal("10000.00") + net_inflow

    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument == "INFY"
    assert positions[0].quantity == -2
    assert positions[0].average_entry_price == Decimal("1498.50")


def test_position_addition_averages_entry_price() -> None:
    """Verify sequential buy orders properly weight-average the entry price."""
    config = PaperBrokerConfig(slippage_bps=Decimal("0.0"))
    adapter = PaperBrokerAdapter(config)

    adapter.place_order("B1", "TCS", "BUY", 1, price=Decimal("3000.00"))
    adapter.place_order("B2", "TCS", "BUY", 1, price=Decimal("3200.00"))

    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 2
    assert positions[0].average_entry_price == Decimal("3100.00")


def test_position_partial_exit_and_realized_pnl() -> None:
    """Verify partial and complete position exits correctly calculate realized P&L."""
    config = PaperBrokerConfig(slippage_bps=Decimal("0.0"))
    adapter = PaperBrokerAdapter(config)

    # 1. Buy 4 shares at 1000
    adapter.place_order("B1", "WIPRO", "BUY", 4, price=Decimal("1000.00"))
    # 2. Sell 2 shares at 1100 (Profit: 2 * 100 = +200)
    adapter.place_order("S1", "WIPRO", "SELL", 2, price=Decimal("1100.00"))

    pos = adapter.get_positions()[0]
    assert pos.quantity == 2
    assert pos.average_entry_price == Decimal("1000.00")
    assert pos.realized_pnl == Decimal("200.00")
    assert adapter.realized_pnl == Decimal("200.00")

    # 3. Sell remaining 2 shares at 1150 (Profit: 2 * 150 = +300)
    adapter.place_order("S2", "WIPRO", "SELL", 2, price=Decimal("1150.00"))

    pos_flat = adapter.get_positions()[0]
    assert pos_flat.quantity == 0
    assert pos_flat.realized_pnl == Decimal("500.00")
    assert adapter.realized_pnl == Decimal("500.00")


def test_position_flip_long_to_short() -> None:
    """Verify position flip from Long to Short correctly splits realized P&L and new short entry."""
    config = PaperBrokerConfig(slippage_bps=Decimal("0.0"))
    adapter = PaperBrokerAdapter(config)

    # Buy 2 shares at 1000
    adapter.place_order("B1", "HDFCBANK", "BUY", 2, price=Decimal("1000.00"))
    # Sell 5 shares at 1100 -> closes 2 Long at +200 profit, opens 3 Short at 1100
    adapter.place_order("S1", "HDFCBANK", "SELL", 5, price=Decimal("1100.00"))

    pos = adapter.get_positions()[0]
    assert pos.quantity == -3
    assert pos.average_entry_price == Decimal("1100.00")
    assert pos.realized_pnl == Decimal("200.00")
    assert adapter.realized_pnl == Decimal("200.00")


def test_position_flip_short_to_long() -> None:
    """Verify position flip from Short to Long correctly splits realized P&L and new long entry."""
    config = PaperBrokerConfig(slippage_bps=Decimal("0.0"))
    adapter = PaperBrokerAdapter(config)

    # Short 2 shares at 1500
    adapter.place_order("S1", "SBIN", "SELL", 2, price=Decimal("1500.00"))
    # Buy 5 shares at 1400 -> closes 2 Short at +200 profit, opens 3 Long at 1400
    adapter.place_order("B1", "SBIN", "BUY", 5, price=Decimal("1400.00"))

    pos = adapter.get_positions()[0]
    assert pos.quantity == 3
    assert pos.average_entry_price == Decimal("1400.00")
    assert pos.realized_pnl == Decimal("200.00")
    assert adapter.realized_pnl == Decimal("200.00")


def test_quote_driven_working_orders_and_on_tick_matching() -> None:
    """Verify QUOTE_DRIVEN mode holds limit orders and fills them upon tick updates."""
    config = PaperBrokerConfig(
        initial_cash=Decimal("10000.00"),
        slippage_bps=Decimal("0.0"),
        fill_mode="QUOTE_DRIVEN",
    )
    adapter = PaperBrokerAdapter(config)
    adapter.set_market_price("RELIANCE", Decimal("2500.00"))

    # Buy limit at 2480 (below current 2500 -> rests in book)
    buy_order = adapter.place_order("BUY-REST", "RELIANCE", "BUY", 2, price=Decimal("2480.00"))
    assert buy_order.status == "SUBMITTED"

    # Sell limit at 2520 (above current 2500 -> rests in book)
    sell_order = adapter.place_order("SELL-REST", "RELIANCE", "SELL", 1, price=Decimal("2520.00"))
    assert sell_order.status == "SUBMITTED"

    assert len(adapter.fills) == 0

    # Market moves to 2490 -> neither fills
    f1 = adapter.on_tick("RELIANCE", Decimal("2490.00"))
    assert len(f1) == 0
    assert adapter.get_order_status("BUY-REST").status == "SUBMITTED"

    # Market drops to 2475 <= 2480 -> BUY fills!
    f2 = adapter.on_tick("RELIANCE", Decimal("2475.00"))
    assert len(f2) == 1
    assert f2[0].client_order_id == "BUY-REST"
    assert adapter.get_order_status("BUY-REST").status == "FILLED"

    # Market rises to 2525 >= 2520 -> SELL fills!
    f3 = adapter.on_tick("RELIANCE", Decimal("2525.00"))
    assert len(f3) == 1
    assert f3[0].client_order_id == "SELL-REST"
    assert adapter.get_order_status("SELL-REST").status == "FILLED"


def test_market_order_with_known_price() -> None:
    """Verify MARKET orders fill immediately using latest seeded price."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(slippage_bps=Decimal("0.0")))
    adapter.set_market_price("TCS", Decimal("3500.00"))

    order = adapter.place_order("MKT-1", "TCS", "BUY", 1, order_type="MARKET")
    assert order.status == "FILLED"
    assert adapter.fills[0].price == Decimal("3500.00")


def test_order_cancellation() -> None:
    """Verify cancelling working orders succeeds and non-working returns False."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(fill_mode="QUOTE_DRIVEN"))
    adapter.set_market_price("INFY", Decimal("1500.00"))

    adapter.place_order("REST-1", "INFY", "BUY", 1, price=Decimal("1400.00"))
    assert adapter.cancel_order("REST-1") is True
    assert adapter.get_order_status("REST-1").status == "CANCELLED"

    # Second cancel returns False
    assert adapter.cancel_order("REST-1") is False
    # Non-existent returns False
    assert adapter.cancel_order("NONEXISTENT") is False


def test_order_modification() -> None:
    """Verify modifying working orders updates quantity and limit price."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(fill_mode="QUOTE_DRIVEN"))
    adapter.set_market_price("INFY", Decimal("1500.00"))

    adapter.place_order("REST-2", "INFY", "BUY", 1, price=Decimal("1400.00"))
    modified = adapter.modify_order("REST-2", quantity=3, price=Decimal("1410.00"))

    assert modified.quantity == 3
    assert modified.limit_price == Decimal("1410.00")

    with pytest.raises(BrokerOrderNotFoundError):
        adapter.modify_order("NONEXISTENT", quantity=1)

    with pytest.raises(BrokerOrderError, match="Modified quantity must be positive"):
        adapter.modify_order("REST-2", quantity=0)

    # Cancel order, then try to modify
    adapter.cancel_order("REST-2")
    with pytest.raises(BrokerOrderError, match="Cannot modify paper order"):
        adapter.modify_order("REST-2", quantity=5)


def test_get_order_status_not_found_raises() -> None:
    """Verify get_order_status raises BrokerOrderNotFoundError on unknown ID."""
    adapter = PaperBrokerAdapter()
    with pytest.raises(BrokerOrderNotFoundError):
        adapter.get_order_status("UNKNOWN")


def test_set_market_price_validation() -> None:
    """Verify set_market_price rejects zero or negative price."""
    adapter = PaperBrokerAdapter()
    with pytest.raises(ValueError, match="Price must be positive"):
        adapter.set_market_price("TEST", Decimal("0"))


def test_on_tick_validation() -> None:
    """Verify on_tick rejects zero or negative price."""
    adapter = PaperBrokerAdapter()
    with pytest.raises(ValueError, match="Tick price must be positive"):
        adapter.on_tick("TEST", Decimal("-1.00"))


def test_equity_mark_to_market_tracking() -> None:
    """Verify equity tracks mark-to-market valuations dynamically."""
    adapter = PaperBrokerAdapter(
        PaperBrokerConfig(initial_cash=Decimal("10000.00"), slippage_bps=Decimal("0.0"))
    )
    adapter.place_order("B1", "TATASTEEL", "BUY", 10, price=Decimal("100.00"))

    # Bought 10 shares at ₹100 = ₹1,000 cash out + small tax
    # Total equity should initially be ~₹10,000 (minus fees)
    initial_equity = adapter.equity
    assert initial_equity <= Decimal("10000.00")

    # Tick moves price up to ₹120 (+$20 * 10 = +$200 gain)
    adapter.on_tick("TATASTEEL", Decimal("120.00"))
    assert adapter.equity == initial_equity + Decimal("200.00")


def test_quote_driven_immediate_fill_when_price_satisfies_limit() -> None:
    """Verify limit orders fill immediately in quote-driven mode if market price is favorable."""
    adapter = PaperBrokerAdapter(
        PaperBrokerConfig(fill_mode="QUOTE_DRIVEN", slippage_bps=Decimal("0.0"))
    )
    adapter.set_market_price("INFY", Decimal("1500.00"))

    # Buy order with limit 1510 (favorable, market is 1500 <= 1510) -> fills immediately
    buy_sub = adapter.place_order("B-FAV", "INFY", "BUY", 2, price=Decimal("1510.00"))
    assert buy_sub.status == "FILLED"

    # Sell order with limit 1490 (favorable, market is 1500 >= 1490) -> fills immediately
    sell_sub = adapter.place_order("S-FAV", "INFY", "SELL", 1, price=Decimal("1490.00"))
    assert sell_sub.status == "FILLED"

    # Market order with known market price in QUOTE_DRIVEN mode fills immediately
    mkt_sub = adapter.place_order("M-FAV", "INFY", "BUY", 1, order_type="MARKET")
    assert mkt_sub.status == "FILLED"


def test_short_position_partial_exit_and_mtm() -> None:
    """Verify short position unrealized P&L mark-to-market and partial exit realized P&L."""
    adapter = PaperBrokerAdapter(PaperBrokerConfig(slippage_bps=Decimal("0.0")))

    # Open short: sell 10 shares at ₹500
    adapter.place_order("SH-1", "SBIN", "SELL", 10, price=Decimal("500.00"))
    positions = adapter.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.quantity == -10
    assert pos.average_entry_price == Decimal("500.00")

    # Mark price drops to ₹450 -> gain for short: (500 - 450) * 10 = ₹500
    adapter.on_tick("SBIN", Decimal("450.00"))
    pos = adapter.get_positions()[0]
    assert pos.unrealized_pnl == Decimal("500.00")

    # Partial buyback: buy 4 shares at ₹450 -> realized P&L = (500 - 450) * 4 = ₹200
    adapter.place_order("SH-COVER", "SBIN", "BUY", 4, price=Decimal("450.00"))
    pos = adapter.get_positions()[0]
    assert pos.quantity == -6
    assert pos.average_entry_price == Decimal("500.00")
    assert pos.realized_pnl == Decimal("200.00")


def test_on_tick_skips_fill_when_cash_insufficient() -> None:
    """Verify working buy limit order fill is skipped on tick if cash is insufficient."""
    # Start with ₹500 cash
    adapter = PaperBrokerAdapter(
        PaperBrokerConfig(
            initial_cash=Decimal("500.00"),
            fill_mode="QUOTE_DRIVEN",
            slippage_bps=Decimal("0.0"),
        )
    )
    # Place limit order: Buy 2 shares at ₹600 (needs ₹1200 > ₹500)
    # Limit is 600, no market price set yet, so it enters working book
    sub = adapter.place_order("BUY-BROKE", "EXPENSIVE", "BUY", 2, price=Decimal("600.00"))
    assert sub.status == "SUBMITTED"

    # Tick arrives at ₹590 (satisfies limit <= 600, but cash ₹500 is < ₹1180)
    fills = adapter.on_tick("EXPENSIVE", Decimal("590.00"))
    assert len(fills) == 0

    # Order should remain SUBMITTED
    order_status = adapter.get_order_status("BUY-BROKE")
    assert order_status.status == "SUBMITTED"


def test_quote_driven_unpriced_market_order_and_unfavorable_limits() -> None:
    """Verify market orders wait for first tick, and unfavorable limits remain working."""
    adapter = PaperBrokerAdapter(
        PaperBrokerConfig(fill_mode="QUOTE_DRIVEN", slippage_bps=Decimal("0.0"))
    )

    # 1. Market order placed before any tick
    mkt_sub = adapter.place_order("MKT-WAIT", "WIPRO", "BUY", 5, order_type="MARKET")
    assert mkt_sub.status == "SUBMITTED"

    # 2. Limit orders placed when market price is known but unfavorable
    adapter.set_market_price("WIPRO", Decimal("400.00"))

    # Buy limit 390 (market is 400 > 390, unfavorable) -> remains SUBMITTED
    unfav_buy = adapter.place_order("BUY-UNFAV", "WIPRO", "BUY", 2, price=Decimal("390.00"))
    assert unfav_buy.status == "SUBMITTED"

    # Sell limit 410 (market is 400 < 410, unfavorable) -> remains SUBMITTED
    unfav_sell = adapter.place_order("SELL-UNFAV", "WIPRO", "SELL", 2, price=Decimal("410.00"))
    assert unfav_sell.status == "SUBMITTED"

    # Now tick arrives at ₹395:
    # - MKT-WAIT should fill at 395
    # - BUY-UNFAV (390) does not fill (395 > 390)
    # - SELL-UNFAV (410) does not fill (395 < 410)
    fills = adapter.on_tick("WIPRO", Decimal("395.00"))
    assert len(fills) == 1
    assert fills[0].client_order_id == "MKT-WAIT"
    assert fills[0].price == Decimal("395.00")
