"""Shared Pytest fixtures and testing configuration for AI Trader."""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest


@pytest.fixture
def fixed_utc_now() -> datetime:
    """Provide a deterministic UTC timestamp for temporal tests."""
    return datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def clean_environment() -> Generator[None, None, None]:
    """Ensure clean test environment without persistent side-effects."""
    yield
