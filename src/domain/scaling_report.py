"""Canonical domain models for multi-criteria capital scaling evaluation.

Adheres strictly to BRD BR-2, FRD-CAP-2, FRD-CAP-5, FRD-CAP-6, and RTLD §15.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CriterionResult(BaseModel):
    """Result of an individual capital scaling criterion evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_number: int = Field(ge=1, le=9, description="Criterion index (1 to 9)")
    name: str = Field(..., description="Short name of the criterion")
    passed: bool = Field(..., description="Whether the criterion requirement was satisfied")
    threshold: str = Field(..., description="Target threshold requirement string")
    actual: str = Field(..., description="Observed empirical performance string")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Supporting evidence data")


class CapitalScalingReport(BaseModel):
    """Immutable audit report evaluating eligibility for capital scaling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str = Field(
        default_factory=lambda: f"cap_eval_{uuid.uuid4().hex[:12]}",
        description="Unique identifier for the evaluation report",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Evaluation timestamp in UTC",
    )
    current_capital: Decimal = Field(
        ge=Decimal("0.00"),
        description="Current live trading capital in INR",
    )
    recommended_capital: Decimal | None = Field(
        default=None,
        description="Recommended new capital tier (+25% capped) if eligible, else None",
    )
    eligible_for_scaling: bool = Field(
        ...,
        description="True only if ALL 9 RTLD §15 criteria passed simultaneously",
    )
    criteria_results: dict[str, CriterionResult] = Field(
        ...,
        description="Dictionary mapping criterion key to its evaluation result",
    )
    passed_count: int = Field(
        ge=0,
        le=9,
        description="Number of criteria that passed",
    )
    total_criteria: int = Field(
        default=9,
        description="Total number of evaluated criteria (strictly 9)",
    )
    summary_verdict: str = Field(
        ...,
        description="Human-readable decision explanation and evidence summary",
    )
    evaluation_window_days: int = Field(
        ge=1,
        description="Observation duration in days",
    )
