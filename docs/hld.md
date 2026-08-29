# High-Level Design (HLD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | High-Level Design (HLD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD, BRD, FRD, NFRD, SOW, TRD, RTLD, BTD, DDD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader FRD v0.1, NFRD v0.1, TRD v0.1, RTLD v0.1, BTD v0.1, DDD v0.1 |

---

## 1. Purpose of This Document

The FRD defines *what* each module must do; the NFRD defines *how well*; the TRD defines *what technical properties* the implementation must have, without choosing an architecture pattern (TRD-ARCH-5 explicitly leaves this open). This HLD is where that choice — and the overall system architecture built on it — is actually made: how the twelve FRD modules are grouped into deployable components, how they communicate, where the Trading Brain/Research Brain boundary is drawn physically (not just logically), where the safety-critical isolation required by NFR-SAFE-2 is enforced structurally, and how the architecture evolves across the V0–V8 roadmap without a rewrite at each phase.

This HLD does not select specific products, languages, or cloud providers — those remain TTD/ADR decisions, made against the architecture and constraints defined here. Where this HLD makes an architectural choice among several TRD-permitted options (e.g., TRD-ARCH-5's "monolith vs. microservices" question), that choice is presented as a **reasoned proposal**, flagged for operator confirmation, consistent with how RTLD/BTD numeric choices were handled.

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| Priority order for any architecture trade-off: reliability > maintainability > correctness > observability > performance > scalability > cost efficiency. | TRD §3 |
| The Trading Brain and Research Brain must be technically isolated — separate deployable units, separate credentials, no shared write-path to live execution or live risk configuration. | TRD-ARCH-2 |
| Safety-critical components (Risk Engine, Supervisor, kill switch) must have minimal runtime dependencies so their availability is not coupled to less-reliable components. | TRD-ARCH-3 |
| A single, canonical decision-record schema is used consistently by every module that logs a decision. | TRD-ARCH-4; DDD §5.2 |
| At least three technically separated environments (research/backtest, paper, live) must exist, with configuration never shared by default between paper and live. | TRD-DEPLOY-1/2 |
| No architecture choice may improve a lower-priority attribute (e.g., performance, cost) at the expense of a higher-priority one (e.g., reliability) without explicit operator sign-off. | TRD §3 |
| Avoid unnecessary complexity — architecture should be no more elaborate than the ₹10,000-scale, single-operator project currently justifies. | TRD Guiding Principle 7; NFR-SCALE-2 |
| The architecture must not preclude the V0–V8 roadmap's later phases, but must not be over-built for phases not yet reached. | BRD BR-8; SOW §11 |

This HLD converts these constraints into an actual system shape — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:** overall architecture pattern selection; system context (external actors/integrations); module-to-component mapping; the Trading Brain/Research Brain physical boundary; safety-critical path isolation design; inter-module interface/contract style; environment/deployment topology across research, paper, and live modes; how the architecture evolves phase-by-phase (V0–V8); failure-mode handling at the architecture level (broker/data outages, restart/reconciliation); and how this architecture consumes the DDD's data model, RTLD's risk rules, and BTD's backtesting design without re-specifying them.

**Out of scope:** specific technology/vendor selection (TTD, ADRs); detailed algorithms inside any module (LLD, MLD); the full API contract specification (API Spec document); detailed security controls and threat model (Security Design); detailed observability tooling choice (Observability Design); UI/UX layout of the dashboard (UI/UX Spec).

---

## 4. Architectural Style Decision

TRD-ARCH-5 leaves the pattern (monolith-with-modules vs. modular monolith vs. microservices) open, requiring only that whichever is chosen satisfies TRD-ARCH-1–4.

**Proposed decision: a modular monolith for the Trading Brain, with the Research Brain as a fully separate deployable unit, and the safety-critical path (Risk Engine + Supervisor + kill switch) further isolated as a minimal-dependency internal component within the Trading Brain — not a separate service.**

| Consideration | Why this shape |
|---|---|
| Guiding Principle 7 (avoid unnecessary complexity) | A full microservices architecture at ₹10,000 scale, single-operator, would add operational complexity (service discovery, network calls between every module, distributed-transaction concerns for TRD-DATA-2's transactional-integrity requirement) with no corresponding benefit yet. |
| TRD-ARCH-1 (modular boundaries) | A modular monolith still requires each FRD module to sit behind a documented internal interface (TRD-API-1) so it can be modified, tested, or later extracted into its own service without a rewrite — modularity is achieved through code/interface boundaries, not necessarily network boundaries. |
| TRD-ARCH-2 (Trading Brain/Research Brain isolation) | This is the one boundary that **must** be a real deployment boundary, not just a code boundary — the Research Brain runs as a separate process/deployment with its own credentials and no write-path to live execution or capital allocation (DDD §14), satisfying NFR-SAFE-5's requirement that this be structurally, not conventionally, true. |
| TRD-ARCH-3 (safety-critical minimal dependencies) | Within the Trading Brain monolith, Risk Engine + Supervisor + kill switch are structured as an isolated internal module with no call-out to model-inference services, external LLM APIs, or the general-purpose event bus (TRD-MSG-2) — reachable via a short, direct code path so a slow/crashed agent elsewhere cannot block a risk check or STOP. |
| Future extraction | If a specific module later justifies extraction (e.g., Feature Engineering becomes a genuine bottleneck, or Research Brain compute needs to scale independently — already a separate deployment), the interface discipline from TRD-API-1 makes that extraction incremental, not a rewrite. |

**This is a proposal, not a finalized decision** — it should be confirmed or revised by the operator, particularly if the compute-hosting model (TRD-COMPUTE-5, still open) turns out to favor a different shape.

---

## 5. System Context

External actors and systems the architecture must integrate with, and the nature of each boundary:

```
                    ┌──────────────────────────────┐
                    │        System Owner /         │
                    │       Operator (human)        │
                    │  - reviews dashboard           │
                    │  - approves model promotion    │
                    │  - approves capital scaling    │
                    │  - manual STOP authority        │
                    └───────────────┬────────────────┘
                                    │ (authenticated UI/API — TRD-API-3, TRD-SEC-3)
                                    ▼
        ┌───────────────────────────────────────────────────────┐
        │                    AI TRADER SYSTEM                     │
        │                                                          │
        │   ┌───────────────┐        ┌───────────────────────┐   │
        │   │ Trading Brain  │        │   Research Brain        │   │
        │   │ (live/paper)   │        │ (offline, isolated —    │   │
        │   │                │        │  TRD-ARCH-2, FRD-X-4)   │   │
        │   └───────┬────────┘        └────────────┬─────────┘   │
        └───────────┼────────────────────────────────┼───────────┘
                     │                                │
     ┌───────────────┼───────────────┐                │ (historical data only,
     ▼                ▼               ▼                ▼  read-only — DDD §14)
┌─────────┐   ┌──────────────┐  ┌───────────┐   ┌───────────────┐
│  Broker  │   │ Market Data  │  │  Exchange  │   │  Historical    │
│   API    │   │  Vendor(s)   │  │ (indirect, │   │  Data Store    │
│(orders,  │   │ (OHLCV, tick,│  │via broker/ │   │ (shared with   │
│ fills,   │   │ depth, deriv,│  │data vendor)│   │  Trading Brain │
│ positions)│  │ fundamentals,│  │            │   │  per TRD-PIPE-3)│
│          │   │ news)        │  │            │   │                │
└─────────┘   └──────────────┘  └───────────┘   └───────────────┘
```

Both the Broker API and Market Data Vendor(s) are still open selections (PRD §6.3, TRD-EXEC-6, TRD-PIPE-5) — the architecture below treats both as abstracted interfaces (§9) precisely so that selection can happen without redesigning the system around it.

---

## 6. Module-to-Component Mapping

The FRD's twelve modules map to architectural components as follows. "Deployment unit" indicates whether a module ships as part of the Trading Brain monolith, the Research Brain, or is shared.

| FRD Module | Component | Deployment Unit |
|---|---|---|
| 1. Data Ingestion & Validation | **Data Pipeline** — pluggable adapters (TRD-PIPE-1) behind a common contract (DDD §11) | Shared library, invoked by both Trading Brain (real-time) and Research Brain (bulk historical), per TRD-PIPE-3 |
| 2. Feature Engineering | **Feature Engine** | Shared library — single source of truth (FRD-FEAT-4), invoked live and offline |
| 3. Market Regime Detection | **Regime Detector** | Trading Brain (live), also invoked by Research Brain for regime-partitioned backtesting (BTD §8.6) |
| 4. Signal Generation (multi-agent) | **Agent Roster** — one sub-component per agent (final roster per §14 open item) | Trading Brain (live/paper); Research Brain (training/backtesting versions of the same agent logic) |
| 5. Signal Aggregation & Trade Quality Scoring | **Aggregator** | Trading Brain |
| 6. Risk Engine | **Risk Engine** — isolated, minimal-dependency (§4, §8) | Trading Brain only — never present in Research Brain (FRD-X-4) |
| 7. Supervisor / Decision Gate | **Supervisor** — isolated alongside Risk Engine | Trading Brain only |
| 8. Execution Engine | **Execution Engine** | Trading Brain only (live and paper modes — §11); Research Brain has no path to this component at all (TRD-ARCH-2) |
| 9. Trade Evaluation & Explainability | **Evaluation Service** | Trading Brain (live/paper evaluation) + Research Brain (backtest run evaluation) — both write to the same DecisionRecord/TradeEvaluation schema (DDD §5.2/§5.3), never divergent schemas |
| 10. Learning & Model Lifecycle | **Learning Pipeline** | Research Brain — candidate generation, validation (per BTD §8), promotion recommendation; **actual promotion action** requires crossing into Trading Brain's model-serving slot via a controlled, audited handoff (§8), not a direct write |
| 11. Dashboard & Human Control | **Dashboard/Control Service** | Shared — reads from both Trading Brain and Research Brain via defined APIs only (TRD-API-2), never direct storage access; hosts the manual STOP control, wired directly to the Risk Engine's kill-switch path (§8) |
| 12. Capital & Growth Management | **Capital Manager** | Trading Brain — evaluates RTLD §15 criteria and reports; capital changes require operator action via Dashboard/Control Service, never self-actuated (FRD-X-4-adjacent) |

---

## 7. Trading Brain Internal Data Flow

Within the Trading Brain, a single evaluation cycle flows in the fixed order already established by RTLD §13 — this HLD shows it as a component pipeline:

```
Market Data (real-time)
     │
     ▼
[Data Pipeline] → validate → tag quality state (DDD §7: RAW/VALIDATED/QUARANTINED)
     │  (quarantined data suppressed per FRD-DATA-9 → forced NO TRADE for that instrument)
     ▼
[Feature Engine] → versioned FeatureSet (DDD §8)
     │
     ▼
[Regime Detector] → RegimeClassification
     │
     ▼
[Agent Roster] → AgentSignalOutput[] (per-agent, per-model-version)
     │
     ▼
[Aggregator] → AggregationResult (trade quality score, expected value)
     │
     ▼
┌─────────────────────────────────────────────────────┐
│   SAFETY-CRITICAL BOUNDARY (TRD-ARCH-3)                │
│                                                        │
│   [Risk Engine] → evaluates RTLD §5–§12 checklist      │
│         │ (all-must-pass; any breach blocks)           │
│         ▼                                              │
│   [Supervisor] → consults Risk Engine result            │
│         │ (cannot approve what Risk Engine blocked —    │
│         │  FRD-SUP-2/6; kill switch/STOP forces          │
│         │  HOLD/exit-only — FRD-SUP-5, FRD-X-5)          │
└─────────┼──────────────────────────────────────────────┘
          ▼
   Final decision: BUY / SELL / HOLD / NO TRADE
          │
          ├──────────────► [Evaluation Service] → DecisionRecord (always, every cycle — FRD-X-3)
          │
          ▼ (only if BUY/SELL and approved)
   [Execution Engine] → Broker API
          │
          ▼
   Fill → [Evaluation Service] updates Position/TradeEvaluation
```

Every arrow into **Evaluation Service** happens unconditionally — including for NO TRADE and HOLD outcomes — so FRD-X-3's "no module may bypass Module 9 logging" is a structural property of the pipeline shape, not an add-on step some code paths could skip.

---

## 8. Safety-Critical Path Isolation

Per TRD-ARCH-3 and NFR-SAFE-2, the Risk Engine + Supervisor + kill switch form a single isolated unit with these architectural properties:

- **No required call-out** to the Agent Roster's model-inference services, any external LLM API, or the general-purpose internal event bus (if one exists — TRD-MSG-2/4) to evaluate a block or to activate the kill switch. Its inputs are: current capital/exposure state, the candidate trade's parameters, and the RTLD parameter register (RTLD §14) — all deterministic, locally available data.
- **Manual STOP wiring**: the Dashboard's STOP control (FRD-DASH-7) connects to the kill switch via the shortest possible path — ideally a direct function call or a dedicated, minimal-dependency channel — not routed through the Aggregator, Agent Roster, or any component that could be slow, crashed, or degraded (NFR-SAFE-2). This satisfies the <2 second activation target (RTLD-17/NFR-SAFE-3) by removing intermediate hops that could introduce latency or failure points.
- **No AI/LLM component sits on this path** at all (BRD BR-4) — this is enforced by the component boundary itself: the Risk Engine and Supervisor components have no dependency edge, in the architecture diagram, pointing at the Agent Roster's model-serving components. A code review / dependency-graph check (NFR-SAFE-5's "verified structurally") should confirm no such edge exists before every deployment touching this component (TRD-CI-2).
- **Precedence enforcement** (FRD-X-5): the kill switch/STOP state is checked **first**, structurally — the Supervisor's decision logic reads kill-switch state before it reads the Aggregator's output, so an active kill switch short-circuits the pipeline regardless of what upstream components computed, rather than being one input among several that could be outweighed.

---

## 9. Integration Abstraction Layer

Both the Broker API and Market Data Vendor(s) sit behind internal abstraction interfaces, consistent with TRD-EXEC-4 and TRD-PIPE-1:

| Interface | Purpose | Consumers | Why abstracted |
|---|---|---|---|
| **Broker Adapter Interface** | Authenticate, place/modify/cancel orders, poll/receive fills, query positions | Execution Engine only | A broker change must not require touching Risk Engine, Supervisor, or Evaluation (TRD-EXEC-4) — those components speak only to this interface's stable internal contract, never to a vendor SDK directly. |
| **Data Source Adapter Interface** | Ingest OHLCV/tick/depth/derivatives/fundamentals/news, conforming to the DDD §11 data contract | Data Pipeline | Lets a vendor be added/replaced without touching Feature Engineering, Regime Detection, or any agent (FRD-DATA-8, TRD-PIPE-1). |

Both interfaces are designed now, ahead of the actual vendor/broker selections (still open, PRD §6.3), specifically so those selections don't force an architectural change later — the selections plug into an already-defined shape.

---

## 10. Trading Brain vs. Research Brain Boundary — Enforcement Detail

This is the one boundary in the system that must hold even under a bug, not just under normal operation (TRD-ARCH-2, FRD-X-4, NFR-SAFE-5):

| Enforcement Layer | Mechanism |
|---|---|
| **Deployment** | Separate deployable process/service; Research Brain can be offline entirely without affecting Trading Brain (TRD-COMPUTE-2). |
| **Credentials** | Research Brain holds no broker-live credentials at all — not scoped-down credentials, but genuinely none, since a scoping bug is still a bug. Where it needs market data, it uses the same Data Source Adapter Interface (§9) as the Trading Brain but pointed only at the historical data store (DDD §6), never the live feed's order-submission path (which doesn't exist on this side regardless). |
| **Network/code path** | No function call, API endpoint, or shared-database write permission from Research Brain code into Execution Engine or Capital Manager (DDD §14) — this must be checkable via a dependency/interface review (NFR-SAFE-5), not just asserted in documentation. |
| **Output path** | The Research Brain's only sanctioned output into the Trading Brain's world is a **promotion recommendation** (a ModelVersion + ValidationRunRecord evidence bundle, per DDD §5.4) — never a direct write to a live model-serving slot. Promotion itself (§13) is a controlled, audited, Supervisor-adjacent action gated by FRD-LEARN-5's risk-review step and, where required, explicit human sign-off (open item, BRD §11 item 6). |

---

## 11. Environment/Deployment Topology

Per TRD-DEPLOY-1–4, three environments exist with the same module architecture (§6) but different configuration and, for live, additional gating:

| Environment | Purpose | Execution Engine Behavior | Configuration |
|---|---|---|---|
| **Research/Backtest** | Historical replay only (V0+) | Not present/not invoked — no order submission path exists in this mode at all | Uses BTD's fill-simulation model (BTD §7), historical data store only |
| **Paper** | Real-time data, simulated execution (V4+) | Simulated fills against real-time market data, no broker order actually sent | Separate config from live (TRD-DEPLOY-2) — same RTLD limits applied for realism, but against notional capital (FRD-CAP-1) |
| **Live** | Real broker execution (V5+) | Real order submission via Broker Adapter | Live-only credentials; deployment requires the explicit, auditable action in TRD-DEPLOY-3, gated on SOW §9 preconditions being met |

A single build/release of the Trading Brain module code is what's promoted from Paper to Live (per V4→V5 in the roadmap) — the module logic does not fork between environments; only the Execution Engine's target (simulated vs. real broker) and the configuration set (RTLD/BTD parameter versions, credentials) differ. This is what makes paper-trading results actually predictive of live behavior (feeding RTLD §15's "live/paper divergence" scaling criterion) rather than testing a different code path.

---

## 12. Model Promotion Handoff (Architecture View)

Elaborating §10's "controlled, audited handoff": promotion is modeled as a state transition on a `ModelVersion` record (DDD §5.4), not a file copy or direct deployment action initiated by the Research Brain:

```
Research Brain: candidate ModelVersion completes BTD §8 pipeline
      → ValidationRunRecord[] (all stages) written
      → PromotionEvent proposed, evidence_ref populated
      → FRD-LEARN-5 risk review executed
      → [if required per BRD §11 item 6] human_signoff_ref populated
      → Supervisor-adjacent promotion component (Trading Brain side)
        reads the PromotionEvent, verifies evidence + signoff,
        and only then updates the live model-serving slot
      → RollbackEvent capability retained (prior ModelVersion never deleted — FRD-LEARN-6)
```

The component that actually flips the live model-serving slot lives on the **Trading Brain** side, not the Research Brain side — the Research Brain proposes, it never actuates, which is the architectural expression of BR-6 ("no unvalidated model touches live capital... the system itself may never decide").

---

## 13. Observability Architecture

Per TRD-OBS-1–5:
- Every component in §7's pipeline emits structured events into a single **Observability/Logging** cross-cutting layer — not free-text logs — covering decision records, order lifecycle events, risk evaluations, and system-health signals.
- This layer is architecturally **decoupled** from the safety-critical path (§8): a logging outage is detected and escalated (FRD-X-3, treated as a data-quality/system failure per RTLD §11) rather than silently blocking a risk check, and also never silently drops a decision-record write — this requires the logging layer to have its own failure-visibility, separate from whatever it's logging about.
- The Dashboard/Control Service (§6) and any alerting mechanism (NFR-AUDIT-5) both read from this single source of truth (TRD-OBS-4), rather than each independently probing individual components — this avoids the Dashboard becoming a second, potentially inconsistent audit trail alongside the "real" one in the DecisionRecord store (TRD-API-2's concern, generalized).

---

## 14. Failure Modes and Resilience (Architecture-Level)

| Failure | Architectural Response |
|---|---|
| **Broker/data disconnection** | Detected by the relevant Adapter Interface (§9); Data Pipeline/Execution Engine escalate to Risk Engine (FRD-EXEC-6, RTLD §11) after the reconnection window; new decisions for affected instruments (or system-wide, for broker loss) suppress toward NO TRADE, never proceed on stale assumed state. |
| **Unplanned restart/infrastructure failure** | On restart, the system reconciles position/order state against the broker (TRD-DR-2) before resuming automated decision-making; if reconciliation cannot be confirmed, the system defaults to a safe state (HOLD/NO TRADE only) until it succeeds or the operator intervenes (TRD-DR-3) — this is a startup-sequence requirement on the Execution Engine and Risk Engine components, not just an operational runbook step. |
| **Logging-layer outage** | Per §13, escalated as a system fault; the safety-critical path does not proceed "silently" without logging (FRD-X-3) — the architecture must make "risk-checked but unlogged" an impossible or at least loudly-flagged state, not a quiet degradation mode. |
| **Research Brain outage/crash** | No impact on Trading Brain by design (§10 deployment separation); Research Brain restart/recovery is lower-urgency (TRD-COMPUTE-2). |
| **A crashed or slow agent (Module 4)** | Does not block the Risk Engine/Supervisor/kill switch (§8's isolation) — worst case, that agent's signal is simply absent from the Aggregator's input for that cycle, potentially resulting in NO TRADE if aggregate confidence/quality then falls below RTLD §12's threshold, which is a safe failure direction. |

---

## 15. Relationship to RTLD, BTD, and DDD

This HLD is deliberately thin on numbers and schemas because those already have dedicated documents, referenced rather than duplicated:
- **Risk logic and limits**: the Risk Engine component (§6, §8) implements RTLD §5–§16 exactly; this HLD does not restate the numeric parameter register (RTLD §14).
- **Backtesting mechanics**: the Research Brain's Learning Pipeline component invokes the backtesting engine as designed in BTD §6–§11; this HLD does not restate cost/friction assumptions (BTD §13).
- **Data model**: every component's inputs/outputs above map to the DDD §5 entities; this HLD does not redefine schemas — where a component "writes a DecisionRecord," that is the DDD §5.2 entity, verbatim.

Any future change to RTLD, BTD, or DDD that affects a component boundary defined here (e.g., a new risk-check type requiring a new external dependency) must be reflected back into this HLD's §8 isolation guarantees, not silently absorbed into an implementation detail.

---

## 16. Phased Architecture Evolution (V0–V8)

The module-to-component mapping (§6) is the **target** shape; not every component is fully built at every phase. Per SOW §6 and BRD BR-8, phases add components incrementally without requiring earlier components to be rearchitected:

| Version | Architecture State |
|---|---|
| **V0** | Data Pipeline (historical/bulk only) + shared data store. No Trading Brain pipeline yet. |
| **V1** | + Backtesting engine (BTD) + one baseline strategy, invoked standalone — Aggregator/Risk Engine/Supervisor not yet present as gating components; the strategy's own logic stands in for them in this phase. |
| **V2** | + Feature Engine (versioned) + first ML model + Evaluation framework for backtest metrics. |
| **V3** | + Regime Detector, Agent Roster (initial validated subset — §17 item 1), Aggregator, **Risk Engine, Supervisor** (simulated, not live) — this is where the full pipeline shape in §7 first exists end-to-end, against simulated/backtest decisions. |
| **V4** | + real-time Data Pipeline mode, Execution Engine in **paper mode only** — Trading Brain now runs continuously per TRD-COMPUTE-1, against zero real capital. |
| **V5** | + Execution Engine **live mode**, live credentials, kill switch fully wired (§8), Dashboard STOP control live — the Live environment (§11) is stood up for the first time, gated on SOW §9 preconditions. |
| **V6** | + Research Brain as a genuinely separate deployment, Evaluation Service extended to post-trade analysis, Learning Pipeline (candidate generation) — Research Brain isolation (§10) becomes an operative boundary rather than a design-only one. |
| **V7** | + full promotion handoff (§12), automated rollback, dynamic timeframe/strategy selection logic inside the Agent Roster/Aggregator components. |
| **V8** | + production observability/alerting hardening (§13), Capital Manager's scaling mechanics (RTLD §15) fully wired to the Dashboard's operator-approval flow, reliability hardening across all failure modes in §14. |

No phase requires discarding a component built in an earlier phase — this is the specific test of whether §4's architectural choice actually satisfies BR-8's incremental-exposure principle at the technical level, not just the business-scope level.

---

## 17. Open Items Requiring Operator or Downstream Decision

1. **Confirm or revise §4's architectural style proposal** (modular monolith + isolated Research Brain) before HLD is treated as final.
2. **Compute hosting model** (self-hosted/cloud/hybrid, TRD-COMPUTE-5) — affects how "separate deployable unit" (§10) is physically realized.
3. **Broker and data-vendor selection** (PRD §6.3) — plugs into the abstraction interfaces in §9 without changing them, but selection is still needed before TTD/LLD can proceed on those adapters.
4. **Initial agent roster** (FRD-SIG-5 open item) — affects how many Agent Roster sub-components exist at V3.
5. **Human sign-off requirement for promotion** (BRD §11 item 6) — affects whether §12's `human_signoff_ref` step is populated automatically-within-gates or requires a manual operator action every time.
6. **Messaging/event mechanism necessity** (TRD-MSG-4) — this HLD assumes direct internal calls within the modular monolith are sufficient at this scale (§4) and does not introduce a dedicated message broker; revisit if Research Brain compute scaling or a future service-extraction (§4) changes this.
7. **Whether Regime Detector should also live in the safety-critical isolated boundary (§8)** — currently placed outside it since it does not itself block/approve trades, only classifies; confirm this doesn't create a hidden dependency the Risk Engine relies on without realizing it (worth a dependency-graph check at LLD stage).

---

## 18. Traceability

| HLD Section | Source Requirement(s) |
|---|---|
| §4 Architecture style | TRD-ARCH-1–5 |
| §5 System context | PRD §5 Stakeholders; FRD Module 1, 8 |
| §6 Module-to-component mapping | FRD Modules 1–12; TRD-ARCH-1 |
| §7 Trading Brain data flow | RTLD §13; FRD-X-1, FRD-X-3 |
| §8 Safety-critical isolation | TRD-ARCH-3; NFR-SAFE-1–5; FRD-X-5 |
| §9 Integration abstraction | TRD-EXEC-4; TRD-PIPE-1; DDD §11 |
| §10 Trading/Research Brain boundary | TRD-ARCH-2; FRD-X-4; NFR-SAFE-5 |
| §11 Environment topology | TRD-DEPLOY-1–4 |
| §12 Promotion handoff | FRD-LEARN-5/6/8; BRD BR-6 |
| §13 Observability architecture | TRD-OBS-1–5 |
| §14 Failure modes | TRD-DR-1–4; FRD-EXEC-6/7; RTLD §11 |
| §16 Phased evolution | SOW §6; BRD BR-8 |

Every component named in §6 should be entered into the Requirements Traceability Matrix against its FRD module ID, and every architectural boundary in §8/§10 should have a corresponding LLD-level verification test (per NFR-SAFE-4/5) confirming it holds in the actual implementation, not just in this diagram.

---

## 19. Document Governance

This HLD is a living document and must be reviewed whenever:
- §4's architectural style proposal is confirmed, revised, or rejected by the operator.
- Broker/data-vendor selection (§17 item 3) resolves, to confirm the abstraction interfaces (§9) hold as designed.
- Any phase in §16 reveals that a component needs restructuring beyond what was anticipated — this itself would be a signal worth surfacing to the operator, since one goal of this design is exactly to avoid that.
- The RTLD, BTD, or DDD change in a way that affects a component boundary (§15).

**Next recommended step:** the operator reviews and confirms §4 (architecture style) and the open items in §17; TTD work (concrete technology selection against this HLD's component boundaries) and LLD work on the safety-critical isolated component (§8) should proceed first, since it carries the most technical and safety risk per SOW §6.4's earlier flag on the core decision architecture.