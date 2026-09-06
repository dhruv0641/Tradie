# Technology / Technical Design Document (TTD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Technology / Technical Design Document (TTD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1, PRD, BRD, SOW, FRD, NFRD, TRD, HLD, ADD, MLD, RTLD, BTD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader TRD v0.1 (technical requirements), HLD v0.1 (architecture) |
| **Sibling/Downstream Documents** | LLD (per-module detail), DDD (data schema — not yet drafted), API Spec, Security Design, Observability Design, Deployment/DevOps Design, ADRs, Requirements Traceability Matrix |

---

## 1. Purpose of This Document

The TRD defines *what technical properties* the system must have; the HLD defines *how the FRD modules are grouped into components and how they communicate*. Neither selects a product, language, framework, or vendor. This TTD is where that selection happens: it names the concrete technology stack, justifies each choice against the TRD's guiding-principle priority order (§3), and maps every choice back to the HLD component it implements.

Consistent with how the HLD treated TRD-ARCH-5 (monolith vs. microservices) and how the ADD/MLD treated framework selection, **every technology choice in this document is a reasoned proposal, not a finalized decision**, unless explicitly marked otherwise. Several choices are conditional on open items this TTD does not own (compute hosting model, broker selection, data-vendor selection) — where that is the case, this document states the requirement-driven shortlist and the decision criteria, rather than guessing a name to fill the blank.

This TTD does not restate *why* a requirement exists (see TRD) or *where* a component sits in the system (see HLD) — it only answers *which concrete technology satisfies that requirement, inside that component boundary*.

---

## 2. Scope

**In scope:** programming language(s) and runtime; per-component library/framework selection; data storage technology; messaging/event-processing technology (or the decision not to use one); ML/DL/RL framework selection; API/interface technology; secrets-management mechanism; observability/logging stack; CI/CD tooling; dependency and environment management; containerization/deployment mechanism; backup/DR tooling; a consolidated technology decision table; and the shortlist/criteria for the still-open compute-hosting, broker, and data-vendor decisions.

**Out of scope:** *why* each TRD requirement exists (TRD); component boundaries and data flow (HLD); per-module algorithms (LLD, MLD, ADD, RTLD, BTD); the full data schema (DDD, not yet drafted — §17); the full API contract (API Spec); detailed threat model (Security Design); UI/UX layout (UI/UX Spec). Where this TTD names a technology for one of those areas (e.g., "structured logs in JSON"), it is naming the *mechanism*, not designing the *content* those documents own.

---

## 3. Guiding Principles (Carried Forward, Not Reopened)

Every choice below is justified against this priority order, highest first — unchanged from TRD §3 / HLD §2:

**Reliability > Maintainability > Correctness > Observability > Performance > Scalability > Cost efficiency**, with the added architectural constraint that the Trading Brain and Research Brain are separately deployable (TRD-ARCH-2) and the safety-critical path (Risk Engine, Supervisor, kill switch) must have minimal runtime dependencies (TRD-ARCH-3). A technology that scores well on performance or cost but poorly on reliability or maintainability for a single-operator, ₹10,000-scale project is the wrong choice here, even if it would be the right choice at larger scale — Guiding Principle 7 (avoid unnecessary complexity) applies to every selection in this document, not only to the architecture pattern.

---

## 4. Language & Runtime

| Decision | Proposal |
|---|---|
| **Primary language** | **Python 3.12+** for all components (Data Pipeline, Feature Engine, Regime Detector, Agent Roster, Aggregator, Risk Engine, Supervisor, Execution Engine, Evaluation Service, Learning Pipeline, Dashboard/Control backend, Capital Manager). |

**Rationale (against §3 priorities):**
- **Maintainability** — a single operator/small team maintaining ten-plus components benefits from one language across the whole system rather than a polyglot stack; Python has the deepest available library ecosystem for data analysis, ML/DL/RL, and broker SDKs relevant to this domain, minimizing custom integration code (itself a maintainability and correctness risk).
- **Correctness** — mature, widely-used numerical/data libraries (pandas, NumPy) reduce the chance of a hand-rolled bug in something as safety-relevant as position sizing or a walk-forward calculation.
- **Reliability** — Python is not the fastest language, but nothing in the FRD/NFRD requires HFT-grade latency (NFRD explicitly scopes this as non-HFT, §14); the reliability cost of a less mature/less-tested toolchain in this domain would outweigh a speed gain nothing here requires.
- **Performance** — where a specific hot path genuinely needs it (e.g., a backtest inner loop over years of tick data), this proposes using vectorized NumPy/pandas or, if profiling shows it is still insufficient, a narrowly-scoped Rust/C extension (e.g., via `polars` or `numba`) for that one function only — never a second general-purpose language for a whole component (Guiding Principle 7).

**This is a proposal, not a finalized decision** — it should be confirmed by the operator before it is treated as binding across every downstream LLD.

---

## 5. Compute & Runtime Environment

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-COMPUTE-1 (continuous process execution, Trading Brain) | Trading Brain runs as a long-lived OS process managed by a process supervisor (`systemd` if self-hosted Linux, or the container orchestrator's restart policy if containerized — §12) — not a script left running in a terminal or notebook. |
| TRD-COMPUTE-2 (Research Brain, separate schedule) | Research Brain runs as scheduled/on-demand jobs (cron, or a container run on demand) — no requirement for 24/7 uptime. |
| TRD-COMPUTE-4 (auto-restart for non-safety-critical; manual restart for safety-critical) | Non-safety-critical components use the supervisor's auto-restart. The Risk Engine/Supervisor/kill-switch unit (HLD §8) is explicitly **excluded** from auto-restart-on-crash without human review — a crash there must halt to a safe state (per TRD-DR-3) and page the operator, not silently come back up and resume trading; this is a policy applied to whichever supervisor technology is chosen, not a property of the technology itself. |
| TRD-COMPUTE-5 (open: hosting model) | **Open — see §13.** This TTD's other choices (§4, §6, §12) are made to work under *either* self-hosted or cloud hosting, specifically so this open item does not block the rest of the stack. |

---

## 6. Data Storage & Persistence

| TRD Requirement | Technology Proposal | Rationale |
|---|---|---|
| TRD-DATA-1 (time-series storage, OHLCV/tick/depth) | **PostgreSQL with the TimescaleDB extension**, or plain Postgres with time-partitioned tables if TimescaleDB adds unwanted operational complexity at current scale. **Parquet files** (partitioned by instrument/date) for the Research Brain's bulk historical archive, read via `pandas`/`polars`/DuckDB for backtesting. | One relational engine (Postgres) serves both time-series and transactional needs (below), satisfying Guiding Principle 7 by not requiring a second database technology just for time-series data at this scale. Parquet is the standard for large, columnar, append-mostly historical data and integrates directly with the backtesting engine's need for fast range scans (BTD §8). |
| TRD-DATA-2 (relational storage, transactional integrity) | **PostgreSQL** for positions, orders, decision records, model version metadata — ACID transactions satisfy the "an order fill must not partially apply" requirement directly. |
| TRD-DATA-3 (immutable decision records) | Decision records and trade evaluations are written **append-only** at the application layer (no `UPDATE`/`DELETE` code path for these tables); enforced additionally via restricted database-role permissions (`INSERT`-only grant on those tables for the Trading Brain's runtime credential). |
| TRD-DATA-4 (full-history retention) | Postgres for structured records; Parquet/object storage (local disk or cloud object storage, per §13) for bulk time-series — both scale to multi-year retention without requiring destructive pruning as routine operation. |
| TRD-DATA-5 (backup/restore) | `pg_dump`/`pg_basebackup` (or managed-Postgres automated backups if cloud-hosted) on a defined schedule; Parquet archive mirrored to a second location (external disk or cloud object storage) — see §16 (DR). |
| TRD-DATA-6 (versioned feature sets/model artifacts) | Model artifacts serialized (`joblib`/`pickle` for scikit-learn-family models, framework-native serialization for any deep-learning model) and stored in a version-labeled file store (local filesystem or object storage), with the version identifier, hash, and storage path recorded in a Postgres `ModelVersion` row — never the artifact bytes without a matching relational record, and never a relational record without the retrievable artifact. |

**Why not a NoSQL/document store:** the data here is fundamentally relational and consistency-sensitive (positions, orders, risk state) or naturally columnar/time-series (market data) — neither profile is better served by a document database, and introducing one would add a second storage technology to operate and back up without a corresponding requirement it uniquely satisfies (Guiding Principle 7). **Why not a dedicated time-series database (e.g., InfluxDB) instead of Postgres/TimescaleDB:** it would be a third storage technology for a benefit (very high-cardinality, very high-ingest-rate time-series) this project's scale does not yet require; this should be revisited only if NFR-SCALE-3 capacity headroom analysis (once written) shows Postgres/TimescaleDB becoming a genuine bottleneck.

---

## 7. Data Pipeline & Integration

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-PIPE-1 (pluggable adapters, common contract) | Each data vendor gets one adapter module implementing a shared Python `Protocol`/abstract base class (`DataSourceAdapter`) defined once and reused by every adapter — satisfies HLD §9's Data Source Adapter Interface concretely. |
| TRD-PIPE-2 (validation as distinct stage) | A dedicated validation module (staleness, gap, anomaly checks) runs as an explicit pipeline stage using `pandas`/`pydantic` for schema and range validation — not embedded inline in each adapter. |
| TRD-PIPE-3 (same contract for streaming and bulk) | Real-time ingestion uses vendor WebSocket/streaming APIs (via `websockets` or the vendor SDK) normalized into the same `pydantic` data-contract models used by the bulk historical loader (`pandas`/`requests` against REST/bulk-download endpoints) — one contract, two ingestion paths. |
| TRD-PIPE-4 (outage detection) | Adapter-level heartbeat/last-message-timestamp tracking, surfaced to the Risk Engine via the same internal call path used for all Risk Engine inputs (HLD §8) — no new dependency introduced on the safety-critical path itself. |
| TRD-PIPE-5 (vendor selection) | **Open — see §14.** The adapter interface above is designed so vendor selection is a matter of writing one new adapter class, not a pipeline redesign. |

---

## 8. Broker / Execution Integration

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-EXEC-1–3 (auth, orders, status, connection health) | A single `BrokerAdapter` interface (Python abstract base class) implemented once per broker, wrapping whatever SDK/REST API the selected broker provides. |
| TRD-EXEC-2 (idempotent submission) | Client-order-ID generation and a local `OrderSubmission` de-duplication table (Postgres) sit inside the adapter layer, so idempotency does not depend on every broker's API supporting it natively. |
| TRD-EXEC-4 (abstraction, no leakage to Risk Engine/Supervisor/Evaluation) | Enforced the same way as HLD §10's Trading Brain/Research Brain boundary: no import of any broker SDK type outside the `BrokerAdapter` implementation module — checkable via a dependency-graph/import-linter check in CI (ties to TRD-CI-2). |
| TRD-EXEC-6 (broker selection) | **Open — see §14.** Indian retail-broker APIs commonly used for algorithmic trading (e.g., Zerodha Kite Connect, Upstox, others) are named here only as **illustrative examples of the category this adapter must support** — not a selection. |

---

## 9. ML / DL / RL Training & Serving

| TRD Requirement | Technology Proposal | Rationale |
|---|---|---|
| TRD-ML-1 (offline training, same data contract) | **scikit-learn** and **XGBoost/LightGBM** for the initial roster's statistical/ML agents (per ADD §6, initial agents are largely rule-based/statistical — heavier frameworks are not yet justified). | Matches the actual initial-roster complexity (MLD §6) rather than pre-installing deep-learning infrastructure for models that don't yet exist. |
| TRD-ML-2 (versioned, serializable, loadable artifacts) | `joblib` (scikit-learn-family) or framework-native save/load; version tag = git commit hash of training code + a monotonic model-version ID, per DDD §5.4's `ModelVersion` entity (once DDD is drafted — §17). |
| TRD-ML-3 (serving separated from training) | Serving path only ever *loads* a versioned artifact (§6 TRD-DATA-6) — it never imports the training pipeline's code, so a training-time dependency (e.g., a heavier ML library not needed at inference time) cannot leak into the latency-sensitive live path. |
| TRD-ML-4 (RL sandboxing) | **Gymnasium** (successor to OpenAI Gym) for the RL environment interface, **Stable-Baselines3** for RL algorithms, **only if/when** an RL agent is actually introduced (ADD §11 — none in the initial roster). The training environment is a package with no import of the `BrokerAdapter` (§8) at all — structurally incapable of order submission, not merely configured not to submit orders. |
| TRD-ML-5 (reproducible validation stages) | Each BTD §8 stage (backtest, out-of-sample, walk-forward, stress, robustness, paper) is a distinct, independently-invokable Python entry point/script with its own recorded inputs, outputs, and `ValidationRunRecord` — not one monolithic "train and deploy" function. |

**Not proposed at this stage:** PyTorch/TensorFlow or any deep-learning framework. Nothing in the current agent roster (ADD §6) or MLD (§6–§9) specifies a neural-network model; introducing one of these frameworks before an agent actually needs it would violate Guiding Principle 7. This should be revisited the moment a specific candidate agent's design (MLD or a future ADR) calls for it.

---

## 10. Messaging / Event Processing

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-MSG-1–3 (ordering, no SPOF on safety-critical path, reliable delivery) | **No dedicated message broker is proposed at this stage.** Consistent with HLD §4's modular-monolith decision and HLD §17 item 6, inter-module communication within the Trading Brain uses direct in-process function calls, which trivially preserve per-instrument ordering (single-threaded per-instrument evaluation cycle, RTLD §13) and cannot themselves become an availability dependency for the Risk Engine/Supervisor (TRD-ARCH-3) since there is no network hop or broker process involved. |
| TRD-MSG-3 (logging-critical delivery guarantee) | Decision-record writes go directly to Postgres inside the same function-call chain that produced the decision (HLD §7's "every arrow into Evaluation Service happens unconditionally") — a direct, transactional write has a stronger delivery guarantee here than routing through an intermediary broker would, at lower operational complexity. |
| TRD-MSG-4 (justification for "no broker") | This is the reasoned justification TRD-MSG-4 requires: a dedicated broker (Kafka, RabbitMQ, Redis Streams, etc.) would add an operational dependency and failure mode with no corresponding benefit at single-operator, one-Trading-Brain-process scale. **Revisit if:** the Research Brain's compute needs (TRD-COMPUTE-2) grow to require distributed job scheduling, or a future component extraction (HLD §4 "Future extraction") genuinely crosses a process boundary that direct function calls can no longer serve — at that point, a narrowly-scoped addition (e.g., Redis for just that one boundary) is preferable to introducing a general-purpose broker pre-emptively. |

---

## 11. API & Interface Layer

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-API-1 (documented internal interfaces) | Python `Protocol`/ABC-defined interfaces per HLD §6 component boundary (already reflected in §7/§8/§9 above), type-checked with `mypy` in CI so an interface violation is caught before runtime, not just documented in comments. |
| TRD-API-2 (Dashboard via defined API, not direct storage access) | **FastAPI** backend exposing the Dashboard/Control Service's read endpoints (system state, decision records, positions) and the STOP control's write endpoint — the Dashboard frontend never queries Postgres directly. |
| TRD-API-3 (authenticated, encrypted external API) | FastAPI's built-in dependency-injection auth (token-based to start; see TRD-SEC-3/§14 for the finalized mechanism) behind HTTPS/TLS (§13). |
| TRD-API-4 (full spec is a separate document) | This TTD only fixes the technology (FastAPI); the actual contract belongs in the API Spec document (not yet drafted). |

**Dashboard frontend:** a lightweight web frontend (e.g., a small React/Vite app, or, if the operator prefers minimal footprint, a server-rendered page via FastAPI + Jinja2) consuming the API above. This choice is lower-stakes than the backend choices in this document and can be deferred to the UI/UX Spec without blocking any safety-critical component.

---

## 12. Security & Secrets Management (Technical Layer)

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-SEC-1 (secrets never in source control/plaintext logs) | Environment-variable injection for all environments, sourced from a `.env` file (git-ignored) for local/self-hosted development, and a managed secrets store (e.g., the cloud provider's secrets manager, or `HashiCorp Vault` self-hosted) if/when cloud hosting is adopted (§13). `python-dotenv` for local loading; secrets never hard-coded or committed. |
| TRD-SEC-2 (TLS for all external calls) | All broker/data-vendor HTTP(S)/WebSocket connections use TLS by default (both are expected to require it); explicitly verified (no `verify=False` / disabled certificate checks anywhere in the adapter code — enforced via a CI lint rule). |
| TRD-SEC-3 (authenticated STOP/capital-scaling access) | Token-based authentication on the FastAPI Dashboard/Control Service to start (e.g., a long-lived operator API key stored per TRD-SEC-1); the specific mechanism (API key vs. OAuth vs. something else) is finalized in the Security Design document — this TTD commits only to "authenticated, not anonymous," per TRD-SEC-3's own scope note. |
| TRD-SEC-4 (dependency/library version tracking) | **`uv` or `poetry`** for Python dependency management with a committed lockfile (`uv.lock`/`poetry.lock`), enabling reproducible installs and a clear basis for vulnerability scanning (`pip-audit` or `safety` in CI). |

---

## 13. Observability & Logging Infrastructure

| TRD Requirement | Technology Proposal | Rationale |
|---|---|---|
| TRD-OBS-1 (structured logs) | Python's `structlog` (or `logging` with a JSON formatter) emitting structured JSON for every decision record, order-lifecycle event, risk evaluation, and health signal. |
| TRD-OBS-2 (logging decoupled from safety-critical path, outage detected not silently absorbed) | Decision-record persistence writes directly to Postgres (§10) inside the same evaluation call, so "logging" for audit purposes is a database transaction, not a best-effort log line — a Postgres write failure raises an exception the Supervisor can detect and escalate (rather than a fire-and-forget log call that could silently fail). Free-text application logs (for debugging, not audit) are separate and may use a simpler pipeline. |
| TRD-OBS-3 (queryable by instrument/date/type/model version) | Native SQL queries against the Postgres decision-record table, indexed on those columns — no separate log-search product needed at this scale. |
| TRD-OBS-4 (health metrics, single source of truth) | A lightweight `/health` endpoint on the FastAPI service aggregating broker-connection, data-connection, model-status, and database-status checks, consumed by both the Dashboard (§11) and an alerting mechanism. |
| TRD-OBS-5 (tooling scaled to Guiding Principle 7) | **Proposed: no enterprise observability stack (no dedicated Prometheus/Grafana/ELK deployment) at current scale.** Structured logs + Postgres queries + the `/health` endpoint, with simple threshold-based alerting (e.g., a scheduled check that emails/messages the operator if `/health` reports a failure) cover NFR-AUDIT-1–5 and NFR-AUDIT-5 without the operational overhead of running and maintaining a metrics/dashboarding stack for a single-operator system. **Revisit** once V8's "production observability/alerting hardening" phase (HLD §16) is reached and actual gaps in this lightweight approach are identified. |

---

## 14. Testing & CI/CD

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-CI-1 (independent test suite per module) | **`pytest`**, with tests organized to mirror the HLD §6 module boundaries — each component's tests runnable in isolation (`pytest tests/risk_engine/`, etc.). |
| TRD-CI-2 (safety-critical tests gate deployment, no override) | **GitHub Actions** (or GitLab CI if the operator's repo host differs) with a required, non-bypassable check on the Risk Engine/Supervisor/kill-switch test suite before any merge/deploy touching those paths — branch-protection rules enforce this at the platform level, not just as a CI script convention. |
| TRD-CI-3 (backtest known-answer/regression tests) | Known-answer backtest fixtures committed to the repo and run as standard `pytest` cases on every CI run, not as a manual one-off. |
| TRD-CI-4 (deployment pipeline gates model/code changes) | The same CI pipeline gates deployment; promotion of a new model version (HLD §12) additionally requires the `ValidationRunRecord` evidence check described there — a CI-green build is necessary but not sufficient for model promotion specifically. |
| TRD-CI-5 (fast rollback) | Prior `ModelVersion` artifacts are never deleted (TRD-DATA-6); rollback = re-pointing the live model-serving slot's reference to a prior version ID — a database update, not a redeployment. |
| TRD-CI-6 (tooling scaled appropriately) | GitHub Actions (or equivalent) is proposed specifically because it requires no separate CI server to operate — appropriate for a single-operator project (Guiding Principle 7) versus a self-hosted Jenkins/enterprise CI system. |

**Code quality tooling:** `ruff` (lint + format), `mypy` (type checking), `pre-commit` hooks to catch issues before they reach CI — reduces the chance of a preventable bug reaching the safety-critical test gate in the first place.

---

## 15. Deployment & Environment Topology

| TRD Requirement | Technology Proposal |
|---|---|
| TRD-DEPLOY-1 (three separated environments/modes) | **Docker** images for the Trading Brain and Research Brain, with environment selected via a build/run-time argument (`research` / `paper` / `live`) that determines which `BrokerAdapter` implementation is wired in — the research mode has no `BrokerAdapter` implementation compiled/available at all (mirrors HLD §11's "no order submission path exists" for that mode, made structurally true rather than configuration-only). |
| TRD-DEPLOY-2 (no shared config between paper/live by default) | Separate `.env`/secrets files per environment (§12), never a single shared config file with an environment flag that could be toggled by mistake. |
| TRD-DEPLOY-3 (explicit, auditable action for live deployment) | Live deployment requires a distinct, manually-triggered CI/CD job (not automatic on merge, unlike paper/research deploys which may auto-deploy) — the trigger itself is logged with who/when, satisfying the auditability requirement at the deployment-tooling layer. |
| TRD-DEPLOY-4 (physical topology is a TTD decision) | Proposed: **one physical/cloud host can run all environments** with Docker providing the logical separation (separate containers, separate networks/volumes per environment) — full physical separation is not required by TRD-DEPLOY-1–3 and would add cost/complexity (Guiding Principle 7) without a corresponding reliability benefit at this scale. This should be revisited if the compute-hosting decision (§13 open item... see §16) favors a different topology. |

---

## 16. Compute Hosting — Open Item, Shortlist and Criteria

TRD-COMPUTE-5 and HLD §17 item 2 leave the hosting model open (self-hosted / cloud / hybrid). This TTD does not resolve it, but narrows it to a decision the operator can make against concrete criteria, since every choice above (§5, §6, §12, §15) has been made to work under any of the three options:

| Option | Fits well if... | Technology implication |
|---|---|---|
| **Self-hosted** (operator's own machine, always-on) | Operator has a reliable always-on machine and residential/available internet suitable for continuous market-hours operation (TRD-COMPUTE-1); no infrastructure budget is confirmed yet (BRD §11 item 5, still open). | Docker + `systemd`, local Postgres, local Parquet/disk storage, `.env`-based secrets. Lowest cost; operator bears reliability/uptime risk directly. |
| **Cloud-hosted** (e.g., a single small VM) | An infrastructure budget is confirmed; operator wants provider-managed uptime/backup guarantees for the Trading Brain specifically. | Same Docker images, deployed to a cloud VM; managed Postgres (e.g., RDS-equivalent) optional; cloud provider's secrets manager instead of local `.env`. |
| **Hybrid** | Trading Brain self-hosted for direct control over the safety-critical path; Research Brain (compute-heavier, less latency-sensitive) cloud-hosted for training/backtesting burst capacity (TRD-COMPUTE-2 already permits this — Research Brain has no continuous-uptime requirement). | Splits cleanly along the same boundary the architecture already requires (HLD §10); no re-architecture needed to move Research Brain compute later. |

**This TTD's recommendation, pending operator confirmation:** start **self-hosted** for V0–V4 (research/backtest/paper — zero real capital at risk per SOW §7), since no infrastructure budget is yet confirmed and reliability requirements for these phases are lower; revisit cloud/hybrid specifically for V5+ (live trading) once BRD §11 item 5's budget question is resolved, since that is when Trading Brain uptime during market hours becomes safety- and capital-relevant. This is a reasoned proposal, not a decision — it should be confirmed or revised by the operator before V4/V5 planning finalizes.

---

## 17. Broker & Data Vendor Selection — Open Items, Not Resolved Here

Per TRD-EXEC-6 and TRD-PIPE-5 (carried from PRD §6.3, SOW §12 item 2), broker and data-vendor selection remain open and are **not decided in this document**. This TTD's contribution is limited to:

1. Confirming the `BrokerAdapter` (§8) and `DataSourceAdapter` (§7) interfaces are the *only* place broker/vendor-specific code may live, so selection — whenever it happens — is additive, not a redesign.
2. Naming the general category of Indian retail-broker APIs commonly used for algorithmic trading (e.g., Zerodha Kite Connect, Upstox) purely as **illustrative examples of what the adapter must support** (order types, market-data entitlements per PRD §6.3), not as a recommendation or selection.
3. Flagging that broker fee/cost structure feeds directly into BTD's cost/friction modeling (BTD §13) — so this open item blocks finalizing those numeric parameters, not just this TTD.

**This should be resolved by the operator (with input on API capability/cost trade-offs, not a unilateral technology pick) before TRD-EXEC-5's instrument-type requirement and BTD's cost assumptions can move from placeholder to final.**

---

## 18. Consolidated Technology Decision Table

| Layer | Technology | Status |
|---|---|---|
| Language/runtime | Python 3.12+ | Proposed |
| Relational + time-series storage | PostgreSQL (+ TimescaleDB extension if warranted) | Proposed |
| Bulk historical storage | Parquet files, read via pandas/polars/DuckDB | Proposed |
| Data validation | pydantic + pandas | Proposed |
| Real-time ingestion | websockets / vendor SDK | Proposed |
| ML (initial roster) | scikit-learn, XGBoost/LightGBM | Proposed |
| RL (if/when introduced) | Gymnasium + Stable-Baselines3 | Conditional — not needed for initial roster |
| Deep learning | *(none proposed yet)* | Deferred until a specific agent design requires it |
| Messaging/event bus | None (direct in-process calls) | Proposed; revisit per §10 triggers |
| Internal API | FastAPI | Proposed |
| Dashboard frontend | React/Vite or FastAPI+Jinja2 | Proposed, lower-stakes, deferrable to UI/UX Spec |
| Secrets management | `.env` (local) / cloud secrets manager or Vault (cloud) | Proposed |
| Structured logging | structlog / JSON logging | Proposed |
| Metrics/alerting | Lightweight `/health` + scheduled checks (no Prometheus/Grafana yet) | Proposed |
| Dependency management | `uv` or `poetry` with lockfile | Proposed |
| Testing | pytest | Proposed |
| Lint/type-check | ruff, mypy, pre-commit | Proposed |
| CI/CD | GitHub Actions (or GitLab CI) | Proposed |
| Containerization | Docker | Proposed |
| Compute hosting | Self-hosted → cloud/hybrid for V5+ | **Open — §16** |
| Broker | Not selected | **Open — §17** |
| Data vendor(s) | Not selected | **Open — §17** |

Every "Proposed" row should be converted into a formal Architecture Decision Record (ADR) once confirmed, per Master Context §28's ADR deliverable — this table is the index of ADRs still to be written, not a substitute for them.

---

## 19. Traceability

| TTD Section | TRD Reference | HLD Reference |
|---|---|---|
| §4 Language & runtime | TRD §3 Guiding Principles | HLD §4 |
| §5 Compute & runtime | TRD-COMPUTE-1–5 | HLD §11, §16 |
| §6 Data storage | TRD-DATA-1–7 | HLD §6, §15 |
| §7 Data pipeline | TRD-PIPE-1–5 | HLD §9 |
| §8 Broker/execution | TRD-EXEC-1–6 | HLD §9, §6 |
| §9 ML/DL/RL | TRD-ML-1–6 | HLD §6 (Agent Roster, Learning Pipeline), ADD §10–§11 |
| §10 Messaging | TRD-MSG-1–4 | HLD §4, §17 item 6 |
| §11 API | TRD-API-1–4 | HLD §6 (Dashboard/Control Service), §9 |
| §12 Security | TRD-SEC-1–5 | HLD §5 |
| §13 Observability | TRD-OBS-1–5 | HLD §13 |
| §14 Testing/CI-CD | TRD-CI-1–6 | HLD §19 (governance) |
| §15 Deployment | TRD-DEPLOY-1–4 | HLD §11 |
| §16 Compute hosting | TRD-COMPUTE-5 | HLD §17 item 2 |
| §17 Broker/vendor | TRD-EXEC-6, TRD-PIPE-5 | HLD §17 item 3 |

Every row in §18's decision table should be entered into the Requirements Traceability Matrix against its TRD-ID and HLD component, and every "Proposed" status should be updated to "Confirmed" or "Revised" as the operator reviews this document, before LLD work begins on the corresponding component.

---

## 20. Open Items Carried Into Downstream Work

1. **Compute hosting model** (self-hosted/cloud/hybrid) — §16, blocks finalizing §15's physical topology.
2. **Broker selection** — §17, blocks TRD-EXEC-5's instrument-type requirement and BTD's cost-parameter finalization.
3. **Data vendor(s) and entitlements** — §17, blocks confirming which `DataSourceAdapter` implementations are actually needed for V0.
4. **Infrastructure/compute budget**, particularly for the Research Brain (BRD §11 item 5) — directly feeds the §16 recommendation.
5. **Authentication mechanism for Dashboard/STOP control** (API key vs. OAuth vs. other) — TRD-SEC-3, deferred to Security Design.
6. **DDD (Data Design Document) has not yet been drafted** — several references above (e.g., `ModelVersion`, `DecisionRecord` schemas) are cited from other documents' section numbers but the DDD itself is currently empty; the schema-level detail behind TRD-DATA-1–7 should be finalized there, consistent with this TTD.

None of these block treating §4–§15 and §18's "Proposed" rows as a working baseline for LLD work to begin against — they should, however, be resolved before any "Proposed" row is promoted to a formal ADR.

---

## 21. Document Governance

This TTD must remain consistent with the TRD (requirements) and HLD (architecture). Any technology choice here that cannot satisfy a TRD requirement, or that doesn't fit inside an HLD component boundary, must either (a) trigger a documented exception with operator sign-off, or (b) trigger revision of the TRD/HLD first — never be implemented silently in contradiction of either.

This TTD should be revisited whenever:
- The operator confirms, revises, or rejects any "Proposed" row in §18.
- Compute hosting, broker, or data-vendor selection (§16, §17) resolves.
- A later phase (per HLD §16's V0–V8 evolution) reveals that a technology choice made for an earlier phase's scale no longer fits (e.g., Postgres/TimescaleDB approaching a genuine capacity limit, or the Research Brain's compute needs outgrowing the "no message broker" decision in §10).

**Next recommended step:** the operator reviews and confirms/revises §4 (language), §6 (storage), §9 (ML framework), and §10 (no message broker) as the highest-leverage proposals; in parallel, resolve the open items in §20 (particularly compute budget and broker selection) so §16/§17 can move from shortlist to decision; then proceed to per-component LLD work, starting with the safety-critical isolated component (Risk Engine/Supervisor/kill switch), consistent with HLD §19's own recommended sequencing.
