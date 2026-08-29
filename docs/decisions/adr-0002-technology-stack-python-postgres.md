# ADR-0002: Unified Python 3.12+ and PostgreSQL / TimescaleDB Technology Stack

## Context & Problem Statement
We must choose the primary programming language, data storage engine, and core libraries for the AI Trader platform to satisfy the priority order: $\text{Reliability} > \text{Maintainability} > \text{Correctness} > \text{Observability} > \text{Performance} > \text{Scalability} > \text{Cost}$ (TRD §3).

## Decision
1. **Primary Language**: Standardize on **Python 3.12+** across the entire platform.
   - Enforce strict typing with `mypy --strict` and modern dataclasses (`@dataclass(frozen=True)`).
   - Use `uv` / `poetry` with locked manifests (`uv.lock`) for deterministic dependency management.
   - Use `ruff` for linting and formatting.
2. **Primary Storage**: **PostgreSQL 16+ with TimescaleDB extension**.
   - Serves both relational ACID transactions (positions, orders, decision records, model versions) and real-time/recent time-series hypertables (OHLCV, tick, depth).
3. **Bulk Historical Storage**: Partitioned **Parquet files**, read via DuckDB, Polars, and Pandas for high-speed columnar historical scans in backtesting.
4. **API Framework**: **FastAPI** for dashboard control plane and internal observability endpoints.
5. **Testing**: `pytest` with `pytest-cov`, known-answer fixtures, and failure injection.

## Consequences
### Positive
- Single-language ecosystem maximizes maintainability for a single operator.
- Direct access to the richest quantitative, ML, and broker SDK ecosystems.
- PostgreSQL ACID guarantees prevent partial state updates on position and order fills.
- Parquet provides compact, high-throughput historical backtesting.

### Negative / Risks
- Python is not sub-millisecond low-latency, which is acceptable because the system is non-HFT (5s decision latency budget, 2s order submission budget). Hot loops can be accelerated with NumPy/Polars/Numba.

## Status
Accepted (Derived from TTD §4, §6, §11, §14, §18).
