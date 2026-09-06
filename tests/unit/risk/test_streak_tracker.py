"""Unit tests for StreakTracker enforcing RTLD §10 consecutive loss circuit breakers."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.domain.risk import StreakState
from src.risk.streak_tracker import StreakTracker


def test_initial_state_defaults() -> None:
    """Verify clean initial state of StreakTracker."""
    tracker = StreakTracker()

    assert tracker.consecutive_losses == 0
    assert tracker.session_paused is False
    assert tracker.is_tier1_active is False
    assert tracker.is_tier2_active is False
    assert tracker.size_multiplier == Decimal("1.0")
    assert tracker.rolling is True
    assert tracker.config.consec_loss_reduce_trigger == 3
    assert tracker.config.consec_loss_pause_trigger == 5

    state = tracker.get_state()
    assert state.consecutive_losses == 0
    assert state.is_tier1_active is False
    assert state.is_tier2_active is False
    assert state.session_paused is False
    assert state.last_trade_pnl is None


def test_consecutive_loss_progression_tier1_and_tier2() -> None:
    """Verify progression through Tier-1 (3 losses) and Tier-2 (5 losses) triggers."""
    tracker = StreakTracker()

    # Trade 1: Loss ₹50 -> losses=1, tier1=False, mult=1.0
    s1 = tracker.record_trade(Decimal("-50.00"), trade_id="T1")
    assert s1.consecutive_losses == 1
    assert s1.is_tier1_active is False
    assert s1.is_tier2_active is False
    assert tracker.size_multiplier == Decimal("1.0")

    # Trade 2: Loss ₹40 -> losses=2, tier1=False, mult=1.0
    s2 = tracker.record_trade(-40.0, trade_id="T2")
    assert s2.consecutive_losses == 2
    assert s2.is_tier1_active is False
    assert s2.is_tier2_active is False
    assert tracker.size_multiplier == Decimal("1.0")

    # Trade 3: Loss ₹30 -> losses=3 -> TIER-1 ACTIVE (RTLD-11: 50% size reduction)
    s3 = tracker.record_trade(Decimal("-30.00"), trade_id="T3")
    assert s3.consecutive_losses == 3
    assert s3.is_tier1_active is True
    assert s3.is_tier2_active is False
    assert tracker.is_tier1_active is True
    assert tracker.size_multiplier == Decimal("0.5")

    # Trade 4: Loss ₹20 -> losses=4 -> Tier-1 persists, Tier-2 not yet
    s4 = tracker.record_trade(Decimal("-20.00"), trade_id="T4")
    assert s4.consecutive_losses == 4
    assert s4.is_tier1_active is True
    assert s4.is_tier2_active is False
    assert tracker.size_multiplier == Decimal("0.5")

    # Trade 5: Loss ₹10 -> losses=5 -> TIER-2 ACTIVE (RTLD-12: Session Pause)
    s5 = tracker.record_trade(Decimal("-10.00"), trade_id="T5")
    assert s5.consecutive_losses == 5
    assert s5.is_tier1_active is True
    assert s5.is_tier2_active is True
    assert s5.session_paused is True
    assert tracker.session_paused is True
    assert tracker.is_tier2_active is True


def test_winning_trade_resets_counter() -> None:
    """A winning trade immediately resets consecutive loss counter to 0."""
    tracker = StreakTracker()

    # Accumulate 3 losses (Tier-1 active)
    tracker.record_trade(Decimal("-50.00"))
    tracker.record_trade(Decimal("-50.00"))
    tracker.record_trade(Decimal("-50.00"))
    assert tracker.is_tier1_active is True
    assert tracker.size_multiplier == Decimal("0.5")

    # Winning trade ₹100.00
    state = tracker.record_trade(Decimal("100.00"), trade_id="WIN-1")
    assert state.consecutive_losses == 0
    assert state.is_tier1_active is False
    assert state.is_tier2_active is False
    assert tracker.consecutive_losses == 0
    assert tracker.size_multiplier == Decimal("1.0")
    assert state.last_trade_pnl == Decimal("100.00")


def test_breakeven_trade_maintains_streak() -> None:
    """A breakeven trade (pnl = 0) does not break streak nor increment it."""
    tracker = StreakTracker()

    tracker.record_trade(Decimal("-50.00"))
    tracker.record_trade(Decimal("-50.00"))
    assert tracker.consecutive_losses == 2

    state = tracker.record_trade(Decimal("0.00"), trade_id="BE-1")
    assert state.consecutive_losses == 2
    assert tracker.consecutive_losses == 2
    assert state.last_trade_pnl == Decimal("0.00")


def test_session_start_with_rolling_persistence() -> None:
    """Session start clears Tier-2 session pause while retaining rolling Tier-1 losses."""
    tracker = StreakTracker(rolling=True)

    # Trigger 5 losses (Tier-2 session pause)
    for _ in range(5):
        tracker.record_trade(Decimal("-20.00"))
    assert bool(tracker.session_paused) is True
    assert bool(tracker.is_tier2_active) is True

    # New session starts
    new_session_state = tracker.on_session_start(session_date=date(2026, 9, 7))
    assert bool(new_session_state.session_paused) is False
    assert bool(tracker.session_paused) is False
    # Rolling retention keeps consecutive losses at 5, meaning Tier-1 sizing persists
    assert new_session_state.consecutive_losses == 5
    assert new_session_state.is_tier1_active is True
    assert tracker.size_multiplier == Decimal("0.5")


def test_session_start_non_rolling_resets_losses() -> None:
    """When rolling is disabled, session start resets consecutive losses to 0."""
    tracker = StreakTracker(rolling=False)

    for _ in range(3):
        tracker.record_trade(Decimal("-20.00"))
    assert tracker.consecutive_losses == 3
    assert tracker.is_tier1_active is True

    new_state = tracker.on_session_start()
    assert new_state.consecutive_losses == 0
    assert new_state.is_tier1_active is False
    assert tracker.size_multiplier == Decimal("1.0")


def test_initial_state_injection() -> None:
    """Verify StreakTracker initializes correctly from an existing StreakState."""
    initial = StreakState(
        consecutive_losses=4,
        is_tier1_active=True,
        is_tier2_active=False,
        session_paused=False,
        last_trade_pnl=Decimal("-25.00"),
    )
    tracker = StreakTracker(initial_state=initial)

    assert tracker.consecutive_losses == 4
    assert tracker.is_tier1_active is True
    assert tracker.size_multiplier == Decimal("0.5")
    assert tracker.get_state().last_trade_pnl == Decimal("-25.00")


def test_naive_datetime_handling() -> None:
    """Naive timestamp in record_trade is safely normalized to UTC."""
    tracker = StreakTracker()
    naive_dt = datetime(2026, 9, 6, 15, 30, 0)

    state = tracker.record_trade(pnl=Decimal("-15.00"), trade_id="T-NAIVE", exit_time=naive_dt)
    assert state.consecutive_losses == 1


def test_authorized_manual_reset() -> None:
    """Operator manual reset clears all streak counters when valid token is supplied."""
    tracker = StreakTracker()
    tracker.record_trade(Decimal("-50.00"))
    tracker.record_trade(Decimal("-50.00"))
    tracker.record_trade(Decimal("-50.00"))
    assert tracker.consecutive_losses == 3

    # Reset with valid auth token
    tracker.reset(auth_token="valid_operator_token_123")
    assert tracker.consecutive_losses == 0
    assert tracker.is_tier1_active is False
    assert tracker.session_paused is False
    assert tracker.size_multiplier == Decimal("1.0")


def test_unauthorized_manual_reset_raises_error() -> None:
    """Manual reset without token raises PermissionError."""
    tracker = StreakTracker()
    tracker.record_trade(Decimal("-50.00"))

    with pytest.raises(PermissionError, match="Operator authorization token required"):
        tracker.reset(auth_token="")

    with pytest.raises(PermissionError, match="Operator authorization token required"):
        tracker.reset(auth_token=None)
