# Master Requirements Traceability Matrix (RTM)

## AI Trader — Baseline v1.0

This matrix establishes the unbroken lineage from business objectives and rules down through technical specifications, low-level design, code components, and verification test suites.

---

## 1. Business Rules & Governance Lineage (BRD §6)

| Business Rule | Description | FRD Module / ID | TRD / HLD Reference | LLD / Code Component | Verification Test Suite |
|---|---|---|---|---|---|
| **BR-1** | Capital Preservation Precedence | FRD-RISK-1–14, FRD-X-1 | RTLD §4–§12, HLD §8 | `RiskEngine`, `Supervisor` | `tests/risk_engine/`, KS-TEST-1 |
| **BR-2** | No Silent Capital Scaling | FRD-CAP-1–6 | RTLD §15, HLD §6 | `CapitalManager` | `tests/capital_manager/` |
| **BR-3** | NO TRADE Valid Outcome | FRD-AGG-4, FRD-SUP-3 | RTLD §13.2, ADD §4 | `Aggregator`, `Supervisor` | `tests/aggregator/` |
| **BR-4** | Deterministic Safety Independence | FRD-RISK-11, NFR-SAFE-1 | RTLD §2, HLD §8, TRD-ARCH-3 | `RiskEngine`, `KillSwitch` | `tests/risk_engine/`, KS-TEST-2 |
| **BR-5** | Human Override & Emergency STOP | FRD-DASH-7, NFR-SAFE-2 | RTLD §16, HLD §8 | `KillSwitch`, Dashboard API | `tests/kill_switch/`, KS-TEST-1–4 |
| **BR-6** | No Unvalidated Model to Live Capital | FRD-LEARN-3–5, FRD-X-4 | ADD §8, MLD §9, HLD §10 | `LearningPipeline`, Model Registry | `tests/learning_pipeline/` |
| **BR-7** | Full Decision Auditability (100%) | FRD-EVAL-1–6, NFR-AUDIT-1 | DDD §5.2, HLD §7, TRD-OBS-1 | `EvaluationService`, `DecisionRecord` | `tests/evaluation/` |
| **BR-8** | Incremental Phased Delivery | SOW §6 (V0–V8) | HLD §16 | Implementation Roadmap | Gated Phase Reviews |
| **BR-9** | Regulatory Compliance Precondition | NFR-COMP-1 | SOW §9, EDD §1 | Live Deployment Gate | Precondition Audit |

---

## 2. Functional Modules Traceability (FRD Modules 1–12)

| FRD Module | Requirement IDs | Domain Design | Architecture Ref | LLD Class / Function | Test Specification |
|---|---|---|---|---|---|
| **Module 1: Data Ingestion** | FRD-DATA-1–9 | DDD §4, §7 | HLD §6, §9, TRD-PIPE-1 | `DataSourceAdapter`, `DataPipeline` | `tests/data_pipeline/`, Quarantining |
| **Module 2: Feature Engine** | FRD-FEAT-1–5 | DDD §5.1, MLD §4 | HLD §6, TRD-PIPE-3 | `FeatureEngine.compute_features` | `tests/feature_engine/`, Look-ahead tests |
| **Module 3: Regime Detector** | FRD-REGIME-1–5 | MLD §5, RTLD §11 | HLD §6, ADD §5 | `RegimeDetector.classify` | `tests/regime_detector/` |
| **Module 4: Signal Generation** | FRD-SIG-1–5 | MLD §6, ADD §6 | HLD §6, ADD §4 | `TradingAgent.evaluate` | `tests/agents/`, Norm tests [0,1] |
| **Module 5: Aggregation & Scoring**| FRD-AGG-1–6 | ADD §7, RTLD §13 | HLD §6, LLD §8 | `Aggregator.aggregate`, `select_best_timeframe` | `tests/aggregator/`, Disagreement test |
| **Module 6: Risk Engine** | FRD-RISK-1–14 | RTLD §4–§14 | HLD §8, LLD §5 | `RiskEngine.evaluate`, `_check_*` | `tests/risk_engine/`, 100% branch cov |
| **Module 7: Supervisor** | FRD-SUP-1–6 | RTLD §13, HLD §8 | HLD §7, LLD §7 | `Supervisor.decide` | `tests/supervisor/`, KS-TEST-1 |
| **Module 8: Execution Engine** | FRD-EXEC-1–10 | EDD §4–§11 | HLD §9, LLD §9 | `ExecutionEngine`, `BrokerAdapter` | `tests/execution/`, Idempotency/Recon |
| **Module 9: Trade Evaluation** | FRD-EVAL-1–6 | DDD §5.3, SLD §5 | HLD §7, §12 | `TradeEvaluationService` | `tests/evaluation/` |
| **Module 10: Self-Learning** | FRD-LEARN-1–9 | SLD §6–§8, MLD §9 | HLD §10, §12 | `LearningPipeline`, `RollbackService` | `tests/self_learning/`, Rollback sim |
| **Module 11: Control & STOP** | FRD-DASH-1–8 | RTLD §16, EDD §11 | HLD §8, LLD §6 | `KillSwitch.activate`, `reset` | `tests/kill_switch/`, KS-TEST-1–4 |
| **Module 12: Capital Management** | FRD-CAP-1–6 | RTLD §15 | HLD §6, TRD-ARCH-4 | `CapitalManager` | `tests/capital_manager/` |

---

## 3. Non-Functional Requirements & Safety Invariants (NFRD §14, TRD)

| NFR ID | Requirement Category | Constraint / Threshold | Design Reference | Verification Mechanism |
|---|---|---|---|---|
| **NFR-SAFE-1** | Deterministic Risk Path | Minimal dependencies; no AI in risk loop | TRD-ARCH-3, HLD §8, LLD §10 | Static dependency-graph import check |
| **NFR-SAFE-2** | Manual STOP Latency | Trigger to order submission block $<2$ seconds | RTLD §16, LLD §6.2 | Automated latency benchmark under load |
| **NFR-SAFE-6** | Safety Branch Coverage | **100% branch coverage** on Modules 6, 7, 11 | LLD §13, TRD-CI-2 | `pytest --cov --cov-branch` gate in CI |
| **NFR-DATA-3** | Point-in-Time Discipline | Zero look-ahead leakage across time-series | BTD §5.2, DDD §2 | Known-Answer synthetic series tests |
| **NFR-DATA-4** | Audit Immutability | Append-only storage for decisions/evaluations | TRD-DATA-3, DDD §6 | Database grant restrictions & test assertions |
| **NFR-REL-4** | Reconnection Window | 30s broker reconnection before safe-state hold | RTLD §11, EDD §9, LLD §9.3 | Simulated network drop integration test |
| **NFR-REL-5** | Startup Reconciliation | Zero orders submitted before clean reconciliation | TRD-DR-2/3, EDD §10, LLD §9.1 | Discrepancy injection restart tests |
| **NFR-PERF-2** | Decision Latency Budget | $<5$ seconds from candle close to decision | TRD-PERF-2, EDD §7 | End-to-end cycle timer logging |
| **NFR-PERF-3** | Order Latency Budget | $<2$ seconds from decision to broker submission | TRD-PERF-3, EDD §7 | Gateway dispatch benchmark |
| **NFR-SEC-1** | Secrets Isolation | Zero plaintext secrets in code, configs, or logs | TRD-SEC-1, TTD §12 | Pre-commit `gitleaks` & `detect-secrets` |
| **NFR-TEST-3** | General Line Coverage | $\ge 80\%$ line coverage across all non-safety code | TRD-CI-2, TTD §14 | CI coverage gate |
| **NFR-TEST-4** | Backtest Known-Answer | 100% match on deterministic synthetic test suites | BTD §11 | Known-answer fixture suite |
