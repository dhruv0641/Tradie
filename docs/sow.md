# Statement of Work (SOW)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Statement of Work (SOW) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1, PRD v0.1, and BRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, AI Trader BRD v0.1 |

---

## 1. Purpose of This Document

The PRD defines *what* the product must do, and the BRD defines *why* and under what business rules. This SOW defines *how the work will be carried out*: the phased work packages, deliverables, acceptance criteria, roles, exclusions, and governance for actually building the system.

This SOW covers delivery of the full V0–V8 roadmap at a phase level. Because timelines, budget, and staffing have not yet been decided by the operator (see BRD §11, Open Business Questions), this SOW defines **scope and acceptance criteria per phase** rather than committing to fixed dates or costs. Those must be layered in once the relevant open questions are resolved.

---

## 2. Engagement Overview

| | |
|---|---|
| **Client / Operator** | System Owner (the user) — sole stakeholder, capital owner, final approval authority |
| **Delivery Party** | To be determined — may be the operator themself, a developer/quant engaged by the operator, or an AI-assisted build process (e.g., Claude Code) directed by the operator |
| **Engagement Type** | Phased, incremental delivery (V0 through V8), gated by exit criteria per phase |
| **Initial Capital at Risk** | ₹0 through V4 (research/backtest/paper only); ₹10,000 experimental capital from V5 onward, subject to BRD Business Rules |
| **Governing Documents** | PRD v0.1, BRD v0.1, and this SOW; downstream FRD/NFRD/HLD/TTD/LLD etc. must remain consistent with all three |

---

## 3. Objectives of This Engagement

Per BRD §3 Business Objectives, this SOW exists to deliver a system that:
- Preserves capital as the first priority (BO-1, BO-5).
- Earns the right to manage more capital only through evidenced, staged delivery (BO-2, BO-6).
- Replaces ad hoc manual trading with a disciplined, auditable process (BO-3, BO-4).
- Remains overridable by the operator at all times (BO-7).

This SOW's phase structure is itself a control: it operationalizes BR-8 (Incremental risk exposure) by ensuring business/financial risk is only introduced (V5+) after non-financial-risk phases (V0–V4) are complete and validated.

---

## 4. In-Scope Work

This SOW covers the design, build, testing, and staged deployment of the AI Trader system across the following phases, consistent with PRD §13 and BRD §7.2 (target future-state business process):

| Phase | Name | Nature of Work |
|---|---|---|
| V0 | Research Foundation | Data ingestion pipelines, database setup, basic analytics tooling |
| V1 | Backtesting Trader | Strategy scaffolding, backtesting engine with realistic cost modeling |
| V2 | ML Trader | Feature engineering pipeline, predictive model training and evaluation |
| V3 | Multi-Agent Trader | Regime detection, signal generation, risk engine, decision architecture |
| V4 | Paper Trader | Real-time data integration, simulated (non-live) execution |
| V5 | Autonomous Risk-Controlled Trader | Broker integration, hard risk controls, limited live capital deployment |
| V6 | Self-Learning Trader | Trade evaluation pipeline, research pipeline, candidate model generation |
| V7 | Adaptive Autonomous Trader | Controlled model promotion pipeline, dynamic strategy/timeframe selection |
| V8 | Scalable Production System | Monitoring, reliability hardening, capital-scaling mechanics, mature operations |

Also in scope, spanning all phases:
- Production of the documentation set defined in PRD §14/Master Context §28 (FRD, NFRD, HLD, TTD, LLD, ADD, DDD, MLD, Risk & Trading Logic Design, Execution Design, Backtesting Design, Self-Learning Design, API Spec, Database Design, Security Design, Test Strategy, Deployment/DevOps Design, Observability Design, UI/UX Spec, ADRs, Requirements Traceability Matrix, Master Implementation Plan).
- Dashboard delivery (account, trading, AI, risk, learning, system views) with manual emergency STOP, per PRD §7.9.
- Maintenance of the Requirements Traceability Matrix linking PRD → BRD → SOW → FRD → design → code → test → validation.

---

## 5. Out-of-Scope Work

The following are explicitly excluded from this SOW unless a future change order is agreed:

- Trading markets outside India.
- Managing capital on behalf of any party other than the operator (would require re-scoping the BRD's business/regulatory basis — see BRD §11 item 8).
- Guaranteeing any specific return, win rate, or timeline to profitability.
- Building a fully unattended system with no human override capability.
- Replacing deterministic safety/risk logic with AI/LLM judgment, at any phase.
- Ultra-low-latency/high-frequency infrastructure, unless a later validated strategy specifically requires it and a change order is issued.
- Legal/regulatory certification — regulatory review is a **precondition dependency** for V5 (see §9), not a deliverable this SOW produces on its own; specialist legal/compliance input is out of scope for this SOW unless separately engaged.

---

## 6. Work Packages, Deliverables, and Acceptance Criteria

Each phase is a discrete work package. A phase is not to be started until the prior phase's exit criteria are met (BRD BR-8), and phases involving live capital (V5+) additionally require the preconditions in §9 to be satisfied.

### 6.1 V0 — Research Foundation
**Deliverables:** market data ingestion pipeline (batch/streaming as applicable), data validation logic, time-series/relational storage, basic exploratory analytics tooling, initial data-quality documentation.
**Acceptance Criteria:** data can be ingested, validated, and queried reliably; data-quality issues (gaps, stale data, bad ticks) are detectable; no live or simulated trading occurs in this phase.

### 6.2 V1 — Backtesting Trader
**Deliverables:** at least one baseline strategy, backtesting engine incorporating brokerage, fees, taxes, slippage, spread, and liquidity assumptions per PRD FR-25.
**Acceptance Criteria:** backtests are reproducible; look-ahead bias, survivorship bias, and unrealistic fills are demonstrably guarded against per PRD FR-26; results are documented with methodology, not just output numbers.

### 6.3 V2 — ML Trader
**Deliverables:** feature engineering pipeline, at least one trained predictive model, evaluation framework using the metrics in PRD §10 (not accuracy alone).
**Acceptance Criteria:** model evaluation includes out-of-sample testing; performance is reported across the full metrics set (expectancy, profit factor, drawdown, risk-adjusted return, etc.), with sample-size/statistical-significance caveats stated explicitly.

### 6.4 V3 — Multi-Agent Trader
**Deliverables:** market regime detection component, a validated (not assumed) initial agent roster per PRD §6.3, signal aggregation logic, deterministic risk engine, supervisor gating logic, decision architecture per PRD §7 flow (Market Data → ... → Execution Engine).
**Acceptance Criteria:** every simulated decision (BUY/SELL/HOLD/NO TRADE) is logged with rationale; the risk engine can be shown to block a disallowed action independent of agent/model output (proving BR-4's deterministic independence).

### 6.5 V4 — Paper Trader
**Deliverables:** real-time market data integration, simulated order execution against live market conditions, position/portfolio tracking in the simulated environment.
**Acceptance Criteria:** system runs continuously during market hours without manual intervention for a defined evaluation window (window length to be agreed with operator); paper performance is evaluated using the same metrics framework as V1–V2; zero real capital is at risk.

### 6.6 V5 — Autonomous Risk-Controlled Trader
**Deliverables:** broker authentication and order-management integration, all hard risk limits from PRD FR-11 implemented as deterministic controls, emergency kill switch, manual override capability, live deployment at ₹10,000 experimental capital.
**Acceptance Criteria:** all §9 preconditions met (see below); hard risk limits verified to trigger correctly under test conditions before any live order is placed; manual STOP verified to halt trading and, where appropriate, liquidate positions; full audit logging active from the first live trade.

### 6.7 V6 — Self-Learning Trader
**Deliverables:** post-trade evaluation pipeline (PRD FR-19), Research Brain environment isolated from live capital (PRD FR-21), candidate-model generation workflow.
**Acceptance Criteria:** every completed live/paper trade produces a structured evaluation record; Research Brain is demonstrably unable to place live orders or alter live risk parameters directly.

### 6.8 V7 — Adaptive Autonomous Trader
**Deliverables:** full model promotion pipeline (backtest → out-of-sample → walk-forward → stress → robustness → paper trading → performance comparison → risk review → production approval, per PRD FR-22), automated rollback mechanism, dynamic timeframe/strategy selection logic.
**Acceptance Criteria:** a candidate model can be demonstrated moving through every gate; a deliberately degraded model can be shown triggering an automatic rollback; no promotion occurs without passing every defined gate (BR-6).

### 6.9 V8 — Scalable Production System
**Deliverables:** production monitoring/observability, reliability hardening (failure handling, reconnection logic, duplicate-order protection under load), capital-scaling mechanics implementing the criteria from BRD BR-2, mature dashboard (PRD §7.9).
**Acceptance Criteria:** system meets whatever uptime/reliability NFR targets are defined in the NFRD; capital-scaling logic is demonstrated to require explicit predefined-criteria satisfaction and cannot self-trigger; dashboard provides full visibility per PRD FR-30 including a prominent emergency STOP.

---

## 7. Deliverable Format

All deliverables under this SOW are software artifacts (code, configuration, trained model artifacts, pipelines) plus accompanying documentation. Documentation deliverables (per §4) should be produced and version-controlled alongside the corresponding phase, not retrofitted after the fact, per Master Context §29 item 9 ("maintain consistency between documents").

---

## 8. Roles and Responsibilities

| Role | Responsibility |
|---|---|
| **System Owner / Operator** | Approves scope and phase transitions; sets/approves risk limits and capital-scaling criteria (per BRD BR-2); holds emergency override authority; reviews and signs off on model promotions where required (open item, BRD §11 item 6); provides or arranges broker/API access. |
| **Delivery Party** (developer/quant/AI-assisted build, TBD) | Designs and implements each phase's work package; writes and maintains tests; produces documentation deliverables; escalates ambiguities rather than silently resolving them (Master Context §29). |
| **Trading Brain (system component)** | Executes only validated, approved live decision logic within hard limits — not a human role, listed here for completeness of the operating model. |
| **Research Brain (system component)** | Runs experimentation isolated from live capital — not a human role, listed here for completeness of the operating model. |

If the Delivery Party is different from the Operator (e.g., a hired developer or an AI coding agent operating under instruction), a separate resourcing/engagement agreement may be needed; this SOW defines scope and acceptance, not employment or commercial terms.

---

## 9. Preconditions for Live-Capital Phases (V5 and beyond)

Per BRD BR-9 and PRD §11 Assumptions, the following must be satisfied **before V5 work begins**, and are treated as hard gates on this SOW, not optional recommendations:

1. Applicable Indian regulatory/exchange requirements for algorithmic trading have been reviewed and confirmed compliant.
2. A broker with suitable API access and required permissions has been selected and contracted (open item carried from PRD §6.3/§14).
3. All V0–V4 exit criteria have been met and are documented.
4. Hard risk limits (PRD FR-11) have been implemented and tested in a non-live environment.
5. The operator has explicitly approved moving to live capital deployment.

Work on V5 deliverables may proceed in a non-live/test-broker environment before these are fully satisfied, but **no live order may be placed** until all five preconditions are met.

---

## 10. Assumptions

- Timeline, budget, and staffing model are not yet fixed (BRD §11 item 1) and will be layered into this SOW once the operator resolves those open business questions.
- The operator retains final authority over phase-transition approval and capital-scaling decisions at all times.
- Phases may be re-scoped via change order if the HLD/TTD reveals a materially different technical approach is required — the phase *names and gates* in this SOW are expected to be stable, but the detailed technical content of each phase is intentionally left to the HLD/TTD/LLD.

---

## 11. Change Control

Any of the following require a documented change order against this SOW, cross-referenced in the Requirements Traceability Matrix:
- Adding/removing a phase or materially changing a phase's acceptance criteria.
- Moving to live capital before all §9 preconditions are met.
- Changing the initial capital figure (₹10,000) or the extreme-loss tolerance referenced in PRD §9.
- Extending scope to markets outside India, or to managing capital for parties other than the operator.
- Skipping a phase or collapsing multiple phases into a single delivery step (prohibited by BRD BR-8 absent an explicit, documented exception).

---

## 12. Open Items Requiring Operator Decision Before This SOW Can Be Finalized

Carried forward and consolidated from PRD §16 and BRD §11, specifically as they affect delivery planning:

1. Target timeline/cadence for V0→V8 — currently undefined.
2. Broker selection — currently undefined, blocks V5 planning detail.
3. Whether options/derivatives are near-term or future-only — affects V3/V5 scope detail.
4. Who the Delivery Party is (operator alone, hired developer, AI-assisted build, or combination) — affects §8 Roles.
5. Budget for infrastructure/data/compute, particularly for the Research Brain (V6+).
6. Required level of human sign-off per model promotion (V7) — affects acceptance criteria in §6.8.
7. Confirmation that regulatory review (precondition §9.1) is either underway or will be commissioned.

This SOW should be treated as **provisional** on phase content and acceptance criteria until items 1, 2, 4, and 7 above are resolved, since they materially affect sequencing and resourcing.

---

## 13. Traceability

| SOW Section | Source |
|---|---|
| §3 Objectives | BRD §3 Business Objectives |
| §4/§5 Scope | PRD §6 Scope, BRD §6 Business Rules |
| §6 Work Packages | PRD §13 Delivery Roadmap |
| §9 Preconditions | BRD BR-9, PRD §11 Assumptions |
| §11 Change Control | BRD BR-2, BR-6, BR-8 |
| §12 Open Items | PRD §16, BRD §11 |

---

## 14. Document Governance

This SOW must be kept consistent with the PRD and BRD at all times. Any approved change order must be reflected in the Requirements Traceability Matrix and, where it affects business rules or risk posture, back-propagated into the BRD.

**Next recommended step:** resolve the Open Items in §12 (particularly timeline, broker, and Delivery Party), then proceed to FRD drafting for V0–V1 in detail.