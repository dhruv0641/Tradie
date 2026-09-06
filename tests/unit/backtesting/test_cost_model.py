"""Unit tests for Indian statutory charges and brokerage cost model (PRD FR-25, BTD §6)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.backtesting.cost_model import CostModel, CostModelConfig


def test_cost_model_initialization_and_config() -> None:
    """Test CostModel initialization with default and custom configurations."""
    model = CostModel()
    assert model.config.flat_brokerage_cap == Decimal("20.00")
    assert model.config.brokerage_pct == Decimal("0.0003")
    assert model.config.gst_rate == Decimal("0.18")

    custom_config = CostModelConfig(
        flat_brokerage_cap=Decimal("15.00"),
        brokerage_pct=Decimal("0.0002"),
    )
    custom_model = CostModel(config=custom_config)
    assert custom_model.config.flat_brokerage_cap == Decimal("15.00")


def test_worked_contract_note_2000_intraday() -> None:
    """Test worked contract note for ₹2,000 intraday order (BTD §6 validation fixture).

    Trade: BUY 10 shares @ ₹200.00, SELL 10 shares @ ₹200.00
    Turnover per leg = ₹2,000.00.
    """
    model = CostModel()

    # 1. BUY leg
    buy = model.calculate_leg(
        price=Decimal("200.00"),
        quantity=10,
        side="BUY",
        product_type="INTRADAY",
    )
    assert buy.turnover == Decimal("2000.00")
    # min(20, 2000 * 0.0003) = 0.60
    assert buy.brokerage == Decimal("0.60")
    # STT on intraday BUY is 0
    assert buy.stt == Decimal("0.00")
    # Exchange: 2000 * 0.0000297 = 0.06
    assert buy.exchange_charges == Decimal("0.06")
    # SEBI: 2000 * 0.000001 = 0.002 -> 0.00
    assert buy.sebi_charges == Decimal("0.00")
    # Stamp: 2000 * 0.00003 = 0.06
    assert buy.stamp_duty == Decimal("0.06")
    # GST: 18% of (0.60 + 0.06) = 0.1188 -> 0.12
    assert buy.gst == Decimal("0.12")
    assert buy.total_cost == Decimal("0.84")

    # 2. SELL leg
    sell = model.calculate_leg(
        price=Decimal("200.00"),
        quantity=10,
        side="SELL",
        product_type="INTRADAY",
    )
    assert sell.brokerage == Decimal("0.60")
    # STT on intraday SELL: 2000 * 0.00025 = 0.50
    assert sell.stt == Decimal("0.50")
    assert sell.exchange_charges == Decimal("0.06")
    assert sell.sebi_charges == Decimal("0.00")
    # Stamp duty on SELL is 0
    assert sell.stamp_duty == Decimal("0.00")
    assert sell.gst == Decimal("0.12")
    assert sell.total_cost == Decimal("1.28")

    # Round trip
    rt = model.calculate_round_trip(
        entry_price=Decimal("200.00"),
        exit_price=Decimal("200.00"),
        quantity=10,
        product_type="INTRADAY",
    )
    assert rt.total_turnover == Decimal("4000.00")
    assert rt.total_brokerage == Decimal("1.20")
    assert rt.total_statutory_charges == Decimal("0.92")
    assert rt.total_cost == Decimal("2.12")
    assert rt.gross_pnl == Decimal("0.00")
    assert rt.net_pnl == Decimal("-2.12")
    # Breakeven diff: 2.12 / 10 = 0.212 -> 0.21 per share
    assert rt.breakeven_price_diff == Decimal("0.21")


def test_worked_contract_note_10000_intraday() -> None:
    """Test worked contract note for ₹10,000 intraday order (system initial capital scale).

    Trade: BUY 50 shares @ ₹200.00, SELL 50 shares @ ₹205.00
    """
    model = CostModel()

    rt = model.calculate_round_trip(
        entry_price=Decimal("200.00"),
        exit_price=Decimal("205.00"),
        quantity=50,
        product_type="INTRADAY",
    )
    assert rt.entry_cost.turnover == Decimal("10000.00")
    assert rt.exit_cost.turnover == Decimal("10250.00")
    # Entry brokerage: 10000 * 0.0003 = 3.00
    assert rt.entry_cost.brokerage == Decimal("3.00")
    # Exit brokerage: 10250 * 0.0003 = 3.075 -> 3.08
    assert rt.exit_cost.brokerage == Decimal("3.08")
    # Exit STT: 10250 * 0.00025 = 2.5625 -> 2.56
    assert rt.exit_cost.stt == Decimal("2.56")
    # Gross PnL: 50 * 5 = 250.00
    assert rt.gross_pnl == Decimal("250.00")
    # Net PnL must account for all costs
    assert rt.net_pnl < rt.gross_pnl
    assert rt.net_pnl == rt.gross_pnl - rt.total_cost


def test_worked_contract_note_100000_brokerage_cap() -> None:
    """Test worked contract note for ₹100,000 order asserting ₹20 flat brokerage cap (BTD-1).

    Turnover: 100 shares @ ₹1,000.00 = ₹100,000.00.
    0.03% = ₹30.00, must be capped at ₹20.00 flat!
    """
    model = CostModel()

    buy = model.calculate_leg(
        price=Decimal("1000.00"),
        quantity=100,
        side="BUY",
        product_type="INTRADAY",
    )
    assert buy.turnover == Decimal("100000.00")
    # Brokerage capped at ₹20.00 flat
    assert buy.brokerage == Decimal("20.00")
    # Exchange: 100000 * 0.0000297 = 2.97
    assert buy.exchange_charges == Decimal("2.97")
    # SEBI: 100000 * 0.000001 = 0.10
    assert buy.sebi_charges == Decimal("0.10")
    # Stamp: 100000 * 0.00003 = 3.00
    assert buy.stamp_duty == Decimal("3.00")
    # GST: 18% of (20.00 + 2.97) = 18% of 22.97 = 4.1346 -> 4.13
    assert buy.gst == Decimal("4.13")
    assert buy.total_cost == Decimal("30.20")

    sell = model.calculate_leg(
        price=Decimal("1000.00"),
        quantity=100,
        side="SELL",
        product_type="INTRADAY",
    )
    assert sell.brokerage == Decimal("20.00")
    # STT: 100000 * 0.00025 = 25.00
    assert sell.stt == Decimal("25.00")
    assert sell.exchange_charges == Decimal("2.97")
    assert sell.sebi_charges == Decimal("0.10")
    assert sell.stamp_duty == Decimal("0.00")
    assert sell.gst == Decimal("4.13")
    assert sell.total_cost == Decimal("52.20")


def test_delivery_product_type_costs() -> None:
    """Test equity delivery transaction costs (STT on both legs, 0.015% stamp duty)."""
    model = CostModel()

    buy = model.calculate_leg(
        price=Decimal("500.00"),
        quantity=20,
        side="BUY",
        product_type="DELIVERY",
    )
    # Turnover: 10,000
    # Delivery STT on BUY: 10,000 * 0.0010 = 10.00
    assert buy.stt == Decimal("10.00")
    # Delivery Stamp duty on BUY: 10,000 * 0.00015 = 1.50
    assert buy.stamp_duty == Decimal("1.50")

    sell = model.calculate_leg(
        price=Decimal("500.00"),
        quantity=20,
        side="SELL",
        product_type="DELIVERY",
    )
    # Delivery STT on SELL: 10,000 * 0.0010 = 10.00
    assert sell.stt == Decimal("10.00")
    # Stamp duty on SELL is 0
    assert sell.stamp_duty == Decimal("0.00")


def test_stt_rupee_rounding_toggle() -> None:
    """Test that stt_round_to_rupee config correctly rounds STT to nearest integer."""
    config_rounded = CostModelConfig(stt_round_to_rupee=True)
    model = CostModel(config=config_rounded)

    # Turnover ₹2,000 intraday sell: raw STT is 0.50, rounded to nearest rupee = 1.00
    sell = model.calculate_leg(
        price=Decimal("200.00"),
        quantity=10,
        side="SELL",
        product_type="INTRADAY",
    )
    assert sell.stt == Decimal("1")


def test_validation_errors() -> None:
    """Test error handling for non-positive price or quantity."""
    model = CostModel()

    with pytest.raises(ValueError, match="Price must be positive"):
        model.calculate_leg(Decimal("0.00"), 10, "BUY")

    with pytest.raises(ValueError, match="Price must be positive"):
        model.calculate_leg(Decimal("-10.00"), 10, "BUY")

    with pytest.raises(ValueError, match="Quantity must be greater than zero"):
        model.calculate_leg(Decimal("100.00"), 0, "BUY")

    with pytest.raises(ValueError, match="Quantity must be greater than zero"):
        model.calculate_leg(Decimal("100.00"), -5, "BUY")


def test_domain_immutability() -> None:
    """Test that CostBreakdown and RoundTripCostBreakdown are strictly frozen."""
    model = CostModel()
    breakdown = model.calculate_leg(Decimal("100.00"), 10, "BUY")

    with pytest.raises(ValidationError):
        breakdown.brokerage = Decimal("0.00")

    rt = model.calculate_round_trip(Decimal("100.00"), Decimal("105.00"), 10)
    with pytest.raises(ValidationError):
        rt.net_pnl = Decimal("1000.00")
