"""Unit tests for the structured logging subsystem."""

import json
from typing import Any

import pytest

from src.utils.logging import (
    bind_correlation_id,
    clear_correlation_id,
    configure_logging,
    get_correlation_id,
    get_logger,
)


@pytest.mark.unit
def test_correlation_id_lifecycle() -> None:
    """Verify binding, retrieving, and clearing of correlation IDs."""
    clear_correlation_id()
    assert get_correlation_id() is None

    assigned = bind_correlation_id("test-corr-id-999")
    assert assigned == "test-corr-id-999"
    assert get_correlation_id() == "test-corr-id-999"

    clear_correlation_id()
    assert get_correlation_id() is None

    auto_gen = bind_correlation_id()
    assert isinstance(auto_gen, str)
    assert len(auto_gen) > 10
    clear_correlation_id()


@pytest.mark.unit
def test_json_logging_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that logging in test/production environment emits valid JSON with mandatory fields."""
    configure_logging(environment="test", log_level="DEBUG")
    logger = get_logger("unit_test_logger")

    test_cid = "corr-req-555"
    bind_correlation_id(test_cid)

    logger.info(
        "order_submitted",
        symbol="RELIANCE",
        quantity=50,
        price=2950.50,
    )

    captured = capsys.readouterr()
    log_line = captured.out.strip()
    assert log_line != ""

    parsed: dict[str, Any] = json.loads(log_line)
    assert parsed["event"] == "order_submitted"
    assert parsed["level"] == "info"
    assert parsed["logger"] == "unit_test_logger"
    assert parsed["correlation_id"] == test_cid
    assert parsed["symbol"] == "RELIANCE"
    assert parsed["quantity"] == 50
    assert parsed["price"] == 2950.50
    assert "timestamp" in parsed

    clear_correlation_id()


@pytest.mark.unit
def test_local_console_environment(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify console renderer operates without error in local development mode."""
    configure_logging(environment="local", log_level="INFO")
    logger = get_logger("dev_logger")
    logger.info("local_dev_event", key="value")

    captured = capsys.readouterr()
    assert "local_dev_event" in captured.out
    assert "value" in captured.out
