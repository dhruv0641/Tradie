# Technical Requirements Document (TRD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Technical Requirements Document (TRD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1, PRD v0.1, BRD v0.1, SOW v0.1, FRD v0.1, NFRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD, BRD, SOW, FRD, NFRD (all v0.1) |

---

## 1. Purpose of This Document

The FRD defines *what each module must do*; the NFRD defines *how well*. This TRD is the bridge between those requirements and actual system design — it states the **technical requirements and constraints** that any architecture (HLD), technology selection (TTD), or detailed design (LLD) must satisfy, without itself choosing specific products, frameworks, or vendors.

This TRD answers: *what technical properties must the chosen stack, infrastructure, and integrations have* — not *which specific stack, infrastructure, or integrations to use*. Concrete technology selection belongs in the TTD, guided by the Master Context's stated technology philosophy (§24): reliability, maintainability, correctness, and observability take priority over performance, scalability, or cost, and unnecessary complexity should be avoided.

Where a technical decision cannot yet be made because an upstream business or product question is unresolved, this TRD states the requirement conditionally and flags the dependency rather than guessing.

---

## 2. Scope

This TRD covers technical requirements for:

1. System Architecture Style
2. Compute & Runtime Environment
3. Data Storage & Persistence
4. Data Pipeline & Integration Requirements
5. Broker/Execution Integration Requirements
6. Model Training & Serving Requirements
7. Messaging / Event Processing Requirements
8. API & Interface Requirements
9. Security & Secrets Management (technical layer)
10. Observability & Logging Infrastructure
11. Testing & CI/CD Requirements
12. Deployment & Environment Requirements
13. Technical Constraints Carried From Upstream Documents

It does not select specific languages, frameworks, cloud providers, or brokers — those are TTD/ADR decisions made against the requirements below.

---

## 3. Guiding Technical Principles (from Master Context §24 and NFRD)

Any technology choice made downstream of this TRD must be justified against this priority order, highest first:

1. **Reliability** — the system does what it's supposed to do, consistently, especially for safety-critical paths (NFR-SAFE-1–6).
2. **Maintainability** — a single operator (or small team) must be able to understand, modify, and safely extend the system over time (NFR-MAINT-1–4).
3. **Correctness** — outputs (decisions, risk calculations, executed trades) must be accurate and reproducible (FRD-FEAT-3, NFR-DATA-4).
4. **Observability** — system state must be inspectable in real time and after the fact (NFRD §8, FRD Module 9/11).
5. **Performance** — adequate for the chosen timeframes; not optimized for HFT by default (NFR-PERF-1–5).
6. **Scalability** — sufficient headroom for the initial scope; not over-engineered for a scale not yet justified (NFR-SCALE-2).
7. **Cost efficiency** — appropriate to a ₹10,000-scale initial deployment; avoid unnecessary spend (NFR-SCALE-2, PRD §24).

**Any technology choice that improves a lower-priority attribute at the expense of a higher-priority one (e.g., a faster but less reliable data feed, a cheaper but non-deterministic risk-check implementation) requires explicit justification and operator sign-off, not a default engineering judgment call.**

---

## 4. System Architecture Style — Technical Requirements

| ID | Requirement |
|---|---|
| TRD-ARCH-1 | The architecture shall be modular/service-oriented at the boundary of each FRD module (Data, Feature Engineering, Regime, Signals, Aggregation, Risk, Supervisor, Execution, Evaluation, Learning, Dashboard, Capital), such that any one module can be modified, replaced, or redeployed independently (implements NFR-MAINT-1). |
| TRD-ARCH-2 | The Trading Brain and Research Brain (PRD §7.6) shall be technically isolated — separate deployable units, separate credentials/permissions, and no shared write-path to live execution or live risk configuration (implements NFR-SAFE-5, FRD-X-4). |
| TRD-ARCH-3 | Safety-critical components (Risk Engine, Supervisor gate, kill switch/STOP) shall have minimal runtime dependencies (e.g., not requiring a model-inference service, external LLM API, or non-essential third-party service to evaluate a block) so their availability is not coupled to less-reliable components (implements NFR-SAFE-2). |
| TRD-ARCH-4 | The architecture shall define a single, canonical decision-record schema (FRD-EVAL-1) used consistently by every module that logs a decision, to avoid divergent or inconsistent audit formats. |
| TRD-ARCH-5 | The final architecture pattern (e.g., monolith-with-modules vs. microservices vs. modular monolith) is an **open TTD/HLD decision**; this TRD requires only that whichever pattern is chosen satisfies TRD-ARCH-1 through TRD-ARCH-4 — it does not mandate microservices or any specific pattern, consistent with avoiding unnecessary complexity (Guiding Principle 7). |

---

## 5. Compute & Runtime Environment — Technical Requirements

| ID | Requirement |
|---|---|
| TRD-COMPUTE-1 | The runtime environment shall support continuous (24/7 or market-hours-persistent) process execution for the Trading Brain, independent of any interactive session (i.e., not dependent on a human keeping a terminal/notebook open). |
| TRD-COMPUTE-2 | The Research Brain's compute (backtesting, model training) may run on a separate schedule/environment from the Trading Brain and does not need to be continuously available (only available when research is actively running). |
| TRD-COMPUTE-3 | Compute resources shall be sized to meet NFR-PERF-2–4 (decision latency, order latency, backtest cycle time) once those targets are confirmed by the operator (NFRD §14) — sizing is a TTD decision dependent on that confirmation. |
| TRD-COMPUTE-4 | The runtime shall support process supervision/auto-restart for non-safety-critical components, and a documented manual restart procedure for safety-critical components (to avoid an auto-restart silently masking a safety-relevant fault). |
| TRD-COMPUTE-5 | **Open item:** whether compute is self-hosted (operator's own machine), cloud-hosted, or hybrid is not yet decided (carried from SOW §12 item 5 / BRD §11 item 5 — Research Brain budget). This affects TRD-COMPUTE-1–4 implementation but not the requirements themselves. |

---

## 6. Data Storage & Persistence — Technical Requirements

| ID | Requirement |
|---|---|
| TRD-DATA-1 | The system shall use a time-series-appropriate storage mechanism for OHLCV/tick/depth data, supporting efficient range queries by instrument and time (supports FRD Module 1, Module 2). |
| TRD-DATA-2 | The system shall use a storage mechanism appropriate for structured/relational records (positions, orders, decision records, model versions) supporting transactional integrity for state changes (e.g., an order fill updating a position must not partially apply). |
| TRD-DATA-3 | Decision records and trade evaluations (FRD-EVAL-1, FRD-EVAL-3) shall be stored immutably (append-only or equivalent), per NFR-DATA-4. |
| TRD-DATA-4 | Storage shall support the retention duration specified in NFR-AUDIT-4 (full operating history by default) without requiring destructive pruning as a matter of routine operation. |
| TRD-DATA-5 | Storage shall support backup/restore sufficient to satisfy Disaster Recovery requirements (§13 below). |
| TRD-DATA-6 | Feature sets and model artifacts shall be stored with version identifiers retrievable alongside any historical decision record (implements FRD-FEAT-3, FRD-LEARN-6). |
| TRD-DATA-7 | Specific database technology/technologies are a TTD decision; this TRD requires only that the chosen technology satisfy TRD-DATA-1–6. |

---

## 7. Data Pipeline & Integration Requirements

| ID | Requirement |
|---|---|
| TRD-PIPE-1 | Data ingestion connectors shall be implemented as pluggable adapters conforming to a common internal data contract, so a vendor can be added/replaced without changing downstream modules (implements FRD-DATA-8, NFR-SCALE-1). |
| TRD-PIPE-2 | Data validation (staleness, gaps, anomalies — FRD-DATA-6) shall run as a distinct pipeline stage before data reaches Feature Engineering, not embedded ad hoc inside consuming modules. |
| TRD-PIPE-3 | The pipeline shall support both real-time/streaming ingestion (for live trading, V4+) and bulk historical ingestion (for backtesting/research, V0+) using the same underlying data contract, so backtest and live code paths do not diverge and silently produce inconsistent behavior. |
| TRD-PIPE-4 | Data-source outages shall be detectable at the pipeline level and surfaced to the Risk Engine (FRD-RISK-9) within the staleness threshold once NFR-DATA-1 is confirmed. |
| TRD-PIPE-5 | Specific vendor(s)/API(s) are an open item (carried from PRD §6.3/§14, SOW §12 item 2); this TRD requires only that whichever vendor(s) are selected can satisfy TRD-PIPE-1–4 and the data types listed in FRD Module 1. |

---

## 8. Broker/Execution Integration Requirements

| ID | Requirement |
|---|---|
| TRD-EXEC-1 | The broker integration shall support, at minimum: authentication, order placement, order modification, order cancellation, order-status polling or push updates, and position/portfolio queries (implements FRD-EXEC-1–4). |
| TRD-EXEC-2 | The integration shall provide (directly or via a wrapper) idempotent order submission (e.g., client-order-ID support) to enable duplicate-order prevention (FRD-EXEC-5). |
| TRD-EXEC-3 | The integration shall expose connection-health signals (e.g., heartbeat, session status) sufficient to detect disconnection within the bound required by NFR-REL-4 once confirmed. |
| TRD-EXEC-4 | The integration layer shall be abstracted behind an internal interface so that a change of broker does not require changes to the Risk Engine, Supervisor, or Evaluation modules (implements NFR-MAINT-1, TRD-ARCH-1). |
| TRD-EXEC-5 | The chosen broker/API must support the instrument types required by the eventual initial live-trading instrument decision (open item, PRD §6.3) — equities at minimum; options/futures support is required only if/when derivatives are brought into scope. |
| TRD-EXEC-6 | Broker selection itself is an open item (carried from PRD §14/SOW §12 item 2); this TRD requires only that the selected broker's API can satisfy TRD-EXEC-1–5. |

---

## 9. Model Training & Serving Requirements

| ID | Requirement |
|---|---|
| TRD-ML-1 | The technical environment shall support offline training of predictive models (Module 2/Module 4 agents that are ML-based) using historical data from the same data contract as TRD-PIPE-3, to avoid train/serve skew. |
| TRD-ML-2 | Trained model artifacts shall be serializable, versioned, and loadable by the live serving path without retraining (supports FRD-LEARN-6). |
| TRD-ML-3 | The serving path for live/paper decisions shall be technically separated from the training path (Research Brain), consistent with TRD-ARCH-2, so training workloads cannot degrade live decision latency (NFR-PERF-2). |
| TRD-ML-4 | Where reinforcement learning is used (PRD FR-24), the training environment shall be a simulated/offline environment technically incapable of submitting real orders (implements NFR-SAFE-5 for RL specifically). |
| TRD-ML-5 | The environment shall support the validation pipeline stages required by FRD-LEARN-3 (backtest, out-of-sample, walk-forward, stress, robustness, paper trading) as distinct, reproducible technical steps — not a single opaque "train and deploy" operation. |
| TRD-ML-6 | Specific ML/DL/RL frameworks are a TTD decision; this TRD requires only that the chosen framework(s) satisfy TRD-ML-1–5 and the backtest-cycle-time target once confirmed (NFR-PERF-4). |

---

## 10. Messaging / Event Processing Requirements

| ID | Requirement |
|---|---|
| TRD-MSG-1 | Where modules communicate asynchronously (e.g., data pipeline → feature engine → agents → aggregation), the mechanism shall preserve ordering per-instrument sufficient to avoid a decision being made on out-of-order data. |
| TRD-MSG-2 | The messaging/event mechanism shall not become a single point of failure for safety-critical paths (Risk Engine, kill switch) — per TRD-ARCH-3, those paths should avoid unnecessary dependency on the general-purpose event bus where a more direct, minimal-dependency path is feasible. |
| TRD-MSG-3 | Event/message delivery shall be reliable enough that a dropped message does not silently cause a missed decision-record log entry (violates FRD-X-3) — at-least-once delivery with de-duplication, or equivalent guarantee, is required for logging-critical events. |
| TRD-MSG-4 | Specific messaging technology (if any is needed beyond direct function/service calls) is a TTD decision, to be justified against Guiding Principle 7 (avoid unnecessary complexity) — a lightweight system at this scale may not need a dedicated message broker at all; this must not be assumed either way without HLD/TTD justification. |

---

## 11. API & Interface Requirements

| ID | Requirement |
|---|---|
| TRD-API-1 | Internal module boundaries (per TRD-ARCH-1) shall be defined through documented interfaces/contracts (e.g., function signatures, internal API specs), not implicit shared state, so modules can be tested in isolation (implements NFR-TEST-1). |
| TRD-API-2 | The Dashboard (FRD Module 11) shall consume system state through a defined interface (API) rather than reading internal module storage directly, so the dashboard cannot itself become a path that bypasses Module 9 logging or Module 6 risk checks. |
| TRD-API-3 | Any external API (e.g., a future integration or remote dashboard access, NFR-UX-3) shall require authentication and use encrypted transport (implements NFR-SEC-2, NFR-SEC-3). |
| TRD-API-4 | The full API Specification (contract details, versioning scheme) is a separate downstream document (Master Context §28 item 16); this TRD requires only that internal and external interfaces exist and satisfy TRD-API-1–3. |

---

## 12. Security & Secrets Management — Technical Layer

| ID | Requirement |
|---|---|
| TRD-SEC-1 | Broker/data-vendor credentials shall be stored using a secrets-management mechanism (e.g., encrypted vault, environment-based secret injection) — never committed to source control or logged in plaintext (implements NFR-SEC-1). |
| TRD-SEC-2 | All external network calls (broker, data vendors, any remote services) shall use TLS or equivalent encrypted transport (implements NFR-SEC-2). |
| TRD-SEC-3 | Access to STOP/kill-switch controls and capital-scaling actions shall require authenticated access at the technical layer, with the specific authentication mechanism selected in Security Design (implements NFR-SEC-3, still open per NFRD §14). |
| TRD-SEC-4 | Dependency/library versions shall be tracked (e.g., a manifest/lockfile) to support the vulnerability-review cadence once confirmed (NFR-SEC-6). |
| TRD-SEC-5 | Detailed security architecture (threat model, specific controls) belongs in the Security Design document (Master Context §28 item 18); this TRD sets only the baseline technical requirements above. |

---

## 13. Observability & Logging Infrastructure

| ID | Requirement |
|---|---|
| TRD-OBS-1 | The system shall emit structured (machine-parseable) logs for every decision record, order lifecycle event, risk evaluation, and system-health signal — not free-text logs that require manual parsing for audit purposes (implements NFR-AUDIT-1, NFR-AUDIT-3). |
| TRD-OBS-2 | Logging infrastructure shall be decoupled from the safety-critical evaluation path such that a logging-infrastructure outage is detected and escalated (per FRD-X-3) rather than silently blocking or silently skipping the underlying safety check. |
| TRD-OBS-3 | The system shall support querying decision records by instrument, date range, decision type, and model version, to satisfy NFR-AUDIT-2 lookup requirements once confirmed. |
| TRD-OBS-4 | System-health metrics (broker connection, data connection, model status, database status) shall be technically exposed in a form consumable by both the Dashboard (Module 11) and an alerting mechanism (NFR-AUDIT-5), from a single source of truth. |
| TRD-OBS-5 | Specific observability tooling (e.g., logging framework, metrics/monitoring stack) is a TTD decision, evaluated against Guiding Principle 4 (Observability) and Principle 7 (avoid unnecessary complexity) — an appropriately lightweight solution for single-operator scale is preferred over an enterprise-grade stack unless justified. |

---

## 14. Testing & CI/CD Requirements

| ID | Requirement |
|---|---|
| TRD-CI-1 | Each module (per FRD decomposition) shall have an automated test suite runnable independently, satisfying NFR-TEST-1. |
| TRD-CI-2 | Safety-critical modules (Risk Engine, Supervisor, kill switch/STOP) shall have their test suite run and pass before any deployment that touches those modules, with no manual override to skip this check (implements NFR-SAFE-4, NFR-SAFE-6). |
| TRD-CI-3 | The backtesting engine shall include known-answer/regression tests (NFR-TEST-4) run as part of the standard test suite, not as a one-off manual validation. |
| TRD-CI-4 | A deployment pipeline (manual or automated) shall exist that prevents a model or code change from reaching the live Trading Brain without passing its required test gates (extends TRD-CI-2 to the general case, supports FRD-LEARN-3 gating). |
| TRD-CI-5 | Rollback (FRD-LEARN-7, TRD-DATA-6/version retention) shall be technically executable without a full redeployment cycle, so an automatic rollback can happen quickly when a deployed model degrades. |
| TRD-CI-6 | Specific CI/CD tooling is a TTD decision, evaluated for appropriateness to a single-operator project (avoid enterprise CI/CD complexity unless justified — Guiding Principle 7). |

---

## 15. Deployment & Environment Requirements

| ID | Requirement |
|---|---|
| TRD-DEPLOY-1 | The system shall support at least three distinct environments/modes: research/backtesting (no live or simulated-market interaction beyond historical replay), paper trading (simulated execution against real-time data), and live trading — with clear technical separation so a paper-trading run cannot accidentally submit a live order or vice versa. |
| TRD-DEPLOY-2 | Configuration (risk limits, thresholds, credentials) shall be environment-specific and never shared by default between paper and live environments, to prevent a paper-trading risk-limit misconfiguration from silently applying to live capital or vice versa. |
| TRD-DEPLOY-3 | Deployment to the live environment (V5+) shall require an explicit, auditable action distinct from deployment to research/paper environments (supports BRD BR-9/SOW §9 preconditions being technically enforceable, not just procedurally observed). |
| TRD-DEPLOY-4 | Whether environments run on the same physical/cloud infrastructure with logical separation, or fully separate infrastructure, is a TTD decision — this TRD requires only the logical/technical separation in TRD-DEPLOY-1–3 regardless of physical topology. |

---

## 16. Disaster Recovery & Business Continuity

| ID | Requirement |
|---|---|
| TRD-DR-1 | Decision records, position state, and model artifacts shall be backed up on a defined schedule sufficient to avoid unrecoverable data loss in a single infrastructure failure. |
| TRD-DR-2 | On unplanned system restart or infrastructure failure, the system shall reconcile position/order state against the broker (extends FRD-EXEC-7/NFR-REL-5) before resuming automated decision-making, rather than trusting potentially stale local state. |
| TRD-DR-3 | If the system cannot confirm reconciled state after a failure, it shall default to a safe state (no new orders, i.e., HOLD/NO TRADE only) until reconciliation succeeds or the operator intervenes — never default to "assume state was fine and continue trading." |
| TRD-DR-4 | Specific backup schedule/RPO/RTO targets are **not yet defined** and should be confirmed alongside the NFRD §14 placeholders (e.g., MTTR target NFR-REL-6), since they are closely related. |

---

## 17. Technical Constraints Carried From Upstream Documents

These are not new requirements — they are hard constraints from the PRD/BRD/SOW/FRD/NFRD restated here because they directly bound technical design choices and must not be "designed around" at the TTD/HLD stage:

| Constraint | Source |
|---|---|
| No AI/LLM component may be a required dependency for hard risk-limit evaluation or kill-switch operation. | BRD BR-4, NFR-SAFE-1/2 |
| No unvalidated model may have a technical path to live order submission. | BRD BR-6, TRD-ML-4, FRD-X-4 |
| No component may silently increase allocated live capital. | BRD BR-2, FRD-CAP-2 |
| Every decision (including NO TRADE) must produce a complete, non-fabricated decision record. | BRD BR-7, NFR-AUDIT-1 |
| Manual STOP must function independent of AI component availability. | BRD BR-5, NFR-SAFE-2/3 |
| No live order may be technically possible before SOW §9 preconditions (regulatory review, broker selection, V0–V4 completion, tested risk limits, operator approval) are met. | SOW §9 |
| System must be built and deployed incrementally per V0–V8; a technical shortcut that collapses phases requires an explicit change order. | SOW §11, BRD BR-8 |

---

## 18. Open Items Carried Into This TRD

Consolidated from upstream documents, restated here specifically as they block finalizing TTD-level technology selection:

1. **Compute hosting model** (self-hosted / cloud / hybrid) — TRD-COMPUTE-5.
2. **Data vendor(s) and their entitlements** — TRD-PIPE-5.
3. **Broker selection and API capabilities** — TRD-EXEC-6.
4. **Compute/infrastructure budget**, particularly for the Research Brain — referenced in TRD-COMPUTE-3/5.
5. **Quantitative NFR targets** (NFRD §14 table) — needed to size TRD-COMPUTE-3, TRD-PIPE-4, TRD-CI (test-gate timing), and TRD-DR-4.
6. **Initial live-trading instrument type** (equity vs. NIFTY vs. options) — affects TRD-EXEC-5.

None of these block *writing* the TTD's requirements-driven sections, but all six should be resolved before the TTD commits to specific vendor/technology names.

---

## 19. Traceability

| TRD Section | FRD Reference | NFRD Reference |
|---|---|---|
| §4 Architecture Style | FRD-X-1–5, Module boundaries | NFR-SAFE-2/5, NFR-MAINT-1 |
| §5 Compute & Runtime | — | NFR-PERF-2–4, NFR-REL |
| §6 Data Storage | FRD-EVAL-1, FRD-FEAT-3 | NFR-DATA-4, NFR-AUDIT-4 |
| §7 Data Pipeline | FRD Module 1 | NFR-DATA-1, NFR-SCALE-1 |
| §8 Broker Integration | FRD Module 8 | NFR-REL-4, NFR-MAINT-1 |
| §9 Model Training/Serving | FRD Module 10 | NFR-PERF-2, NFR-SAFE-5 |
| §10 Messaging | FRD-X-3 | NFR-REL-3 |
| §11 API | FRD Module 11 | NFR-SEC-2/3 |
| §12 Security | — | NFR-SEC-1–6 |
| §13 Observability | FRD Module 9 | NFR-AUDIT-1–5 |
| §14 Testing/CI-CD | — | NFR-TEST-1–4, NFR-SAFE-6 |
| §15 Deployment | — | — |
| §16 Disaster Recovery | FRD-EXEC-7 | NFR-REL-5/6 |

Every TRD-ID should be entered into the Requirements Traceability Matrix alongside its FRD-ID/NFR-ID lineage, and forward-mapped to the TTD's technology decisions and corresponding Architecture Decision Records (ADRs) once made.

---

## 20. Document Governance

This TRD must remain consistent with the FRD and NFRD. Any technology decision made in the TTD that cannot satisfy a requirement in this document must either (a) trigger a documented exception with operator sign-off, or (b) trigger revision of the requirement here first — never be implemented silently in contradiction of this TRD.

**Next recommended step:** resolve the six items in §18 (at least directionally), then proceed to the HLD (system architecture and component design) and TTD (specific technology/vendor selection) in parallel, since the TTD's choices are constrained by, but do not have to wait indefinitely for, every open item to be fully closed.
