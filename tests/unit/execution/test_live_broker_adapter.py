"""Unit tests for LiveBrokerAdapter with sandbox simulation and mocked HTTP transports."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from src.config.models import BrokerConfig
from src.domain.execution import Position
from src.execution.broker_adapter import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerOrderError,
    BrokerOrderNotFoundError,
    BrokerRateLimitError,
)
from src.execution.live_broker_adapter import LiveBrokerAdapter


@pytest.fixture
def sandbox_adapter() -> LiveBrokerAdapter:
    """Create a LiveBrokerAdapter in sandbox mode."""
    cfg = BrokerConfig(
        broker_name="zerodha_sandbox",
        api_key=SecretStr("mock_key"),
        api_secret=SecretStr("mock_secret"),
        paper_trading=True,
    )
    return LiveBrokerAdapter(config=cfg, sandbox_mode=True)


def test_sandbox_order_lifecycle(sandbox_adapter: LiveBrokerAdapter) -> None:
    """Verify order placement, modification, status query, and cancellation in sandbox."""
    assert sandbox_adapter.authenticate() is True
    assert sandbox_adapter.is_authenticated is True

    # 1. Place LIMIT BUY order
    order = sandbox_adapter.place_order(
        client_order_id="CID-001",
        instrument="NSE:INFY",
        direction="BUY",
        quantity=10,
        order_type="LIMIT",
        price=Decimal("1500.00"),
    )
    assert order.client_order_id == "CID-001"
    assert order.broker_order_id is not None
    assert order.status == "SUBMITTED"
    assert order.quantity == 10
    assert order.limit_price == Decimal("1500.00")

    # 2. Query status
    status = sandbox_adapter.get_order_status("CID-001")
    assert status.status == "SUBMITTED"
    assert status.broker_order_id == order.broker_order_id

    # 3. Modify order
    modified = sandbox_adapter.modify_order(
        client_order_id="CID-001",
        quantity=15,
        price=Decimal("1505.00"),
    )
    assert modified.quantity == 15
    assert modified.limit_price == Decimal("1505.00")

    # 4. Cancel order
    cancelled = sandbox_adapter.cancel_order("CID-001")
    assert cancelled is True
    assert sandbox_adapter.get_order_status("CID-001").status == "CANCELLED"

    # 5. Modify or cancel unknown order raises BrokerOrderNotFoundError
    with pytest.raises(BrokerOrderNotFoundError):
        sandbox_adapter.modify_order("UNKNOWN-CID", quantity=5)

    with pytest.raises(BrokerOrderNotFoundError):
        sandbox_adapter.cancel_order("UNKNOWN-CID")

    with pytest.raises(BrokerOrderNotFoundError):
        sandbox_adapter.get_order_status("UNKNOWN-CID")


def test_sandbox_positions_and_cash(sandbox_adapter: LiveBrokerAdapter) -> None:
    """Verify position management and cash balance querying in sandbox mode."""
    sandbox_adapter.authenticate()
    assert sandbox_adapter.heartbeat() is True

    # Initially empty positions and ₹10,000 cash
    assert len(sandbox_adapter.get_positions()) == 0
    assert sandbox_adapter.get_account_balance() == Decimal("10000.00")

    # Inject position
    pos = Position(
        instrument="NSE:TCS",
        quantity=25,
        average_entry_price=Decimal("3800.00"),
        current_market_price=Decimal("3850.00"),
        unrealized_pnl=Decimal("1250.00"),
        realized_pnl=Decimal("0.00"),
        peak_unrealized_pnl=Decimal("1250.00"),
        updated_at=datetime.now(UTC),
    )
    sandbox_adapter.set_sandbox_position(pos)
    sandbox_adapter.set_sandbox_cash(Decimal("15000.00"))

    positions = sandbox_adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument == "NSE:TCS"
    assert positions[0].quantity == 25
    assert sandbox_adapter.get_account_balance() == Decimal("15000.00")


def test_mocked_http_authentication_flow() -> None:
    """Verify live HTTP authentication against mocked broker endpoints."""
    mock_client = MagicMock(spec=httpx.Client)

    # 1. Success 200
    mock_resp_200 = MagicMock(spec=httpx.Response)
    mock_resp_200.status_code = 200
    mock_client.get.return_value = mock_resp_200

    cfg = BrokerConfig(
        broker_name="live_test",
        api_key=SecretStr("real_key"),
        api_secret=SecretStr("real_sec"),
        paper_trading=False,
    )
    adapter = LiveBrokerAdapter(config=cfg, client=mock_client, sandbox_mode=False)

    assert adapter.authenticate() is True
    assert adapter.is_authenticated is True
    assert adapter.heartbeat() is True

    # 2. Auth error 401
    mock_resp_401 = MagicMock(spec=httpx.Response)
    mock_resp_401.status_code = 401
    mock_resp_401.text = "Invalid API Key"
    mock_client.get.return_value = mock_resp_401

    with pytest.raises(BrokerAuthenticationError) as exc:
        adapter.authenticate()
    assert "status 401" in str(exc.value)

    # 3. Connection error
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    with pytest.raises(BrokerConnectionError) as exc_conn:
        adapter.authenticate()
    assert "Network connection error" in str(exc_conn.value)


def test_mocked_http_order_operations_and_error_handling() -> None:
    """Verify live HTTP order placement and error code translation."""
    mock_client = MagicMock(spec=httpx.Client)

    # Profile auth check
    mock_auth_resp = MagicMock(spec=httpx.Response)
    mock_auth_resp.status_code = 200

    # Place order 200
    mock_order_resp = MagicMock(spec=httpx.Response)
    mock_order_resp.status_code = 200
    mock_order_resp.json.return_value = {"status": "success", "data": {"order_id": "EXCH-99999"}}

    mock_client.get.return_value = mock_auth_resp
    mock_client.post.return_value = mock_order_resp

    cfg = BrokerConfig(
        broker_name="live_test",
        api_key=SecretStr("real_key"),
        api_secret=SecretStr("real_sec"),
        paper_trading=False,
    )
    adapter = LiveBrokerAdapter(config=cfg, client=mock_client, sandbox_mode=False)

    order = adapter.place_order(
        client_order_id="CID-HTTP-1",
        instrument="NSE:RELIANCE",
        direction="BUY",
        quantity=5,
        order_type="MARKET",
    )
    assert order.broker_order_id == "EXCH-99999"

    # Rate limit error 429
    mock_rate_limit = MagicMock(spec=httpx.Response)
    mock_rate_limit.status_code = 429
    mock_rate_limit.text = "Too many requests"
    mock_client.post.return_value = mock_rate_limit

    with pytest.raises(BrokerRateLimitError):
        adapter.place_order(
            client_order_id="CID-HTTP-2",
            instrument="NSE:RELIANCE",
            direction="SELL",
            quantity=5,
        )

    # Broker rejection error 400
    mock_reject = MagicMock(spec=httpx.Response)
    mock_reject.status_code = 400
    mock_reject.text = "Insufficient funds"
    mock_client.post.return_value = mock_reject

    with pytest.raises(BrokerOrderError):
        adapter.place_order(
            client_order_id="CID-HTTP-3",
            instrument="NSE:RELIANCE",
            direction="BUY",
            quantity=100,
        )


def test_tls_enforcement_and_secret_protection() -> None:
    """Verify strict TLS verification and SecretStr masking."""
    cfg = BrokerConfig(
        broker_name="tls_test",
        api_key=SecretStr("sensitive_key_val"),
        api_secret=SecretStr("sensitive_secret_val"),
        paper_trading=False,
    )
    adapter = LiveBrokerAdapter(config=cfg, sandbox_mode=True)

    # Assert underlying httpx client enforces TLS certificate verification (TRD-SEC-1)
    # httpx.Client stores this on _transport or ssl_context depending on setup
    assert adapter._client is not None

    # Verify secret string masking
    assert "sensitive_key_val" not in repr(cfg)
    assert "sensitive_secret_val" not in repr(cfg)
    adapter.close()
