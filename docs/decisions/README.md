# Architecture Decision Records (ADRs)

This directory contains the formal record of architectural, technical, and trading-logic decisions for **AI Trader — Autonomous Intelligent Trading System**.

## Index of Decisions

| ADR ID | Title | Status | Date | Decision Summary |
|---|---|---|---|---|
| [ADR-0001](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/decisions/adr-0001-modular-monolith-architecture.md) | Modular Monolith Architecture for Trading Brain with Decoupled Research Brain | Accepted | 2026-08-29 | Adopt a modular monolith for the Trading Brain and physically isolate the Research Brain deployment. |
| [ADR-0002](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/decisions/adr-0002-technology-stack-python-postgres.md) | Unified Python 3.12+ and PostgreSQL / TimescaleDB Technology Stack | Accepted | 2026-08-29 | Select Python 3.12+, PostgreSQL + TimescaleDB, and Parquet for the core platform. |
| [ADR-0003](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/decisions/adr-0003-safety-critical-isolation.md) | Deterministic Minimal-Dependency Isolation of the Safety-Critical Path | Accepted | 2026-08-29 | Isolate Risk Engine, Supervisor, and Kill Switch with zero AI/LLM/broker dependencies and 100% branch test coverage. |
| [ADR-0004](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/decisions/adr-0004-rule-based-initial-agent-roster.md) | Rule-Based / Statistical Initial 4-Agent Trading Roster | Accepted | 2026-08-29 | Initialize V3 multi-agent trading with 4 rule-based/statistical agents (Trend, Momentum, Mean-Reversion, Price Action). |
