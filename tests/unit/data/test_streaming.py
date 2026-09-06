"""Unit and integration tests for WebSocketFeedHandler streaming market data pipeline."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import websockets
from websockets.asyncio.server import ServerConnection, serve

from src.data.aggregator import CandleAggregator
from src.data.streaming import WebSocketFeedHandler
from src.domain.market_data import MarketDepthQuote, MarketTick


def test_feed_handler_initialization() -> None:
    """Verify default configurations and properties of WebSocketFeedHandler."""
    handler = WebSocketFeedHandler(
        endpoint_url="wss://mock.feed.in/stream",
        auth_token="test_jwt_token",
        ping_interval=5.0,
        ping_timeout=2.0,
    )
    assert handler.endpoint_url == "wss://mock.feed.in/stream"
    assert handler.auth_token == "test_jwt_token"
    assert handler.is_connected is False
    assert handler.subscribed_instruments == set()


def test_feed_handler_subscriptions() -> None:
    """Verify subscription tracking and canonical symbol normalization."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    handler.subscribe(["nse:reliance", "  NSE:TCS  "])
    assert handler.subscribed_instruments == {"NSE:RELIANCE", "NSE:TCS"}

    handler.unsubscribe(["NSE:RELIANCE"])
    assert handler.subscribed_instruments == {"NSE:TCS"}


def test_feed_handler_parse_tick_valid() -> None:
    """Verify parsing of valid raw dictionary into MarketTick domain model."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    data = {
        "instrument": "NSE:INFY",
        "timestamp": "2025-01-15T09:15:30Z",
        "last_price": "1620.50",
        "volume": 500,
        "turnover": "810250.00",
        "bid_price": "1620.25",
        "ask_price": "1620.75",
    }
    tick = handler._parse_tick(data)
    assert tick is not None
    assert tick.instrument == "NSE:INFY"
    assert tick.timestamp == datetime(2025, 1, 15, 9, 15, 30, tzinfo=UTC)
    assert tick.last_price == Decimal("1620.50")
    assert tick.volume == 500
    assert tick.turnover == Decimal("810250.00")
    assert tick.bid_price == Decimal("1620.25")
    assert tick.ask_price == Decimal("1620.75")


def test_feed_handler_parse_tick_numeric_timestamp() -> None:
    """Verify parsing tick with numeric unix epoch timestamp."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    data = {
        "instrument": "NSE:SBIN",
        "timestamp": 1736932530,  # unix epoch
        "last_price": "750.00",
        "volume": 100,
    }
    tick = handler._parse_tick(data)
    assert tick is not None
    assert tick.instrument == "NSE:SBIN"
    assert tick.timestamp.tzinfo == UTC
    assert tick.last_price == Decimal("750.00")


def test_feed_handler_parse_tick_no_timestamp() -> None:
    """Verify tick parsing defaults to current UTC time if timestamp field is omitted."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    data = {
        "instrument": "NSE:SBIN",
        "last_price": "750.00",
    }
    tick = handler._parse_tick(data)
    assert tick is not None
    assert tick.instrument == "NSE:SBIN"
    assert tick.timestamp.tzinfo == UTC


def test_feed_handler_parse_tick_invalid() -> None:
    """Verify that corrupt or unparseable tick returns None safely."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    # Missing last_price
    assert handler._parse_tick({"instrument": "NSE:SBIN"}) is None
    # Invalid numeric conversion
    assert handler._parse_tick({"instrument": "NSE:SBIN", "last_price": "NOT_A_PRICE"}) is None


def test_feed_handler_parse_depth_valid() -> None:
    """Verify parsing Level 2 order book snapshot into MarketDepthQuote."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    data = {
        "instrument": "NSE:RELIANCE",
        "timestamp": "2025-01-15T09:15:30Z",
        "bids": [
            {"price": "2500.00", "quantity": 100, "orders_count": 2},
            {"price": "2499.50", "quantity": 250, "orders_count": 5},
        ],
        "asks": [
            {"price": "2500.50", "quantity": 150, "orders_count": 3},
            {"price": "2501.00", "quantity": 300, "orders_count": 4},
        ],
    }
    depth = handler._parse_depth(data)
    assert depth is not None
    assert depth.instrument == "NSE:RELIANCE"
    assert len(depth.bids) == 2
    assert len(depth.asks) == 2
    assert depth.bids[0].price == Decimal("2500.00")
    assert depth.asks[0].price == Decimal("2500.50")


def test_feed_handler_parse_depth_invalid() -> None:
    """Verify invalid depth payload returns None safely."""
    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")
    # Missing bids/asks
    assert handler._parse_depth({"instrument": "NSE:RELIANCE", "bids": "invalid"}) is None


@pytest.mark.asyncio
async def test_feed_handler_raw_message_routing() -> None:
    """Verify dispatching of raw JSON messages to tick, depth, and status callbacks."""
    received_ticks: list[MarketTick] = []
    received_depths: list[MarketDepthQuote] = []
    received_statuses: list[str] = []

    handler = WebSocketFeedHandler(endpoint_url="wss://mock.feed.in/stream")

    async def async_tick(t: MarketTick) -> None:
        received_ticks.append(t)

    async def async_depth(d: MarketDepthQuote) -> None:
        received_depths.append(d)

    async def async_status(s: str) -> None:
        received_statuses.append(s)

    handler.register_tick_callback(async_tick)
    handler.register_depth_callback(async_depth)
    handler.register_status_callback(async_status)

    # 1. Dispatch tick message
    tick_json = json.dumps(
        {
            "type": "tick",
            "instrument": "NSE:WIPRO",
            "timestamp": "2025-01-15T09:15:00Z",
            "last_price": "500.00",
            "volume": 20,
        }
    )
    await handler._handle_raw_message(tick_json)
    assert len(received_ticks) == 1
    assert received_ticks[0].instrument == "NSE:WIPRO"

    # 2. Dispatch bytes binary tick
    tick_bytes = json.dumps(
        {
            "type": "tick",
            "instrument": "NSE:WIPRO",
            "timestamp": "2025-01-15T09:15:01Z",
            "last_price": "501.00",
            "volume": 30,
        }
    ).encode("utf-8")
    await handler._handle_raw_message(tick_bytes)
    assert len(received_ticks) == 2

    # 3. Dispatch depth message
    depth_json = json.dumps(
        {
            "type": "depth",
            "instrument": "NSE:WIPRO",
            "timestamp": "2025-01-15T09:15:00Z",
            "bids": [{"price": "499.00", "quantity": 50}],
            "asks": [{"price": "501.00", "quantity": 50}],
        }
    )
    await handler._handle_raw_message(depth_json)
    assert len(received_depths) == 1
    assert received_depths[0].instrument == "NSE:WIPRO"

    # 4. Dispatch pong message (handled without error)
    await handler._handle_raw_message(json.dumps({"type": "pong"}))

    # 5. Dispatch invalid JSON (logged, no error)
    await handler._handle_raw_message("INVALID_JSON{")

    # 6. Dispatch status
    await handler._dispatch_status("CONNECTED")
    assert received_statuses == ["CONNECTED"]


@pytest.mark.asyncio
async def test_feed_handler_e2e_streaming_and_aggregation() -> None:
    """Integration test connecting WebSocketFeedHandler to a local async WebSocket server."""
    messages_received_by_server: list[dict[str, Any]] = []

    async def mock_ws_server(websocket: ServerConnection) -> None:
        try:
            async for raw in websocket:
                data = json.loads(raw)
                messages_received_by_server.append(data)

                if data.get("action") == "subscribe":
                    # Send back test ticks to client
                    t1 = {
                        "type": "tick",
                        "instrument": "NSE:RELIANCE",
                        "timestamp": "2025-01-15T09:15:10Z",
                        "last_price": "2500.00",
                        "volume": 100,
                    }
                    t2 = {
                        "type": "tick",
                        "instrument": "NSE:RELIANCE",
                        "timestamp": "2025-01-15T09:15:40Z",
                        "last_price": "2525.00",
                        "volume": 150,
                    }
                    t3 = {
                        "type": "tick",
                        "instrument": "NSE:RELIANCE",
                        "timestamp": "2025-01-15T09:16:05Z",  # crosses to next minute!
                        "last_price": "2510.00",
                        "volume": 50,
                    }
                    await websocket.send(json.dumps(t1))
                    await websocket.send(json.dumps(t2))
                    await websocket.send(json.dumps(t3))
        except websockets.ConnectionClosed:
            pass

    server = await serve(mock_ws_server, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]
    server_url = f"ws://127.0.0.1:{server_port}"

    aggregator = CandleAggregator(timeframes=["1m"])
    client = WebSocketFeedHandler(
        endpoint_url=server_url,
        auth_token="jwt_secret",
        candle_aggregator=aggregator,
        ping_interval=0.2,
        initial_reconnect_delay=0.1,
    )

    statuses: list[str] = []
    client.register_status_callback(statuses.append)

    client.subscribe(["NSE:RELIANCE"])
    await client.start()

    # Wait for connection, subscription, and message processing
    for _ in range(50):
        await asyncio.sleep(0.05)
        if len(aggregator.flush_closed_candles()) > 0 or aggregator.total_ticks_processed >= 3:
            break

    def is_online(handler: WebSocketFeedHandler) -> bool:
        return handler.is_connected

    assert is_online(client)
    assert "CONNECTED" in statuses

    # Verify that server received subscription payload
    assert any(m.get("action") == "subscribe" for m in messages_received_by_server)

    # Dynamic subscription while connected
    client.subscribe(["NSE:INFY"])
    await asyncio.sleep(0.05)
    assert "NSE:INFY" in client.subscribed_instruments

    # Dynamic unsubscription
    client.unsubscribe(["NSE:INFY"])
    assert "NSE:INFY" not in client.subscribed_instruments

    # Verify that ticks were forwarded and aggregated
    assert aggregator.total_ticks_processed >= 3

    # Check active bar
    active = aggregator.get_active_candle("NSE:RELIANCE", "1m")
    assert active is not None
    assert active.timestamp == datetime(2025, 1, 15, 9, 16, 0, tzinfo=UTC)
    assert active.close == Decimal("2510.00")

    # Stop client and server cleanly
    await client.stop()
    # Stopping an already stopped client is idempotent
    await client.stop()

    server.close()
    await server.wait_closed()

    assert not is_online(client)
    assert "DISCONNECTED" in statuses


@pytest.mark.asyncio
async def test_feed_handler_reconnection_loop() -> None:
    """Verify feed handler triggers reconnect status on connection failure."""
    statuses: list[str] = []

    # Connect to invalid port with fast backoff and fast open_timeout
    client = WebSocketFeedHandler(
        endpoint_url="ws://127.0.0.1:1",  # Guaranteed connection refused
        open_timeout=0.05,
        initial_reconnect_delay=0.05,
        backoff_factor=1.5,
        max_reconnect_delay=0.2,
    )
    client.register_status_callback(statuses.append)

    await client.start()
    # Allow reconnection attempts to fire
    for _ in range(30):
        if "STALE" in statuses:
            break
        await asyncio.sleep(0.05)

    await client.stop()

    assert "STALE" in statuses
    assert "RECONNECTING" in statuses
    assert client._reconnect_attempts >= 1
