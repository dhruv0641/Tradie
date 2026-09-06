"""Unit tests for PositionSizer enforcing RTLD §6 multi-constraint fixed-fractional sizing."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from src.domain.risk import CandidateTrade, CapitalState, MarketState, StreakState
from src.risk.config import RiskConfig
from src.risk.sizer import PositionSizer, SizingResult


def _utc_now() -> datetime:
    return datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def _make_candidate(
    entry: str = "250.00",
    stop: str = "240.00",
    direction: Literal["BUY", "SELL"] = "BUY",
    instrument: str = "RELIANCE",
) -> CandidateTrade:
    return CandidateTrade(
        instrument=instrument,
        direction=direction,
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        timeframe="15m",
        trade_quality_score=0.85,
        expected_value=Decimal("15.00"),
        confidence=0.85,
        timestamp=_utc_now(),
    )


def _make_capital(
    current: str = "10000.00",
    deployed: str = "0.00",
) -> CapitalState:
    cur = Decimal(current)
    dep = Decimal(deployed)
    return CapitalState(
        current_capital=cur,
        peak_equity=cur,
        session_start_capital=cur,
        currently_deployed=dep,
        open_position_count=0,
        trades_today=0,
    )


def test_rtld_section6_worked_example() -> None:
    """Validate exact numbers from RTLD §6 worked example.

    Capital: ₹10,000, 1% risk = ₹100
    Entry: ₹250, Stop: ₹240 -> Stop distance = ₹10
    Raw Qty = floor(100 / 10) = 10
    Max Pos Cap = ₹10,000 * 20% = ₹2,000 -> Pos Cap Qty = floor(2000 / 250) = 8
    Exposure Headroom = ₹5,000 -> Exposure Cap Qty = floor(5000 / 250) = 20
    Final Qty = min(10, 8, 20) = 8 shares
    Binding Constraint: position_cap
    Actual Risk: 8 * ₹10 = ₹80
    Position Value: 8 * ₹250 = ₹2,000
    """
    sizer = PositionSizer()
    candidate = _make_candidate(entry="250.00", stop="240.00")
    capital = _make_capital(current="10000.00", deployed="0.00")

    result: SizingResult = sizer.calculate(candidate, capital)

    assert result.approved is True
    assert result.final_quantity == 8
    assert result.raw_quantity == 10
    assert result.pos_cap_quantity == 8
    assert result.exposure_cap_quantity == 20
    assert result.binding_constraint == "position_cap"
    assert result.actual_risk_at_stop == Decimal("80.00")
    assert result.position_value == Decimal("2000.00")
    assert result.risk_amount == Decimal("100.00")
    assert result.risk_pct_used == Decimal("0.01")
    assert result.reason == ""


def test_risk_budget_binding_constraint() -> None:
    """When raw quantity is smaller than position and exposure caps, risk_budget governs."""
    sizer = PositionSizer()
    # Entry 100, Stop 90 -> Stop dist 10. Budget ₹100 -> Raw = 10.
    # Pos cap (2000 / 100) = 20. Exposure cap (5000 / 100) = 50.
    # Final = 10, binding = risk_budget.
    candidate = _make_candidate(entry="100.00", stop="90.00")
    capital = _make_capital(current="10000.00", deployed="0.00")

    result = sizer.calculate(candidate, capital)

    assert result.approved is True
    assert result.final_quantity == 10
    assert result.binding_constraint == "risk_budget"
    assert result.actual_risk_at_stop == Decimal("100.00")
    assert result.position_value == Decimal("1000.00")


def test_exposure_headroom_binding_constraint() -> None:
    """When deployed capital reduces exposure headroom, exposure_headroom governs."""
    sizer = PositionSizer()
    # Deployed ₹4,800 out of ₹5,000 max exposure -> Headroom = ₹200.
    # Entry 100, Stop 90 -> Stop dist 10. Raw = 10. Pos cap = 20.
    # Exposure cap = 200 // 100 = 2 shares.
    # Final = 2, binding = exposure_headroom.
    candidate = _make_candidate(entry="100.00", stop="90.00")
    capital = _make_capital(current="10000.00", deployed="4800.00")

    result = sizer.calculate(candidate, capital)

    assert result.approved is True
    assert result.final_quantity == 2
    assert result.exposure_cap_quantity == 2
    assert result.binding_constraint == "exposure_headroom"
    assert result.actual_risk_at_stop == Decimal("20.00")
    assert result.position_value == Decimal("200.00")


def test_unsizeable_raw_qty_zero() -> None:
    """When stop distance is wider than risk budget, raw quantity is 0 and trade is rejected."""
    sizer = PositionSizer()
    # Budget ₹100, Stop dist ₹150 -> Raw = 0
    candidate = _make_candidate(entry="500.00", stop="350.00")
    capital = _make_capital(current="10000.00")

    result = sizer.calculate(candidate, capital)

    assert result.approved is False
    assert result.final_quantity == 0
    assert result.raw_quantity == 0
    assert result.binding_constraint == "unsizeable"
    assert "cannot purchase 1 unit" in result.reason


def test_unsizeable_zero_stop_distance() -> None:
    """Zero stop distance is rejected as unsizeable."""
    sizer = PositionSizer()
    # Construct with model bypass or matching stop
    candidate = CandidateTrade.model_construct(
        instrument="NIFTY",
        direction="BUY",
        entry_price=Decimal("100.00"),
        stop_price=Decimal("100.00"),
        timeframe="15m",
        timestamp=_utc_now(),
        confidence=0.8,
    )
    capital = _make_capital()

    result = sizer.calculate(candidate, capital)
    assert result.approved is False
    assert result.final_quantity == 0
    assert result.binding_constraint == "unsizeable"
    assert "Stop distance must be strictly positive" in result.reason


def test_unsizeable_negative_entry_price() -> None:
    """Invalid entry price <= 0 is rejected as unsizeable."""
    sizer = PositionSizer()
    candidate = CandidateTrade.model_construct(
        instrument="NIFTY",
        direction="BUY",
        entry_price=Decimal("0.00"),
        stop_price=Decimal("-10.00"),
        timeframe="15m",
        timestamp=_utc_now(),
        confidence=0.8,
    )
    capital = _make_capital()

    result = sizer.calculate(candidate, capital)
    assert result.approved is False
    assert result.final_quantity == 0
    assert result.binding_constraint == "unsizeable"
    assert "Entry price must be strictly positive" in result.reason


def test_exposure_headroom_zero_blocks_sizing() -> None:
    """When exposure is fully deployed, headroom is 0 and sizing is rejected."""
    sizer = PositionSizer()
    # ₹5,000 deployed on ₹10,000 capital (50% max exposure)
    candidate = _make_candidate(entry="100.00", stop="90.00")
    capital = _make_capital(current="10000.00", deployed="5000.00")

    result = sizer.calculate(candidate, capital)

    assert result.approved is False
    assert result.final_quantity == 0
    assert result.exposure_cap_quantity == 0
    assert result.binding_constraint == "exposure_headroom"
    assert "Exposure headroom prevents purchasing 1 unit" in result.reason


def test_position_cap_zero_blocks_sizing() -> None:
    """When single position cap is less than entry price, sizing is rejected."""
    config = RiskConfig(max_position_size_pct=Decimal("0.005"))  # 0.5% = ₹50
    sizer = PositionSizer(config=config)
    candidate = _make_candidate(entry="100.00", stop="90.00")
    capital = _make_capital(current="10000.00")

    result = sizer.calculate(candidate, capital)

    assert result.approved is False
    assert result.final_quantity == 0
    assert result.pos_cap_quantity == 0
    assert result.binding_constraint == "position_cap"
    assert "Single position cap prevents purchasing 1 unit" in result.reason


def test_streak_tier1_halves_risk_budget() -> None:
    """3 consecutive losses triggers Tier-1 50% risk budget reduction (RTLD-11)."""
    sizer = PositionSizer()
    candidate = _make_candidate(entry="100.00", stop="95.00")  # stop dist 5
    capital = _make_capital(current="10000.00")

    # Normal: budget ₹100, dist 5 -> raw 20
    normal_res = sizer.calculate(candidate, capital)
    assert normal_res.final_quantity == 20
    assert normal_res.risk_pct_used == Decimal("0.01")

    # Tier-1 active (3 losses): budget ₹50, dist 5 -> raw 10
    streak = StreakState(consecutive_losses=3)
    tier1_res = sizer.calculate(candidate, capital, streak=streak)
    assert tier1_res.approved is True
    assert tier1_res.final_quantity == 10
    assert tier1_res.risk_amount == Decimal("50.00")
    assert tier1_res.risk_pct_used == Decimal("0.005")


def test_elevated_volatility_halves_risk_budget() -> None:
    """Market volatility > 2x trailing average halves risk budget (RTLD-14)."""
    sizer = PositionSizer()
    candidate = _make_candidate(entry="100.00", stop="95.00")  # stop dist 5
    capital = _make_capital(current="10000.00")

    market = MarketState(
        instrument="RELIANCE",
        current_volatility=Decimal("25.0"),
        trailing_20session_avg_volatility=Decimal("10.0"),  # 2.5x > 2.0x trigger
    )
    result = sizer.calculate(candidate, capital, market=market)

    assert result.approved is True
    assert result.final_quantity == 10
    assert result.risk_amount == Decimal("50.00")
    assert result.risk_pct_used == Decimal("0.005")


def test_combined_streak_and_volatility_halved_twice() -> None:
    """Both streak Tier-1 and elevated vol active reduces budget by 75% (halved twice)."""
    sizer = PositionSizer()
    candidate = _make_candidate(entry="100.00", stop="95.00")  # stop dist 5
    capital = _make_capital(current="10000.00")

    streak = StreakState(consecutive_losses=3)
    market = MarketState(
        instrument="RELIANCE",
        current_volatility=Decimal("25.0"),
        trailing_20session_avg_volatility=Decimal("10.0"),
    )
    result = sizer.calculate(candidate, capital, streak=streak, market=market)

    # ₹10,000 * 1% * 0.5 * 0.5 = ₹25 budget. Stop dist 5 -> 5 shares.
    assert result.approved is True
    assert result.final_quantity == 5
    assert result.risk_amount == Decimal("25.00")
    assert result.risk_pct_used == Decimal("0.0025")


def test_binding_constraint_ties_handling() -> None:
    """Cover tie-breaking branches where constraints are identical."""
    sizer = PositionSizer()
    # Set entry and stop such that raw_qty == pos_cap_qty
    # Capital 10,000. 1% risk = 100. Stop dist 10 -> raw = 10.
    # Entry = 200. Pos cap = 2000 // 200 = 10.
    # Exposure headroom = 5000 // 200 = 25.
    # final_quantity = 10 (raw_qty == pos_cap_qty == 10).
    candidate = _make_candidate(entry="200.00", stop="190.00")
    capital = _make_capital(current="10000.00", deployed="0.00")

    result = sizer.calculate(candidate, capital)
    assert result.approved is True
    assert result.final_quantity == 10
    assert result.binding_constraint in ("position_cap", "risk_budget")


def test_config_property_and_defaults() -> None:
    """Verify config property returns initialized RiskConfig."""
    sizer = PositionSizer()
    assert sizer.config.initial_live_capital == Decimal("10000.00")

    custom_cfg = RiskConfig(max_risk_per_trade_pct=Decimal("0.02"))
    custom_sizer = PositionSizer(config=custom_cfg)
    assert custom_sizer.config.max_risk_per_trade_pct == Decimal("0.02")
