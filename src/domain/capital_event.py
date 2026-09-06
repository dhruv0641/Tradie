"""Canonical domain models for capital scaling and withdrawal events.

Adheres strictly to BRD BR-2, FRD-CAP-1, FRD-CAP-3, FRD-CAP-4, and RTLD §15.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CapitalEventType(StrEnum):
    """Types of capital alteration events."""

    SCALING_INCREASE = "SCALING_INCREASE"
    PROFIT_WITHDRAWAL = "PROFIT_WITHDRAWAL"
    CAPITAL_RESET = "CAPITAL_RESET"


class CapitalEvent(BaseModel):
    """Immutable audit trail record for capital allocation and withdrawal changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(
        default_factory=lambda: f"capevt_{uuid.uuid4().hex[:12]}",
        description="Unique identifier for the capital event",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event creation timestamp in UTC",
    )
    event_type: CapitalEventType = Field(
        ...,
        description="Type of capital event",
    )
    previous_capital: Decimal = Field(
        ge=Decimal("0.00"),
        description="Capital allocated prior to this event in INR",
    )
    new_capital: Decimal = Field(
        ge=Decimal("0.00"),
        description="New capital allocated after this event in INR",
    )
    withdrawn_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=Decimal("0.00"),
        description="Amount of profit withdrawn in this transaction in INR",
    )
    operator_token_hash: str = Field(
        ...,
        description="Cryptographic SHA-256 hash of operator token for non-repudiation",
    )
    justification: str = Field(
        ...,
        description="Operational justification and audit explanation",
    )
    scaling_report_id: str | None = Field(
        default=None,
        description="Associated CapitalScalingReport ID if triggered by scaling evaluation",
    )
