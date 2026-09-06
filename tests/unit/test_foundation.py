"""Foundation sanity unit tests verifying runtime environment and package availability."""

import sys
from datetime import datetime

import asyncpg
import numpy as np
import pandas as pd
import pyarrow as pa
import pydantic
import pytest
import sqlalchemy
import structlog

import src


@pytest.mark.unit
def test_python_version() -> None:
    """Verify runtime Python version is >= 3.12."""
    assert sys.version_info >= (3, 12), f"Expected Python 3.12+, got {sys.version}"


@pytest.mark.unit
def test_package_metadata() -> None:
    """Verify core package version and metadata."""
    assert src.__version__ == "0.1.0"


@pytest.mark.unit
def test_core_dependencies_importable() -> None:
    """Verify that all core production dependencies import without errors."""
    assert pydantic.__version__ is not None
    assert structlog.__version__ is not None
    assert sqlalchemy.__version__ is not None
    assert asyncpg.__version__ is not None
    assert pa.__version__ is not None
    assert np.__version__ is not None
    assert pd.__version__ is not None


@pytest.mark.unit
def test_fixture_deterministic_clock(fixed_utc_now: datetime) -> None:
    """Verify deterministic fixture operation."""
    assert fixed_utc_now.year == 2026
    assert fixed_utc_now.tzinfo is not None
