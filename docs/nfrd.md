# Non-Functional Requirements Document (NFRD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Non-Functional Requirements Document (NFRD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1, PRD v0.1, BRD v0.1, SOW v0.1, and FRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, AI Trader BRD v0.1, AI Trader SOW v0.1, AI Trader FRD v0.1 |

---

## 1. Purpose of This Document

The FRD specifies *what each module must do*. This NFRD specifies *how well, how reliably, how safely, and how observably* it must do it — the quality attributes that apply across modules regardless of specific function.

The PRD (§8) explicitly deferred quantitative NFR targets to this document, stating they "must not be assumed from the PRD." Consistent with the project's engineering principle of never silently inventing critical requirements, this NFRD distinguishes clearly between:

- **Structural/qualitative NFRs** that follow directly from the Master Context, PRD, and BRD (e.g., "safety logic must be deterministic") — these are stated firmly.
- **Quantitative targets** (specific numbers: latency in ms, uptime %, drawdown ₹/%, etc.) that have **not yet been supplied by the operator** — these are presented as placeholders with a proposed default and rationale, explicitly flagged for operator sign-off rather than silently finalized.

No number in this document should be treated as final until the operator has explicitly confirmed it in §14.

---

## 2. Scope

This NFRD applies to every module defined in the FRD (Modules 1–12) and covers the following quality attribute categories:

1. Reliability & Availability
2. Performance & Latency
3. Safety & Determinism
4. Data Quality & Integrity
5. Security
6. Auditability & Observability
7. Scalability
8. Maintainability & Modularity
9. Testability
10. Usability (Dashboard)
11. Compliance
12. Cost Efficiency
13. Disaster Recovery & Business Continuity

Each category below follows the FRD's module IDs (e.g., `FRD-RISK-*`, `FRD-EXEC-*`) where a specific NFR quantifies or constrains a functional requirement.

---

## 3. Reliability & Availability

| ID | Requirement | Status |
|---|---|---|
| NFR-REL-1 | The system shall be available and operating during all applicable market hours for the configured instruments, once deployed to live trading (V5+). | Structural |
| NFR-REL-2 | **Target uptime during market hours:** *proposed 99.5%* (≈ up to ~2 minutes downtime per trading day equivalent). | **Placeholder — needs operator confirmation** |
| NFR-REL-3 | A single agent (FRD-SIG module) failure shall not cause system-wide downtime (per FRD-SIG-3); the system shall degrade gracefully to fewer active signals rather than halting. | Structural |
| NFR-REL-4 | A broker/data connection failure shall trigger reconnection logic (FRD-EXEC-7) within a bounded time; **proposed reconnection attempt window: 30 seconds before escalating to Risk Engine (FRD-RISK-9) and human notification.** | **Placeholder — needs operator confirmation** |
| NFR-REL-5 | The system shall not lose in-flight order or position state on process restart; state shall be reconciled against the broker on startup (extends FRD-EXEC-7). | Structural |
| NFR-REL-6 | Mean time to recovery (MTTR) from a detected system fault shall be tracked from V8 onward as an operational metric, with a **proposed target of under 15 minutes for non-critical faults.** | **Placeholder — needs operator confirmation** |

---

## 4. Performance & Latency

| ID | Requirement | Status |
|---|---|---|
| NFR-PERF-1 | The system is **not** designed for ultra-low-latency/high-frequency operation by default (PRD §4.3 Non-Goals; FRD-EXEC-9: correctness over speed). | Structural |
| NFR-PERF-2 | End-to-end decision latency (data received → Supervisor decision) shall be bounded and monitored; **proposed target: under 5 seconds for the initial (non-HFT) timeframes (5-minute and above).** Shorter timeframes, if enabled later, would require this NFR to be revisited. | **Placeholder — needs operator confirmation** |
| NFR-PERF-3 | Order submission latency (Supervisor approval → order sent to broker) shall be bounded and monitored; **proposed target: under 2 seconds under normal conditions.** | **Placeholder — needs operator confirmation** |
| NFR-PERF-4 | Backtesting throughput shall be sufficient to complete a full out-of-sample + walk-forward + stress-test cycle for a candidate model within a practical research iteration time; **proposed target: under 24 hours per candidate on the operator's available compute**, revisited once compute resources are known (open item carried from SOW §12 item 5). | **Placeholder — needs operator confirmation and compute-resource decision** |
| NFR-PERF-5 | Dashboard data (Module 11) shall refresh at an interval sufficient for monitoring without materially loading the Trading Brain; **proposed refresh interval: 1–5 seconds for live state, up to 60 seconds for learning/system-health views.** | **Placeholder — needs operator confirmation** |

---

## 5. Safety & Determinism

This category directly enforces BRD BR-1, BR-4, BR-5 and FRD Module 6/7/11, and is treated as **non-negotiable** rather than a placeholder category — these are structural requirements regardless of numeric tuning.

| ID | Requirement |
|---|---|
| NFR-SAFE-1 | All hard risk limits (FRD-RISK-3 through FRD-RISK-10) shall be implemented using deterministic logic (rule evaluation, not model inference) and shall execute independently of the availability or correctness of any AI/LLM component. |
| NFR-SAFE-2 | The kill switch (FRD-RISK-12) and manual STOP (FRD-DASH-7) shall have a dedicated, minimal-dependency code path such that a failure elsewhere in the system (e.g., a crashed agent, a slow model call) cannot prevent STOP from taking effect. |
| NFR-SAFE-3 | Kill-switch/STOP activation shall take effect within a bounded, tested time; **proposed target: under 2 seconds from operator command to "no new orders will be submitted" state**, independent of market conditions for the "halt new entries" mode. | 
| NFR-SAFE-4 | The Risk Engine (Module 6) shall be tested to demonstrate it blocks a disallowed action even when all upstream agents/models recommend it (proving independence, per NFR-SAFE-1) — this test must be part of the V5 acceptance criteria (SOW §6.6) and re-run on every Risk Engine change. |
| NFR-SAFE-5 | No code path shall exist by which the Research Brain (Module 10) can directly invoke the Execution Engine (Module 8) or modify live risk-limit configuration (implements FRD-X-4); this shall be verified structurally (e.g., dependency/interface review), not merely by convention. |
| NFR-SAFE-6 | Safety-critical logic (Modules 6, 7, 11 STOP path) shall have materially higher test coverage requirements than non-safety modules — **proposed: 100% branch coverage for Modules 6/7/11 safety paths**, vs. a lower bar elsewhere (see §9 Testability). |

**NFR-SAFE-3 and NFR-SAFE-6's specific numbers are placeholders pending operator confirmation; NFR-SAFE-1, 2, 4, 5 are structural and not subject to relaxation.**

---

## 6. Data Quality & Integrity

| ID | Requirement | Status |
|---|---|---|
| NFR-DATA-1 | Ingested market data shall be validated for staleness against a defined maximum age before being used in a live decision; **proposed staleness threshold: data older than 10 seconds for real-time price data is treated as stale for live decisioning** (looser thresholds may apply to slower-moving data like fundamentals/news). | **Placeholder — needs operator/technical confirmation, may vary by data type and timeframe** |
| NFR-DATA-2 | Data validation failures (FRD-DATA-7) shall be logged with sufficient detail to distinguish a vendor outage from a data-quality defect. | Structural |
| NFR-DATA-3 | Historical data used for backtesting/training shall be checked for known bias sources (look-ahead, survivorship) as part of an automated or documented manual data-integrity review before use (extends FRD-DATA-6 to offline data). | Structural |
| NFR-DATA-4 | Feature and decision-record data (FRD-FEAT-3, FRD-EVAL-1) shall be immutable once written — corrections shall be appended as new records, not edits to historical records, to preserve audit integrity. | Structural |

---

## 7. Security

| ID | Requirement | Status |
|---|---|---|
| NFR-SEC-1 | Broker API credentials and any other secrets shall be stored using a secrets-management approach that avoids plaintext storage in code, logs, or version control. | Structural |
| NFR-SEC-2 | All network communication with the broker, data vendors, and any remote services shall use encrypted transport (TLS or equivalent). | Structural |
| NFR-SEC-3 | Access to the manual STOP and to capital-scaling actions (Module 12) shall be restricted to authenticated operator access; **exact authentication mechanism (password, hardware key, etc.) to be defined in Security Design.** | **Placeholder — mechanism TBD in Security Design** |
| NFR-SEC-4 | The system shall maintain an audit trail of who (operator vs. system) initiated any capital-scaling, STOP, or model-promotion action (extends FRD-EVAL-1/FRD-CAP-4/FRD-LEARN-8 with actor identity). | Structural |
| NFR-SEC-5 | Given this is a single-operator system (BRD §5), multi-user access control is **out of scope** unless the project's scope changes to managing capital for others (BRD §11 item 8), which would require this NFRD to be revisited. | Structural (scope note) |
| NFR-SEC-6 | Dependencies (libraries, models, data-vendor SDKs) shall be tracked for known vulnerabilities; **proposed cadence: review before each phase deployment (V0–V8), not on a fixed calendar schedule given single-operator scale.** | **Placeholder — cadence to be confirmed** |

---

## 8. Auditability & Observability

This category quantifies FRD Module 9 (Evaluation & Explainability) and BRD BR-7 (full auditability).

| ID | Requirement | Status |
|---|---|---|
| NFR-AUDIT-1 | 100% of Supervisor decisions (including NO TRADE) shall produce a complete decision record (FRD-EVAL-1) — this is a hard target, not a placeholder, since partial auditability would violate BRD BR-7. | Structural (100% target) |
| NFR-AUDIT-2 | Decision records shall be retrievable by the operator within a bounded time of request; **proposed target: under 5 seconds for a single-decision lookup, under 60 seconds for a bulk/date-range export.** | **Placeholder — needs operator confirmation** |
| NFR-AUDIT-3 | System health/observability data (FRD-DASH-6) shall be logged continuously, not only sampled at dashboard refresh, so that a failure between refreshes is still captured in logs. | Structural |
| NFR-AUDIT-4 | Logs and decision records shall be retained for the full operating history of the system by default; **any log/record deletion or archival policy requires explicit operator approval** (retention mechanics to be finalized in DDD, per FRD-EVAL-5). | Structural (retention default), mechanics placeholder |
| NFR-AUDIT-5 | Alerting shall notify the operator (channel TBD — e.g., push notification, SMS, email) within a bounded time of a Risk Engine breach, kill-switch activation, or broker/data disconnection; **proposed target: under 60 seconds from event to notification attempt.** | **Placeholder — channel and target need operator confirmation** |

---

## 9. Scalability

| ID | Requirement | Status |
|---|---|---|
| NFR-SCALE-1 | The architecture shall support adding new instruments, data sources, or agents without a full system rewrite (FRD-DATA-8; PRD NFR Scalability). | Structural |
| NFR-SCALE-2 | The system shall be designed to handle the data/compute load of the initial scope (NSE equities + NIFTY-related instruments, single operator) without premature over-engineering for a scale not yet justified by the ₹10,000 initial capital (PRD NFR Cost efficiency). | Structural |
| NFR-SCALE-3 | Capacity headroom (e.g., number of instruments, agents, or concurrent positions the architecture can support before requiring re-architecture) shall be documented in the HLD/TTD so scaling limits are known in advance, not discovered under load. | Structural (deferred to HLD/TTD for specifics) |

---

## 10. Maintainability & Modularity

| ID | Requirement | Status |
|---|---|---|
| NFR-MAINT-1 | Any AI model or agent (Module 4, Module 10) shall be replaceable without modifying the Execution Engine (Module 8) or Risk Engine (Module 6) interfaces (PRD NFR Modularity/Replaceability). | Structural |
| NFR-MAINT-2 | All models, strategies, datasets, and schemas shall be versioned (FRD-FEAT-3, FRD-LEARN-6); version identifiers shall appear in every decision record. | Structural |
| NFR-MAINT-3 | Configuration values referenced as placeholders throughout this NFRD and the FRD (risk limits, thresholds, cadences) shall be externalized as configuration, not hardcoded, so they can be tuned without a code change and redeployment. | Structural |
| NFR-MAINT-4 | Backward compatibility shall be preserved where practical as the system evolves (PRD §12 Constraints); breaking changes to decision-record schema or risk-limit configuration format require a documented migration path. | Structural |

---

## 11. Testability

| ID | Requirement | Status |
|---|---|---|
| NFR-TEST-1 | Every module in the FRD shall be independently testable in isolation before integration (PRD §29 item 16; Master Context Core Engineering Principle §26). | Structural |
| NFR-TEST-2 | No component shall be marked "production-ready" without documented test evidence (PRD §29 item 11). | Structural |
| NFR-TEST-3 | Safety-critical modules (Risk Engine, Supervisor, kill switch/STOP) shall meet the elevated coverage bar in NFR-SAFE-6; other modules' coverage targets are **proposed at 80% line coverage as a general baseline**, to be confirmed per-module in the Test Strategy document. | **Placeholder — general baseline needs confirmation** |
| NFR-TEST-4 | The backtesting engine (FRD Module 2 support, per PRD FR-25–27) shall itself be tested against known-answer scenarios (e.g., a synthetic dataset with a known optimal outcome) to validate it does not introduce look-ahead or survivorship bias. | Structural |

---

## 12. Usability (Dashboard)

| ID | Requirement | Status |
|---|---|---|
| NFR-UX-1 | The manual STOP control (FRD-DASH-7) shall be visually prominent and reachable in no more than one interaction (e.g., one click/tap) from the dashboard's default view, on any supported device. | Structural |
| NFR-UX-2 | Risk status (FRD-DASH-4) and system health (FRD-DASH-6) shall use clear visual state indicators (e.g., normal/warning/critical) rather than requiring the operator to interpret raw numbers to assess safety state. | Structural |
| NFR-UX-3 | Dashboard access shall be available remotely (not only from a machine physically co-located with the trading system), given the operator will need to monitor and potentially STOP the system without being at a specific desk; **exact remote-access mechanism (web app, mobile app, etc.) to be defined in UI/UX Spec.** | **Placeholder — mechanism TBD** |

---

## 13. Compliance

| ID | Requirement | Status |
|---|---|---|
| NFR-COMP-1 | No live trading (V5+) shall begin until applicable Indian regulatory/exchange requirements for algorithmic trading have been reviewed and satisfied (BRD BR-9, SOW §9 precondition 1). | Structural (hard precondition) |
| NFR-COMP-2 | The system shall retain records in a form and duration sufficient to support any applicable regulatory audit or reporting requirement for algorithmic trading in India — **specific requirements pending regulatory review (open item, carried from BRD/SOW).** | **Placeholder — pending regulatory review** |
| NFR-COMP-3 | This NFRD does not itself certify regulatory compliance; compliance sign-off is a separate, specialist activity out of this document's scope (consistent with SOW §5 Out-of-Scope). | Structural (scope note) |

---

## 14. Quantitative Targets Requiring Operator Sign-Off

This is the consolidated list of every placeholder numeric/parametric value proposed above. **None of these are final.** They are proposed defaults, reasonable for a small-capital, single-operator, non-HFT system, offered so design work is not blocked — but each should be explicitly confirmed, adjusted, or rejected by the operator before being carried into the Risk & Trading Logic Design, TTD, or Test Strategy documents.

| ID | Parameter | Proposed Default | Confirmed? |
|---|---|---|---|
| NFR-REL-2 | Market-hours uptime target | 99.5% | ☐ Pending |
| NFR-REL-4 | Reconnection window before escalation | 30 seconds | ☐ Pending |
| NFR-REL-6 | MTTR target (non-critical faults) | < 15 minutes | ☐ Pending |
| NFR-PERF-2 | End-to-end decision latency | < 5 seconds | ☐ Pending |
| NFR-PERF-3 | Order submission latency | < 2 seconds | ☐ Pending |
| NFR-PERF-4 | Backtest cycle time per candidate | < 24 hours | ☐ Pending (also depends on compute-resource decision) |
| NFR-PERF-5 | Dashboard refresh interval | 1–5s live / 60s other | ☐ Pending |
| NFR-SAFE-3 | Kill-switch/STOP activation time | < 2 seconds | ☐ Pending |
| NFR-SAFE-6 | Safety-module test coverage | 100% branch coverage | ☐ Pending |
| NFR-DATA-1 | Real-time data staleness threshold | 10 seconds | ☐ Pending |
| NFR-SEC-3 | STOP/capital-action auth mechanism | TBD | ☐ Pending |
| NFR-SEC-6 | Dependency vulnerability review cadence | Per phase deployment | ☐ Pending |
| NFR-AUDIT-2 | Decision-record lookup time | < 5s single / < 60s bulk | ☐ Pending |
| NFR-AUDIT-5 | Alert notification time & channel | < 60 seconds, channel TBD | ☐ Pending |
| NFR-TEST-3 | General module test coverage baseline | 80% line coverage | ☐ Pending |
| NFR-UX-3 | Remote dashboard access mechanism | TBD | ☐ Pending |
| NFR-COMP-2 | Regulatory record-retention specifics | TBD | ☐ Pending regulatory review |

---

## 15. Risks of Deferred Quantification

| Risk | Impact | Mitigation |
|---|---|---|
| HLD/TTD proceeds using unconfirmed placeholder values as if final | Design decisions may need rework once operator confirms real targets | This NFRD explicitly marks every placeholder; HLD must cite NFR-IDs and flag any that remain unconfirmed |
| Operator has no strong opinion on some parameters (e.g., latency) | Placeholders may get implicitly accepted by default rather than deliberately chosen | Recommend operator explicitly reviews §14 table rather than assuming silence = approval |
| Safety-critical placeholders (NFR-SAFE-3, NFR-SAFE-6) are treated with the same casualness as convenience ones (e.g., dashboard refresh) | Under-resourcing of safety testing | This NFRD separates Safety (§5) as structurally non-negotiable even though specific numbers are still placeholders — the *requirement* to have deterministic, independently-tested safety logic is not optional; only the exact numeric thresholds are pending |

---

## 16. Traceability

| NFRD Category | FRD Reference | BRD Reference |
|---|---|---|
| Reliability & Availability | FRD-EXEC, FRD-DATA-9 | — |
| Performance & Latency | FRD-EXEC-9, Module 2 | — |
| Safety & Determinism | FRD Module 6, 7, FRD-DASH-7, FRD-X-1–5 | BR-1, BR-4, BR-5 |
| Data Quality & Integrity | FRD Module 1 | — |
| Security | FRD Module 8, 11, 12 | — |
| Auditability & Observability | FRD Module 9 | BR-7 |
| Scalability | FRD-DATA-8 | — |
| Maintainability & Modularity | FRD-FEAT-3, FRD-LEARN-6 | — |
| Testability | (all modules) | — |
| Usability | FRD Module 11 | BR-5 |
| Compliance | — | BR-9 |

Every NFR-ID should be added to the Requirements Traceability Matrix alongside its related FRD-ID(s), per PRD §14/Master Context §27.

---

## 17. Document Governance

This NFRD must be revisited whenever:
- Any value in §14 is confirmed, changed, or rejected by the operator.
- Regulatory review (NFR-COMP-1/2) produces findings affecting retention, reporting, or latency requirements.
- The compute/infrastructure decision (SOW §12 item 5) is made, which directly affects NFR-PERF-4.
- Scope changes to multi-user/managing others' capital (would reopen NFR-SEC-5).

**Next recommended step:** operator reviews and confirms/adjusts the §14 table, then proceed to HLD — starting, per the FRD's own recommendation, with the core decision architecture (Modules 3–7), since Safety & Determinism (§5) and Auditability (§8) place the tightest structural constraints on that design.