"""Unit tests for OrderTranslator and bounded slippage parameter translation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domain.decision import Decision
from src.domain.risk import CandidateTrade, RiskCheckResult
from src.execution.translator import (
    OrderTranslationConfig,
    OrderTranslationError,
    OrderTranslator,
)


def make_risk_check(approved: bool = True, quantity: int = 10) -> RiskCheckResult:
    if approved:
        return RiskCheckResult(
            passed=True,
            reason="Approved by test risk check",
            config_version="0.1.0",
            approved_quantity=quantity,
            stop_loss_price=Decimal("2450.00"),
        )
    return RiskCheckResult(
        passed=False,
        failed_check="max_trade_risk",
        rtld_param_id="RTLD-4",
        reason="Rejected by test risk check",
        config_version="0.1.0",
        approved_quantity=0,
    )


def make_decision(
    outcome: str = "BUY",
    approved_quantity: int = 10,
    stop_loss_price: Decimal | None = Decimal("2450.00"),
) -> Decision:
    now = datetime.now(UTC)
    return Decision(
        outcome=outcome,  # type: ignore[arg-type]
        reason="Supervisor approved",
        risk_check=make_risk_check(
            approved=approved_quantity > 0 and outcome in ("BUY", "SELL"),
            quantity=approved_quantity,
        ),
        kill_switch_active=False,
        approved_quantity=approved_quantity,
        stop_loss_price=stop_loss_price,
        target_price=Decimal("2600.00"),
        timestamp=now,
    )


def make_candidate(
    instrument: str = "RELIANCE",
    direction: str = "BUY",
    entry_price: Decimal = Decimal("2500.00"),
    stop_price: Decimal | None = None,
) -> CandidateTrade:
    now = datetime.now(UTC)
    resolved_stop = (
        stop_price
        if stop_price is not None
        else (
            entry_price - Decimal("5.00") if direction == "BUY" else entry_price + Decimal("5.00")
        )
    )
    return CandidateTrade(
        instrument=instrument,
        direction=direction,  # type: ignore[arg-type]
        entry_price=entry_price,
        stop_price=resolved_stop,
        timeframe="5m",
        trade_quality_score=0.85,
        expected_value=Decimal("15.50"),
        confidence=0.80,
        timestamp=now,
    )


def test_order_translator_buy_limit_default() -> None:
    """Verify BUY limit order calculation with default 0.20% slippage and 0.05 tick."""
    translator = OrderTranslator()
    decision = make_decision(outcome="BUY", approved_quantity=10)
    candidate = make_candidate(
        direction="BUY", entry_price=Decimal("100.00"), stop_price=Decimal("95.00")
    )

    result = translator.translate(decision=decision, candidate=candidate)

    assert result.direction == "BUY"
    assert result.order_type == "LIMIT"
    assert result.quantity == 10
    # 100.00 * 1.002 = 100.20 (divisible by 0.05)
    assert result.limit_price == Decimal("100.20")
    assert result.decision_quote_price == Decimal("100.00")
    assert result.slippage_bound == Decimal("0.20")
    assert result.broker_symbol == "RELIANCE"


def test_order_translator_sell_limit_default() -> None:
    """Verify SELL limit order calculation with default 0.20% slippage and 0.05 tick."""
    translator = OrderTranslator()
    decision = make_decision(
        outcome="SELL", approved_quantity=20, stop_loss_price=Decimal("105.00")
    )
    candidate = make_candidate(
        direction="SELL", entry_price=Decimal("100.00"), stop_price=Decimal("105.00")
    )

    result = translator.translate(decision=decision, candidate=candidate)

    assert result.direction == "SELL"
    assert result.order_type == "LIMIT"
    assert result.quantity == 20
    # 100.00 * (1 - 0.002) = 99.80 (divisible by 0.05)
    assert result.limit_price == Decimal("99.80")
    assert result.decision_quote_price == Decimal("100.00")
    assert result.slippage_bound == Decimal("0.20")


def test_order_translator_conservative_tick_rounding_buy() -> None:
    """Verify BUY limit rounds DOWN to nearest tick to avoid exceeding slippage ceiling."""
    translator = OrderTranslator()
    # 123.47 * 1.002 = 123.71694 -> nearest tick (0.05) floor is 123.70
    limit = translator.calculate_bounded_limit_price(
        direction="BUY",
        quote_price=Decimal("123.47"),
        instrument="TEST",
    )
    assert limit == Decimal("123.70")
    assert limit <= Decimal("123.47") * (Decimal("1") + Decimal("0.002"))
    assert limit % Decimal("0.05") == Decimal("0")


def test_order_translator_conservative_tick_rounding_sell() -> None:
    """Verify SELL limit rounds UP to nearest tick to avoid falling below slippage floor."""
    translator = OrderTranslator()
    # 123.47 * (1 - 0.002) = 123.22306 -> nearest tick (0.05) ceil is 123.25
    limit = translator.calculate_bounded_limit_price(
        direction="SELL",
        quote_price=Decimal("123.47"),
        instrument="TEST",
    )
    assert limit == Decimal("123.25")
    assert limit >= Decimal("123.47") * (Decimal("1") - Decimal("0.002"))
    assert limit % Decimal("0.05") == Decimal("0")


def test_order_translator_custom_tick_and_lot_size() -> None:
    """Verify custom instrument tick size, lot size, and symbol mapping."""
    config = OrderTranslationConfig(
        instrument_tick_sizes={"NIFTY": Decimal("0.25")},
        instrument_lot_sizes={"NIFTY": 50},
        symbol_mappings={"NSE:NIFTY": "NIFTY-FUT"},
    )
    translator = OrderTranslator(config=config)

    decision = make_decision(outcome="BUY", approved_quantity=100)
    candidate = make_candidate(
        instrument="NSE:NIFTY",
        direction="BUY",
        entry_price=Decimal("24000.00"),
        stop_price=Decimal("23800.00"),
    )

    result = translator.translate(decision=decision, candidate=candidate)
    assert result.broker_symbol == "NIFTY-FUT"
    assert result.lot_size == 50
    assert result.tick_size == Decimal("0.25")


def test_order_translator_lot_size_violation() -> None:
    """Verify rejection when approved quantity violates instrument lot size."""
    config = OrderTranslationConfig(
        instrument_lot_sizes={"BANKNIFTY": 15},
    )
    translator = OrderTranslator(config=config)

    decision = make_decision(outcome="BUY", approved_quantity=20)  # Not multiple of 15
    candidate = make_candidate(
        instrument="BANKNIFTY",
        direction="BUY",
        entry_price=Decimal("50000.00"),
        stop_price=Decimal("49500.00"),
    )

    with pytest.raises(OrderTranslationError, match="not a multiple of lot size 15"):
        translator.translate(decision=decision, candidate=candidate)


def test_order_translator_market_order_policy() -> None:
    """Verify market orders are forbidden by default and accepted when configured."""
    translator_safe = OrderTranslator()
    decision = make_decision(outcome="BUY", approved_quantity=10)
    candidate = make_candidate(direction="BUY")

    # Default policy forbids market orders
    with pytest.raises(OrderTranslationError, match="Market orders are forbidden"):
        translator_safe.translate(
            decision=decision, candidate=candidate, override_order_type="MARKET"
        )

    # Permissive policy allows market orders
    config_permissive = OrderTranslationConfig(allow_market_orders=True)
    translator_permissive = OrderTranslator(config=config_permissive)

    result = translator_permissive.translate(
        decision=decision, candidate=candidate, override_order_type="MARKET"
    )
    assert result.order_type == "MARKET"
    assert result.limit_price is None
    assert result.slippage_bound is None


def test_order_translator_unapproved_decisions_rejected() -> None:
    """Verify non-actionable decisions (HOLD, NO_TRADE, quantity=0) are rejected."""
    translator = OrderTranslator()
    candidate = make_candidate(direction="BUY")

    # HOLD decision
    hold_dec = make_decision(outcome="HOLD", approved_quantity=0)
    with pytest.raises(OrderTranslationError, match="Cannot translate non-approved decision"):
        translator.translate(decision=hold_dec, candidate=candidate)

    # NO_TRADE decision
    no_trade_dec = make_decision(outcome="NO_TRADE", approved_quantity=0)
    with pytest.raises(OrderTranslationError, match="Cannot translate non-approved decision"):
        translator.translate(decision=no_trade_dec, candidate=candidate)


def test_order_translator_direction_mismatch_rejected() -> None:
    """Verify error when Decision direction does not match CandidateTrade direction."""
    translator = OrderTranslator()
    buy_dec = make_decision(outcome="BUY", approved_quantity=10)
    sell_candidate = make_candidate(
        direction="SELL", entry_price=Decimal("100.00"), stop_price=Decimal("105.00")
    )

    with pytest.raises(OrderTranslationError, match="Direction mismatch"):
        translator.translate(decision=buy_dec, candidate=sell_candidate)


def test_order_translator_invalid_quote_price() -> None:
    """Verify error when quote price is non-positive."""
    translator = OrderTranslator()
    with pytest.raises(OrderTranslationError, match="Quote price must be strictly positive"):
        translator.calculate_bounded_limit_price(
            direction="BUY", quote_price=Decimal("0.00"), instrument="RELIANCE"
        )


def test_order_translator_exact_symbol_tick_override() -> None:
    """Verify exact instrument symbol match in instrument_tick_sizes."""
    config = OrderTranslationConfig(
        instrument_tick_sizes={"TCS": Decimal("0.10")},
    )
    translator = OrderTranslator(config=config)
    assert translator.get_tick_size("TCS") == Decimal("0.10")


def test_order_translator_limit_price_non_positive_error() -> None:
    """Verify error when calculated limit price drops to zero or below."""
    translator = OrderTranslator()
    with pytest.raises(OrderTranslationError, match="must be strictly positive"):
        translator.calculate_bounded_limit_price(
            direction="SELL",
            quote_price=Decimal("0.05"),
            instrument="PENNY",
            slippage_pct=Decimal("1.0"),  # 100% slippage causes price to drop to 0
        )


def test_order_translator_with_current_quote_override() -> None:
    """Verify translate() uses current_quote when provided."""
    translator = OrderTranslator()
    decision = make_decision(outcome="BUY", approved_quantity=10)
    candidate = make_candidate(direction="BUY", entry_price=Decimal("100.00"))

    result = translator.translate(
        decision=decision, candidate=candidate, current_quote=Decimal("200.00")
    )
    assert result.decision_quote_price == Decimal("200.00")
    assert result.limit_price == Decimal("200.40")  # 200 * 1.002 = 200.40


def test_order_translator_deterministic_client_id_linking() -> None:
    """Verify deterministic linking to DecisionRecord ID vs fallback timestamp."""
    translator = OrderTranslator()
    decision = make_decision(outcome="BUY", approved_quantity=10)
    candidate = make_candidate(direction="BUY")

    dec_id = uuid4()
    result_linked = translator.translate(
        decision=decision, candidate=candidate, decision_record_id=dec_id
    )
    assert result_linked.client_order_id == f"aitrader-{dec_id}"

    result_fallback = translator.translate(decision=decision, candidate=candidate)
    assert result_fallback.client_order_id.startswith("aitrader-RELIANCE-BUY-")
