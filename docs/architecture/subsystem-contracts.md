# Subsystem Interface Contracts

## AI Trader — Baseline v1.0

This document defines the formal, typed interface protocols binding the major subsystems of the AI Trader architecture.

---

## 1. Market Data Adapter Contract (`DataSourceAdapter`)

```python
from typing import Protocol, AsyncIterator
from datetime import datetime
from docs.ddd import OHLCVCandle, MarketDepthQuote

class DataSourceAdapter(Protocol):
    """Abstract interface for all market data providers (TRD-PIPE-1, HLD §9)."""

    async def connect(self) -> None:
        """Establish streaming connection to vendor API."""
        ...

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        ...

    async def subscribe_candles(self, instruments: list[str], timeframe: str) -> AsyncIterator[OHLCVCandle]:
        """Stream real-time closed/updated OHLCV candles."""
        ...

    async def subscribe_depth(self, instruments: list[str]) -> AsyncIterator[MarketDepthQuote]:
        """Stream real-time Level-2 market depth quotes."""
        ...

    def fetch_historical_candles(
        self, instrument: str, timeframe: str, start_time: datetime, end_time: datetime
    ) -> list[OHLCVCandle]:
        """Fetch bulk historical candles strictly point-in-time."""
        ...
```

---

## 2. Trading Agent Contract (`TradingAgent`)

```python
from typing import Protocol
from docs.ddd import FeatureSet, RegimeClassification

class AgentSignalOutput:
    agent_id: str
    direction: str  # "LONG", "SHORT", "NO_VIEW"
    confidence: float  # Bounded in [0.0, 1.0]
    inputs_used: dict
    timestamp: datetime

class TradingAgent(Protocol):
    """Uniform contract for all trading intelligence agents (ADD §4, LLD §8.1)."""

    agent_id: str

    def evaluate(
        self,
        instrument: str,
        timeframe: str,
        features: FeatureSet,
        regime: RegimeClassification,
    ) -> AgentSignalOutput:
        """Compute directional signal and normalized confidence."""
        ...
```

---

## 3. Risk Engine Contract (`RiskEngineInterface`)

```python
from typing import Protocol
from docs.ddd import CandidateTrade, CapitalState, StreakState, MarketState, RiskCheckResult

class RiskEngineInterface(Protocol):
    """Deterministic, fail-fast risk evaluation interface (HLD §8, LLD §5)."""

    def evaluate(
        self,
        candidate: CandidateTrade,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
    ) -> RiskCheckResult:
        """Evaluate full deterministic checklist; return pass/fail with exact RTLD param ID."""
        ...
```

---

## 4. Supervisor Decision Gate Contract (`SupervisorInterface`)

```python
from typing import Protocol
from docs.ddd import CandidateTrade, CapitalState, StreakState, MarketState, Decision

class SupervisorInterface(Protocol):
    """Master decision gating interface (HLD §7, LLD §7)."""

    def decide(
        self,
        candidate: CandidateTrade | None,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
        has_open_position: bool,
    ) -> Decision:
        """Constrain output strictly to BUY, SELL, HOLD, or NO_TRADE."""
        ...
```

---

## 5. Broker Adapter Contract (`BrokerAdapter`)

```python
from typing import Protocol
from decimal import Decimal
from docs.ddd import OrderSubmission, Position

class BrokerAdapter(Protocol):
    """Abstract interface for all broker integrations (TRD-EXEC-1/4, HLD §9, EDD §5)."""

    def authenticate(self) -> bool:
        """Authenticate session with broker."""
        ...

    def place_order(
        self,
        client_order_id: str,
        instrument: str,
        direction: str,
        quantity: int,
        price: Decimal | None,
        order_type: str,
    ) -> OrderSubmission:
        """Submit order with idempotent client_order_id."""
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel working order."""
        ...

    def get_positions(self) -> list[Position]:
        """Fetch broker-reported open positions for reconciliation."""
        ...

    def get_order_status(self, client_order_id: str) -> OrderSubmission:
        """Query status of specific order."""
        ...
```
