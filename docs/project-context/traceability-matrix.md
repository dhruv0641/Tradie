# Requirements Traceability Matrix (RTM)

## AI Trader — Baseline v1.0

| Upstream Req / Rule | Description | FRD Module / ID | Architecture / Design Ref | Implementation Component | Test Suite / Verification |
|---|---|---|---|---|---|
| **BR-1** | Capital Preservation Precedence | FRD-RISK-1–14, FRD-X-1 | RTLD §4–§12, HLD §8 | `RiskEngine`, `Supervisor` | `tests/risk_engine/`, KS-TEST-1 |
| **BR-2** | No Silent Capital Scaling | FRD-CAP-1–6 | RTLD §15, HLD §6 | `CapitalManager` | `tests/capital_manager/` |
| **BR-3** | NO TRADE Valid Outcome | FRD-AGG-4, FRD-SUP-3 | RTLD §13.2, ADD §4 | `Aggregator`, `Supervisor` | `tests/aggregator/` |
| **BR-4** | Deterministic Safety Independence | FRD-RISK-11, NFR-SAFE-1 | RTLD §2, HLD §8, LLD §5 | `RiskEngine`, `KillSwitch` | `tests/risk_engine/`, KS-TEST-2 |
| **BR-5** | Human Override & Emergency STOP | FRD-DASH-7, NFR-SAFE-2 | RTLD §16, HLD §8, LLD §6 | `KillSwitch`, Dashboard API | `tests/kill_switch/`, KS-TEST-1–4 |
| **BR-6** | No Unvalidated Model to Live Capital | FRD-LEARN-3–5, FRD-X-4 | ADD §8, MLD §9, HLD §10 | `LearningPipeline`, Model Registry | `tests/learning_pipeline/` |
| **BR-7** | Full Decision Auditability (100%) | FRD-EVAL-1–6, NFR-AUDIT-1 | DDD §5.2, HLD §7, LLD §3 | `EvaluationService`, `DecisionRecord` | `tests/evaluation/` |
| **BR-8** | Incremental Phased Delivery | SOW §6 (V0–V8) | HLD §16 | Master Implementation Roadmap | Gated Phase Reviews |
| **BR-9** | Regulatory Compliance Precondition | NFR-COMP-1 | SOW §9, EDD §1 | Live Trading Deployment Gate | Precondition Check |
| **FR-1** | Ingest OHLCV, Depth, Derivatives | FRD-DATA-1–5 | DDD §4, HLD §9 | `DataPipeline`, `DataSourceAdapter` | `tests/data_pipeline/` |
| **FR-6** | Dynamic Timeframe Intelligence | FRD-AGG-3 | ADD §7.3, LLD §8.3 | `Aggregator.select_best_timeframe` | `tests/aggregator/` |
| **FR-9/10** | Expected Value & Position Sizing | FRD-RISK-1–2 | RTLD §5, §6, LLD §5.3 | `RiskEngine._check_per_trade_risk` | `tests/risk_engine/` |
| **FR-11** | Hard Risk Limits & Circuit Breakers | FRD-RISK-3–10 | RTLD §5–§12, LLD §5 | `RiskEngine.evaluate` | `tests/risk_engine/` |
| **FR-12** | Independent Risk & Supervisor Gate | FRD-SUP-1–6 | HLD §8, LLD §7 | `Supervisor.decide` | `tests/supervisor/` |
| **FR-13–15** | Broker Execution & Idempotency | FRD-EXEC-1–5 | EDD §4–§6, LLD §9 | `ExecutionEngine`, `BrokerAdapter` | `tests/execution/` |
| **FR-19** | Post-Trade Variance Classification | FRD-EVAL-3 | SLD §5, DDD §5.3 | `TradeEvaluationService` | `tests/self_learning/` |
| **FR-22/23** | Model Promotion & Auto-Rollback | FRD-LEARN-3–8 | ADD §8, MLD §9, SLD §7 | `LearningPipeline`, `ModelRegistry` | `tests/self_learning/` |
| **FR-25/26** | Realistic Backtesting & Bias Guards | FRD-LEARN-3 | BTD §5–§8 | `BacktestEngine`, Fill Simulation | `tests/backtesting/`, Known-Answer Suite |
| **NFR-SAFE-6** | 100% Branch Coverage on Safety | NFR-SAFE-6 | LLD §13, TRD-CI-2 | Modules 6, 7, 11 | `pytest --cov --cov-branch` (100%) |
| **NFR-PERF-2/3**| Latency: Decision <5s, Order <2s | NFR-PERF-2/3 | EDD §7 | Execution Pipeline | Performance Benchmark Suite |
