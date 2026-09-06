"""Unit tests for bid-ask spread and liquidity-scaled slippage model (PRD FR-25, BTD §6.1)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.backtesting.slippage_model import SlippageConfig, SlippageModel


def test_slippage_model_initialization_and_config() -> None:
    """Test SlippageModel initialization with default and custom configurations."""
    model = SlippageModel()
    assert model.config.base_slippage_bps == 5.0
    assert model.config.tier1_threshold == 0.01
    assert model.config.tier2_threshold == 0.05
    assert model.config.reject_above_tier2 is True

    custom = SlippageConfig(base_slippage_bps=10.0, reject_above_tier2=False)
    custom_model = SlippageModel(config=custom)
    assert custom_model.config.base_slippage_bps == 10.0
    assert custom_model.config.reject_above_tier2 is False


def test_adverse_execution_drag_buy_and_sell() -> None:
    """Test that spread and slippage apply adversely (BUY > requested, SELL < requested)."""
    model = SlippageModel()

    # BUY 100 shares @ ₹100.00 with 100,000 bar volume (0.1% volume -> Tier 1: 1x multiplier)
    # Spread proxy: 0.05% of 100 = 0.05. Half spread = 0.025 -> 0.03
    # Slippage: 5 bps = 0.05% of 100 = 0.05
    buy_result = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=100,
        side="BUY",
        bar_volume=100_000.0,
    )
    assert buy_result.rejected is False
    assert buy_result.executed_price > buy_result.requested_price
    assert buy_result.multiplier == 1.0
    assert buy_result.spread_drag > Decimal("0.00")
    assert buy_result.slippage_drag > Decimal("0.00")
    assert buy_result.executed_price == buy_result.requested_price + buy_result.total_price_impact

    # SELL 100 shares @ ₹100.00
    sell_result = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=100,
        side="SELL",
        bar_volume=100_000.0,
    )
    assert sell_result.rejected is False
    assert sell_result.executed_price < sell_result.requested_price
    assert (
        sell_result.executed_price == sell_result.requested_price - sell_result.total_price_impact
    )


def test_explicit_bid_ask_spread() -> None:
    """Test slippage calculation when explicit bid-ask spread is provided."""
    model = SlippageModel()

    # Quoted bid-ask spread = ₹0.50. Half spread = ₹0.25
    res = model.calculate_slippage(
        requested_price=Decimal("500.00"),
        quantity=50,
        side="BUY",
        bar_volume=50_000.0,
        bid_ask_spread=Decimal("0.50"),
    )
    assert res.spread_drag == Decimal("0.25")


def test_liquidity_scaling_tiers() -> None:
    """Test the three liquidity scaling tiers (1x for <1%, 2x for 1-5%, 4x for >5%)."""
    # Disable rejection to test 4x multiplier
    model = SlippageModel(config=SlippageConfig(reject_above_tier2=False))
    bar_vol = 10_000.0

    # Tier 1: 50 shares / 10,000 = 0.5% (< 1%) -> 1x multiplier
    t1 = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=50,
        side="BUY",
        bar_volume=bar_vol,
    )
    assert t1.multiplier == 1.0
    assert t1.effective_slippage_bps == 5.0
    assert t1.rejected is False

    # Tier 2: 300 shares / 10,000 = 3% (1%-5%) -> 2x multiplier
    t2 = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=300,
        side="BUY",
        bar_volume=bar_vol,
    )
    assert t2.multiplier == 2.0
    assert t2.effective_slippage_bps == 10.0
    assert t2.rejected is False

    # Tier 3: 800 shares / 10,000 = 8% (> 5%) -> 4x multiplier
    t3 = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=800,
        side="BUY",
        bar_volume=bar_vol,
    )
    assert t3.multiplier == 4.0
    assert t3.effective_slippage_bps == 20.0
    assert t3.rejected is False


def test_excessive_order_volume_rejection() -> None:
    """Test that orders exceeding 5% volume are rejected when reject_above_tier2=True (BTD §6.1)."""
    model = SlippageModel(config=SlippageConfig(reject_above_tier2=True))

    # 600 shares / 10,000 = 6% (> 5%)
    res = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=600,
        side="BUY",
        bar_volume=10_000.0,
    )
    assert res.rejected is True
    assert res.rejection_reason == "EXCESSIVE_VOLUME_SHARE"
    # When rejected, price remains requested price
    assert res.executed_price == Decimal("100.00")


def test_zero_bar_volume_handling() -> None:
    """Test handling of illiquid zero-volume bars."""
    model = SlippageModel()

    res = model.calculate_slippage(
        requested_price=Decimal("100.00"),
        quantity=10,
        side="BUY",
        bar_volume=0.0,
    )
    assert res.rejected is True
    assert res.rejection_reason == "ZERO_BAR_VOLUME"


def test_sell_price_floor() -> None:
    """Test that sell executed price does not drop below ₹0.01 even with extreme slippage."""
    model = SlippageModel(
        config=SlippageConfig(base_slippage_bps=50000.0, reject_above_tier2=False)
    )

    res = model.calculate_slippage(
        requested_price=Decimal("0.05"),
        quantity=10,
        side="SELL",
        bar_volume=100.0,
    )
    assert res.executed_price >= Decimal("0.01")


def test_validation_errors() -> None:
    """Test validation errors on non-positive price or quantity."""
    model = SlippageModel()

    with pytest.raises(ValueError, match="requested_price must be positive"):
        model.calculate_slippage(Decimal("0.00"), 10, "BUY", 1000.0)

    with pytest.raises(ValueError, match="requested_price must be positive"):
        model.calculate_slippage(Decimal("-50.00"), 10, "BUY", 1000.0)

    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        model.calculate_slippage(Decimal("100.00"), 0, "BUY", 1000.0)

    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        model.calculate_slippage(Decimal("100.00"), -10, "BUY", 1000.0)


def test_domain_immutability() -> None:
    """Test that SlippageResult is strictly frozen."""
    model = SlippageModel()
    res = model.calculate_slippage(Decimal("100.00"), 10, "BUY", 1000.0)

    with pytest.raises(ValidationError):
        res.executed_price = Decimal("200.00")
