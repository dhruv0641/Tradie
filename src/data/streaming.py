"""Real-time asynchronous WebSocket streaming pipeline with auto-reconnection."""

import asyncio
import contextlib
import json
import random
import ssl
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect

from src.data.aggregator import CandleAggregator
from src.domain.market_data import MarketDepthLevel, MarketDepthQuote, MarketTick

logger = structlog.get_logger(__name__)

TickCallback = Callable[[MarketTick], Coroutine[Any, Any, None] | None]
DepthCallback = Callable[[MarketDepthQuote], Coroutine[Any, Any, None] | None]
StatusCallback = Callable[[str], Coroutine[Any, Any, None] | None]


class WebSocketFeedHandler:
    """WebSocket feed handler for Indian market data streams (TRD-PIPE-3, NFR-REL-4).

    Features:
    - Asynchronous TLS WebSocket connection management.
    - Automated heartbeat ping-pong monitoring.
    - Exponential backoff reconnection with jitter.
    - Status alerting ('CONNECTED', 'DISCONNECTED', 'STALE', 'RECONNECTING').
    - Subscription state preservation across reconnects.
    - Real-time tick aggregation bridge to CandleAggregator.
    """

    def __init__(
        self,
        endpoint_url: str,
        *,
        auth_token: str | None = None,
        ping_interval: float = 10.0,
        ping_timeout: float = 5.0,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
        backoff_factor: float = 2.0,
        candle_aggregator: CandleAggregator | None = None,
        ssl_context: ssl.SSLContext | None = None,
        open_timeout: float = 5.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.auth_token = auth_token
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.initial_reconnect_delay = initial_reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.backoff_factor = backoff_factor
        self.candle_aggregator = candle_aggregator
        self.ssl_context = ssl_context
        self.open_timeout = open_timeout

        self._subscribed_instruments: set[str] = set()
        self._tick_callbacks: list[TickCallback] = []
        self._depth_callbacks: list[DepthCallback] = []
        self._status_callbacks: list[StatusCallback] = []

        self._running: bool = False
        self._is_connected: bool = False
        self._reconnect_attempts: int = 0
        self._websocket: ClientConnection | None = None

        self._main_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket connection is active and healthy."""
        return self._is_connected

    @property
    def subscribed_instruments(self) -> set[str]:
        """Return current set of subscribed instrument symbols."""
        return set(self._subscribed_instruments)

    def register_tick_callback(self, callback: TickCallback) -> None:
        """Add listener for real-time market trade ticks."""
        self._tick_callbacks.append(callback)

    def register_depth_callback(self, callback: DepthCallback) -> None:
        """Add listener for Level 2 order book depth quotes."""
        self._depth_callbacks.append(callback)

    def register_status_callback(self, callback: StatusCallback) -> None:
        """Add listener for connection status changes."""
        self._status_callbacks.append(callback)

    def subscribe(self, instruments: list[str]) -> None:
        """Register instruments for real-time market data subscription."""
        canonical_symbols = [s.strip().upper() for s in instruments if s.strip()]
        self._subscribed_instruments.update(canonical_symbols)

        if self._is_connected and self._websocket is not None:
            # Fire non-blocking subscription message and keep reference
            task = asyncio.create_task(self._send_subscription(canonical_symbols))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    def unsubscribe(self, instruments: list[str]) -> None:
        """Unsubscribe instruments from real-time market data stream."""
        for s in instruments:
            self._subscribed_instruments.discard(s.strip().upper())

    async def start(self) -> None:
        """Start the background connection and ingestion pipeline."""
        if self._running:
            return
        self._running = True
        self._main_task = asyncio.create_task(self._connection_loop())
        logger.info("websocket_feed_handler_started", endpoint=self.endpoint_url)

    async def stop(self) -> None:
        """Gracefully stop connection, cancel background tasks, and close sockets."""
        if not self._running:
            return
        self._running = False
        self._is_connected = False

        # Cancel heartbeat task
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        # Close active WebSocket
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.warning("websocket_close_error", error=str(e))
            self._websocket = None

        # Cancel main loop task
        if self._main_task is not None and not self._main_task.done():
            self._main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._main_task
            self._main_task = None

        await self._dispatch_status("DISCONNECTED")
        logger.info("websocket_feed_handler_stopped")

    async def _connection_loop(self) -> None:
        """Main lifecycle loop handling initial connection and auto-reconnection with backoff."""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("websocket_connection_failed", error=str(e))

            # Mark stale and calculate backoff delay
            self._is_connected = False
            await self._dispatch_status("STALE")
            await self._dispatch_status("RECONNECTING")

            delay = min(
                self.max_reconnect_delay,
                self.initial_reconnect_delay * (self.backoff_factor**self._reconnect_attempts),
            )
            # Add uniform jitter
            jitter = random.uniform(0.0, 0.5 * delay)
            total_delay = delay + jitter
            self._reconnect_attempts += 1

            logger.info(
                "websocket_reconnecting_after_delay",
                delay=round(total_delay, 2),
                attempt=self._reconnect_attempts,
            )
            try:
                await asyncio.sleep(total_delay)
            except asyncio.CancelledError:
                break

    async def _connect_and_listen(self) -> None:
        """Establish WebSocket connection, start heartbeat monitor, and process messages."""
        headers: dict[str, str] = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        async with ws_connect(
            self.endpoint_url,
            additional_headers=headers if headers else None,
            ssl=self.ssl_context,
            open_timeout=self.open_timeout,
            ping_interval=None,  # We manage application-level ping-pong explicitly
        ) as ws:
            self._websocket = ws
            self._is_connected = True
            self._reconnect_attempts = 0
            await self._dispatch_status("CONNECTED")
            logger.info("websocket_connected", endpoint=self.endpoint_url)

            # Re-subscribe existing instruments
            if self._subscribed_instruments:
                await self._send_subscription(list(self._subscribed_instruments))

            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                async for message in ws:
                    if not self._running:
                        break
                    await self._handle_raw_message(message)
            finally:
                if self._heartbeat_task and not self._heartbeat_task.done():
                    self._heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._heartbeat_task
                self._is_connected = False

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeat pings and verify pong responses."""
        while self._running:
            try:
                await asyncio.sleep(self.ping_interval)
            except asyncio.CancelledError:
                break

            ws = self._websocket
            if not self._is_connected or ws is None:
                break

            try:
                # Send ping message or protocol ping
                ping_payload = json.dumps(
                    {"type": "ping", "timestamp": datetime.now(UTC).isoformat()}
                )
                await ws.send(ping_payload)
            except Exception as e:
                logger.warning("heartbeat_failed", error=str(e))
                if self._websocket:
                    await self._websocket.close()
                break

    async def _send_subscription(self, instruments: list[str]) -> None:
        """Send subscription payload to WebSocket feed."""
        if not self._websocket or not self._is_connected:
            return
        payload = json.dumps({"action": "subscribe", "instruments": instruments})
        try:
            await self._websocket.send(payload)
            logger.debug("subscription_sent", count=len(instruments))
        except Exception as e:
            logger.warning("subscription_send_failed", error=str(e))

    async def _handle_raw_message(self, message: str | bytes) -> None:
        """Decode and parse incoming message into domain models."""
        try:
            text = message.decode("utf-8") if isinstance(message, bytes) else message
            data = json.loads(text)
        except Exception as e:
            logger.warning("malformed_websocket_payload", error=str(e))
            return

        msg_type = data.get("type", "tick")

        if msg_type == "tick":
            tick = self._parse_tick(data)
            if tick:
                await self._dispatch_tick(tick)
        elif msg_type in ("depth", "quote"):
            depth = self._parse_depth(data)
            if depth:
                await self._dispatch_depth(depth)
        elif msg_type == "pong":
            logger.debug("heartbeat_pong_received")

    def _parse_tick(self, data: dict[str, Any]) -> MarketTick | None:
        """Parse raw payload dictionary into a validated MarketTick entity."""
        try:
            raw_ts = data.get("timestamp")
            if isinstance(raw_ts, str):
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            elif isinstance(raw_ts, int | float):
                ts = datetime.fromtimestamp(raw_ts, tz=UTC)
            else:
                ts = datetime.now(UTC)

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            return MarketTick(
                instrument=str(data["instrument"]).strip().upper(),
                timestamp=ts,
                last_price=Decimal(str(data["last_price"])),
                volume=int(data.get("volume", 0)),
                turnover=Decimal(str(data.get("turnover", 0))),
                bid_price=Decimal(str(data["bid_price"])) if "bid_price" in data else None,
                ask_price=Decimal(str(data["ask_price"])) if "ask_price" in data else None,
            )
        except Exception as e:
            logger.warning("tick_parse_failed", payload=data, error=str(e))
            return None

    def _parse_depth(self, data: dict[str, Any]) -> MarketDepthQuote | None:
        """Parse raw payload dictionary into a validated MarketDepthQuote entity."""
        try:
            raw_ts = data.get("timestamp")
            if isinstance(raw_ts, str):
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            else:
                ts = datetime.now(UTC)

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            bids = [
                MarketDepthLevel(
                    price=Decimal(str(b["price"])),
                    quantity=int(b["quantity"]),
                    orders_count=int(b.get("orders_count", 1)),
                )
                for b in data.get("bids", [])
            ]
            asks = [
                MarketDepthLevel(
                    price=Decimal(str(a["price"])),
                    quantity=int(a["quantity"]),
                    orders_count=int(a.get("orders_count", 1)),
                )
                for a in data.get("asks", [])
            ]

            return MarketDepthQuote(
                instrument=str(data["instrument"]).strip().upper(),
                timestamp=ts,
                bids=bids,
                asks=asks,
            )
        except Exception as e:
            logger.warning("depth_parse_failed", payload=data, error=str(e))
            return None

    async def _dispatch_tick(self, tick: MarketTick) -> None:
        """Forward tick to CandleAggregator and registered listeners."""
        if self.candle_aggregator:
            self.candle_aggregator.process_tick(tick)

        for cb in self._tick_callbacks:
            try:
                res = cb(tick)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("tick_callback_failed", instrument=tick.instrument, error=str(e))

    async def _dispatch_depth(self, depth: MarketDepthQuote) -> None:
        """Forward depth quote to registered listeners."""
        for cb in self._depth_callbacks:
            try:
                res = cb(depth)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("depth_callback_failed", instrument=depth.instrument, error=str(e))

    async def _dispatch_status(self, status: str) -> None:
        """Forward status change to registered listeners."""
        for cb in self._status_callbacks:
            try:
                res = cb(status)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("status_callback_failed", status=status, error=str(e))
