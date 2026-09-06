# Data Design Document (DDD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Data Design Document (DDD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | Agent 04 — Data Engineering Agent |
| **Prepared by** | Agent 04 (Data Engineering Agent) / Agent 00 (Chief Architect) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, FRD v0.1 (Module 1, 2, 9, 10), TRD v0.1 (§6, §7), HLD v0.1 (§6, §7, §9, §15), TTD v0.1 (§6) |

---

## 1. Purpose of This Document

The PRD, FRD, TRD, HLD, ADD, MLD, and LLD all cross-reference the **canonical data architecture and entity schemas** defined in this document. This Data Design Document (DDD) specifies:
1. The **data models and schemas** for market data ingestion (OHLCV, tick, market depth, derivatives, corporate actions).
2. The **canonical domain entities**: `DecisionRecord`, `TradeEvaluation`, `Position`, `OrderSubmission`, `ModelVersion`, `ValidationRunRecord`, `PromotionEvent`, `FeatureSet`, and `RegimeClassification`.
3. The **point-in-time data architecture** that structurally eliminates look-ahead and survivorship bias (BTD §5, TRD-PIPE-3).
4. The **hybrid storage architecture**: PostgreSQL with TimescaleDB extension for transactional state and real-time/recent time-series, and partitioned Parquet files for bulk historical analytics and backtesting (TTD §6).
5. The **data quality, validation, staleness, and quarantine framework** (FRD-DATA-6/7/9).

---

## 2. Governing Principles

| Principle | Source |
|---|---|
| Point-in-Time Integrity: Data returned for any historical query must reflect strictly what was available before the query timestamp. | BTD §5.2; NFR-DATA-3 |
| Immutability: Decision records, trade evaluations, and audit logs are append-only; in-place edits and deletions are prohibited. | TRD-DATA-3; NFR-DATA-4 |
| Single Data Contract: The exact same data schemas and validation models serve both streaming live trading and historical backtesting. | TRD-PIPE-3; FRD-FEAT-4 |
| Transactional Consistency: Order lifecycle events and position updates must apply with full ACID transactional integrity. | TRD-DATA-2; EDD §8 |
| Explicit Data Quality States: Data is explicitly tagged as `RAW`, `VALIDATED`, `STALE`, or `QUARANTINED`. Quarantined data is suppressed from decision-making. | FRD-DATA-7/9; HLD §7 |

---

## 3. Storage Architecture Topology

```
                  ┌──────────────────────────────────────────────────────────┐
                  │                 Data Ingestion Pipeline                  │
                  │        (WebSocket streaming / REST bulk ingestion)       │
                  └─────────────┬─────────────────────────────┬──────────────┘
                                │                             │
                                ▼                             ▼
                    ┌──────────────────────┐      ┌──────────────────────┐
                    │ PostgreSQL 16+ /     │      │ Partitioned Parquet  │
                    │ TimescaleDB          │      │ Historical Archive   │
                    │                      │      │                      │
                    │ - Real-time OHLCV    │      │ - Multi-year OHLCV   │
                    │ - Positions & Orders │      │ - Historical Ticks   │
                    │ - Decision Records   │      │ - Feature Store Cache│
                    │ - Model Registry     │      │ - Point-in-time index│
                    └──────────────────────┘      └──────────────────────┘
                               ▲                             ▲
                               │ (ACID read/write)           │ (Fast columnar scan)
                    ┌──────────┴───────────┐      ┌──────────┴───────────┐
                    │    Trading Brain     │      │    Research Brain    │
                    │     (live/paper)     │      │  (backtesting / ML)  │
                    └──────────────────────┘      └──────────────────────┘
```

---

## 4. Market Data Schemas

All market data timestamps are strictly **UTC** ISO-8601 with microsecond resolution.

### 4.1 OHLCV Candle Model
```python
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

class OHLCVCandle(BaseModel):
    instrument: str = Field(..., description="NSE symbol, e.g. NSE:RELIANCE, NSE:NIFTY50")
    timeframe: str = Field(..., description="1m, 5m, 15m, 1h, 1d")
    timestamp: datetime = Field(..., description="Candle start timestamp in UTC")
    open: Decimal = Field(..., gt=0)
    high: Decimal = Field(..., gt=0)
    low: Decimal = Field(..., gt=0)
    close: Decimal = Field(..., gt=0)
    volume: int = Field(..., ge=0)
    turnover: Decimal = Field(default=Decimal(0), ge=0, description="Total traded value in INR")
    open_interest: int | None = Field(default=None, ge=0, description="Applicable for derivatives")
    quality_state: Literal["RAW", "VALIDATED", "STALE", "QUARANTINED"] = "RAW"
```

### 4.2 Tick & Market Depth Model
```python
class MarketDepthLevel(BaseModel):
    price: Decimal
    quantity: int
    orders_count: int | None = None

class MarketDepthQuote(BaseModel):
    instrument: str
    timestamp: datetime
    bids: list[MarketDepthLevel] = Field(..., max_length=5)
    asks: list[MarketDepthLevel] = Field(..., max_length=5)
    last_price: Decimal
    last_quantity: int
    volume_traded_today: int
    quality_state: Literal["RAW", "VALIDATED", "STALE", "QUARANTINED"] = "RAW"
```

### 4.3 Corporate Actions & Adjustments Model
```python
class CorporateAction(BaseModel):
    instrument: str
    action_type: Literal["DIVIDEND", "SPLIT", "BONUS", "RIGHTS"]
    ex_date: datetime
    record_date: datetime | None
    ratio_from: Decimal | None
    ratio_to: Decimal | None
    dividend_amount: Decimal | None
    adjustment_factor: Decimal = Field(..., description="Multiplier applied to historical prices")
```

---

## 5. Canonical Domain Entities

### 5.1 FeatureSet Entity (DDD §5.1)
```python
class FeatureSet(BaseModel):
    feature_set_id: str
    instrument: str
    timeframe: str
    as_of_timestamp: datetime = Field(..., description="Decision bar close timestamp (strictly point-in-time)")
    version: str = Field(..., description="Feature engineering definition version, e.g. v1.0.0")
    features: dict[str, float] = Field(..., description="Key-value mapping of computed features")
```

### 5.2 DecisionRecord Entity (DDD §5.2, Master Audit Record)
```python
class DecisionRecord(BaseModel):
    decision_record_id: str = Field(..., description="Unique UUID: aitrader-dec-YYYYMMDD-UUID")
    timestamp: datetime = Field(..., description="UTC evaluation timestamp")
    instrument: str
    timeframe: str
    environment: Literal["research", "paper", "live"]

    # 1. Ingested Data Quality State
    data_quality_state: Literal["VALIDATED", "STALE", "QUARANTINED"]

    # 2. Market Regime Context
    regime_classification: dict = Field(..., description="Trend, Volatility, Directional Bias, Liquidity")

    # 3. Agent Roster Outputs
    agent_outputs: list[dict] = Field(..., description="List of AgentSignalOutput objects (direction, confidence, inputs)")

    # 4. Aggregator Output
    trade_quality_score: float
    expected_value: Decimal
    disagreement_metric: float

    # 5. Risk Engine Evaluation
    risk_check_passed: bool
    failed_check: str | None
    rtld_param_id: str | None
    risk_config_version: str

    # 6. Final Decision & Execution Linkage
    final_decision: Literal["BUY", "SELL", "HOLD", "NO_TRADE"]
    decision_rationale: str
    client_order_id: str | None = None
    model_version_id: str
```

### 5.3 TradeEvaluation Entity (DDD §5.3)
```python
class TradeEvaluation(BaseModel):
    evaluation_id: str
    decision_record_id: str
    instrument: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    realized_pnl: Decimal
    gross_pnl: Decimal
    total_cost_drag: Decimal = Field(..., description="Brokerage + STT + Taxes + Slippage")
    expected_pnl: Decimal
    pnl_variance: Decimal
    variance_driver: Literal[
        "good_trade",
        "bad_signal",
        "bad_timing",
        "bad_sizing",
        "bad_execution",
        "unexpected_event",
        "regime_change",
        "data_problem",
        "model_problem"
    ]
    evaluation_notes: str
```

### 5.4 Model Governance Entities (DDD §5.4)
```python
class ModelVersion(BaseModel):
    model_version_id: str = Field(..., description="e.g. model-trend-v1.2.0")
    agent_id: str = Field(..., description="trend, momentum, mean_reversion, price_action")
    architecture_type: Literal["rule_based", "statistical", "classical_ml", "rl"]
    created_at: datetime
    git_commit_hash: str
    artifact_storage_path: str
    artifact_sha256: str
    status: Literal["candidate", "in_validation", "validated", "pending_review", "promoted", "superseded", "rolled_back"]
    active_in_production: bool = False

class ValidationRunRecord(BaseModel):
    validation_run_id: str
    model_version_id: str
    stage: Literal["backtest", "out_of_sample", "walk_forward", "stress", "robustness", "paper_trading"]
    start_date: datetime
    end_date: datetime
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    walk_forward_efficiency_ratio: float | None
    trade_count: int
    passed_stage: bool
    evidence_payload_json: str

class PromotionEvent(BaseModel):
    promotion_event_id: str
    model_version_id: str
    prior_model_version_id: str | None
    promoted_at: datetime
    promoted_by: str = Field(..., description="System / Operator ID")
    validation_evidence_ref: str
    human_signoff_ref: str | None
```

### 5.5 Position & Order Entities (DDD §5.5)
```python
class OrderSubmission(BaseModel):
    client_order_id: str = Field(..., description="aitrader-{decision_record_id}")
    broker_order_id: str | None
    decision_record_id: str
    instrument: str
    direction: Literal["BUY", "SELL"]
    order_type: Literal["LIMIT", "MARKET"]
    limit_price: Decimal | None
    quantity: int
    filled_quantity: int = 0
    average_fill_price: Decimal = Decimal(0)
    status: Literal["PENDING", "SUBMITTED", "FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED"]
    rejection_reason: str | None
    submitted_at: datetime
    updated_at: datetime

class Position(BaseModel):
    instrument: str
    quantity: int
    average_entry_price: Decimal
    current_market_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    peak_unrealized_pnl: Decimal
    opened_at: datetime
    last_updated_at: datetime
```

---

## 6. PostgreSQL Relational & TimescaleDB Schema (DDL)

```sql
-- Core Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Market Data Hypertables
CREATE TABLE ohlcv_candles (
    timestamp TIMESTAMPTZ NOT NULL,
    instrument VARCHAR(64) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    open NUMERIC(18, 4) NOT NULL,
    high NUMERIC(18, 4) NOT NULL,
    low NUMERIC(18, 4) NOT NULL,
    close NUMERIC(18, 4) NOT NULL,
    volume BIGINT NOT NULL,
    turnover NUMERIC(18, 4) DEFAULT 0,
    open_interest BIGINT,
    quality_state VARCHAR(16) NOT NULL DEFAULT 'RAW',
    PRIMARY KEY (instrument, timeframe, timestamp)
);
SELECT create_hypertable('ohlcv_candles', 'timestamp', if_not_exists => TRUE);

-- Immutable Decision Records
CREATE TABLE decision_records (
    decision_record_id VARCHAR(128) PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    instrument VARCHAR(64) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    environment VARCHAR(16) NOT NULL,
    data_quality_state VARCHAR(16) NOT NULL,
    regime_classification JSONB NOT NULL,
    agent_outputs JSONB NOT NULL,
    trade_quality_score DOUBLE PRECISION NOT NULL,
    expected_value NUMERIC(18, 4) NOT NULL,
    disagreement_metric DOUBLE PRECISION NOT NULL,
    risk_check_passed BOOLEAN NOT NULL,
    failed_check VARCHAR(64),
    rtld_param_id VARCHAR(32),
    risk_config_version VARCHAR(64) NOT NULL,
    final_decision VARCHAR(16) NOT NULL,
    decision_rationale TEXT NOT NULL,
    client_order_id VARCHAR(128),
    model_version_id VARCHAR(128) NOT NULL
);
CREATE INDEX idx_dec_inst_time ON decision_records (instrument, timestamp DESC);
CREATE INDEX idx_dec_decision ON decision_records (final_decision, timestamp DESC);

-- Immutable Trade Evaluations
CREATE TABLE trade_evaluations (
    evaluation_id VARCHAR(128) PRIMARY KEY,
    decision_record_id VARCHAR(128) REFERENCES decision_records(decision_record_id),
    instrument VARCHAR(64) NOT NULL,
    entry_timestamp TIMESTAMPTZ NOT NULL,
    exit_timestamp TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(18, 4) NOT NULL,
    exit_price NUMERIC(18, 4) NOT NULL,
    quantity INT NOT NULL,
    realized_pnl NUMERIC(18, 4) NOT NULL,
    gross_pnl NUMERIC(18, 4) NOT NULL,
    total_cost_drag NUMERIC(18, 4) NOT NULL,
    expected_pnl NUMERIC(18, 4) NOT NULL,
    pnl_variance NUMERIC(18, 4) NOT NULL,
    variance_driver VARCHAR(32) NOT NULL,
    evaluation_notes TEXT
);

-- Model Registry Tables
CREATE TABLE model_versions (
    model_version_id VARCHAR(128) PRIMARY KEY,
    agent_id VARCHAR(64) NOT NULL,
    architecture_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    git_commit_hash VARCHAR(64) NOT NULL,
    artifact_storage_path TEXT NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    active_in_production BOOLEAN DEFAULT FALSE
);

CREATE TABLE validation_runs (
    validation_run_id VARCHAR(128) PRIMARY KEY,
    model_version_id VARCHAR(128) REFERENCES model_versions(model_version_id),
    stage VARCHAR(32) NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    sharpe_ratio DOUBLE PRECISION NOT NULL,
    sortino_ratio DOUBLE PRECISION NOT NULL,
    max_drawdown_pct DOUBLE PRECISION NOT NULL,
    profit_factor DOUBLE PRECISION NOT NULL,
    walk_forward_efficiency_ratio DOUBLE PRECISION,
    trade_count INT NOT NULL,
    passed_stage BOOLEAN NOT NULL,
    evidence_payload_json JSONB NOT NULL
);

-- Positions & Orders
CREATE TABLE order_submissions (
    client_order_id VARCHAR(128) PRIMARY KEY,
    broker_order_id VARCHAR(128),
    decision_record_id VARCHAR(128) REFERENCES decision_records(decision_record_id),
    instrument VARCHAR(64) NOT NULL,
    direction VARCHAR(8) NOT NULL,
    order_type VARCHAR(16) NOT NULL,
    limit_price NUMERIC(18, 4),
    quantity INT NOT NULL,
    filled_quantity INT DEFAULT 0,
    average_fill_price NUMERIC(18, 4) DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    rejection_reason TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE positions (
    instrument VARCHAR(64) PRIMARY KEY,
    quantity INT NOT NULL,
    average_entry_price NUMERIC(18, 4) NOT NULL,
    current_market_price NUMERIC(18, 4) NOT NULL,
    unrealized_pnl NUMERIC(18, 4) NOT NULL,
    realized_pnl NUMERIC(18, 4) NOT NULL,
    peak_unrealized_pnl NUMERIC(18, 4) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL
);
```

---

## 7. Data Quality & Quarantine Policy

```python
class DataValidationPipeline:
    @staticmethod
    def validate_ohlcv(candle: OHLCVCandle, previous_candle: OHLCVCandle | None = None) -> OHLCVCandle:
        # Rule 1: Physical price sanity
        if not (candle.low <= candle.open <= candle.high and candle.low <= candle.close <= candle.high):
            candle.quality_state = "QUARANTINED"
            return candle

        # Rule 2: Non-negative volume
        if candle.volume < 0:
            candle.quality_state = "QUARANTINED"
            return candle

        # Rule 3: Extreme price spike (e.g. >20% single-minute gap on cash equities)
        if previous_candle and previous_candle.close > 0:
            pct_change = abs(candle.close - previous_candle.close) / previous_candle.close
            if pct_change > Decimal("0.20"):
                candle.quality_state = "QUARANTINED"
                return candle

        candle.quality_state = "VALIDATED"
        return candle
```

---

## 8. Data Lineage and Traceability
Every trading decision points to its exact `FeatureSet`, which points to the underlying `OHLCVCandle`s, which point to the vendor raw ingestion timestamp. This creates an unbroken, auditable chain from raw market tick to realized P&L.
