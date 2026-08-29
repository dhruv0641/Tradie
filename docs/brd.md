# Business Requirements Document (BRD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Business Requirements Document (BRD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1 and PRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Document** | AI Trader PRD v0.1 |

---

## 1. Purpose of This Document

The PRD defines *what the product must do*. This BRD defines *why the business is undertaking this project*: the business case, the value being sought, who is accountable for what, what business rules and constraints bind every downstream decision, and how business (not just technical) success will be judged.

This BRD sits above the FRD/NFRD/HLD in the documentation hierarchy and below the PRD. Where the PRD describes product scope and functional requirements, this BRD describes the business justification, the business rules those functions must obey, and the business-level acceptance criteria for the program as a whole.

Consistent with the project's engineering principles, this BRD does not resolve open business decisions on the operator's behalf — it isolates them explicitly in §11.

---

## 2. Business Background

The operator currently has no systematic, always-on method to trade Indian markets (NSE equities and NIFTY-related instruments) that is free of emotional bias, capable of processing many information sources simultaneously, and disciplined about risk under stress. Manual or simple rule-based approaches are limited in monitoring capacity, consistency, and self-correction.

The business opportunity is to build an internal, single-operator capability — not a customer-facing product — that can trade with discipline the operator wants to enforce on themselves systematically: preferring no action over a poor one, protecting capital ahead of chasing return, and only being trusted with more capital once it has earned that trust through evidence.

---

## 3. Business Objectives

| # | Business Objective | Related PRD Objective(s) |
|---|---|---|
| BO-1 | Preserve the operator's initial capital (₹10,000) as the first priority, ahead of generating returns. | PRD §4.2 items 6, 11; §9 Risk Philosophy |
| BO-2 | Establish a repeatable, evidence-based process for earning the right to manage more capital, rather than scaling capital based on short-term luck. | PRD §4.2 item 14; §12 Constraints |
| BO-3 | Reduce reliance on manual, emotionally-influenced trading decisions by building a disciplined, auditable decision process. | PRD §3 Background |
| BO-4 | Build a system whose decisions and risk posture are fully explainable and auditable at any time, to support trust and oversight by the operator. | PRD §4.2 item 12 |
| BO-5 | Avoid catastrophic, irreversible, or unbounded financial loss under any operating condition, including AI or infrastructure failure. | PRD §9; §22 (Master Context) |
| BO-6 | Build the capability incrementally so that business risk (capital at stake, operational complexity) grows only in step with demonstrated system maturity. | PRD §13 Roadmap |
| BO-7 | Retain the operator's ability to intervene and stop the system at any time, without dependency on the AI's cooperation or availability. | PRD §7.9, FR-31 |

These objectives are not equally weighted: **capital preservation (BO-1, BO-5) takes precedence over return generation** whenever they conflict. This ordering is a business rule, not a technical preference, and must be enforced at every design layer.

---

## 4. Business Justification / Value Proposition

| Value Driver | Description |
|---|---|
| **Discipline at scale** | A well-constrained system can apply the same risk rules every single time, without fatigue, panic, or overconfidence — something difficult to guarantee from manual trading. |
| **Continuous monitoring** | The system can observe multiple markets, timeframes, and information sources simultaneously and continuously during market hours, which is impractical manually. |
| **Compounding of learning** | A structured self-improvement pipeline (research → validation → promotion) allows the system's edge, if any, to improve over time in a controlled, evidenced way rather than through ad hoc tweaks. |
| **Optionality with bounded downside** | Starting at ₹10,000 with an extreme-case tolerance of ~₹1,000 caps the business's downside exposure while the concept is validated, before any larger capital commitment is considered. |
| **Auditability as a governance asset** | Full explainability of every decision creates a record the operator can use to evaluate the system objectively, rather than relying on anecdote or memory. |

There is no external revenue model in the current scope — the value is realized directly as trading performance and as a decision-support/governance capability for the operator's own capital.

---

## 5. Business Stakeholders and Accountability

| Stakeholder | Business Role | Accountable For |
|---|---|---|
| **System Owner / Operator** | Capital owner, final decision authority | Setting risk tolerance and capital-scaling criteria; approving model promotions where human sign-off is required (open question, §11); exercising emergency override; deciding to halt, pause, or wind down the project. |
| **Trading Brain (system, business role)** | Front-line decision execution | Operating strictly within approved risk limits; never exceeding delegated authority. |
| **Research Brain (system, business role)** | Innovation/experimentation function | Generating and validating candidate improvements without creating any business risk to live capital. |
| **Future collaborators (if any)** | Delivery/extension | Any developer or quant brought in later inherits the same non-negotiable risk and governance rules defined in this BRD; this BRD's rules bind future contributors, not just the current build. |

There is no external customer, compliance department, or third-party business stakeholder in the current scope. If the system is ever extended to manage capital on behalf of others, this BRD must be revisited, as that would introduce regulatory and fiduciary obligations not currently in scope.

---

## 6. Business Rules

These are the non-negotiable rules the business imposes on the product, independent of implementation. Every FRD/NFRD/HLD requirement must be traceable to, and consistent with, these rules.

1. **BR-1 — Capital preservation precedence.** No feature, optimization, or performance target may be implemented in a way that increases risk to capital beyond approved limits, even if it would likely increase returns.
2. **BR-2 — No silent capital scaling.** Capital allocated to live trading may only increase when predefined, documented, and previously agreed criteria are met (sample size, consistency, drawdown, risk-adjusted return, robustness, live/paper performance, model stability, execution quality, operational reliability). The system itself may never decide to increase its own capital.
3. **BR-3 — NO TRADE is a legitimate business outcome.** The system must never be tuned, incentivized, or evaluated in a way that pressures it to trade when conditions do not warrant it. A day, week, or month of no trades is an acceptable business outcome.
4. **BR-4 — Deterministic safety cannot be delegated to AI judgment.** Hard risk limits, kill-switch logic, and emergency shutdown must be implemented as deterministic business rules enforced independently of any AI/LLM/probabilistic component, so that a model error, hallucination, or unexpected behavior cannot itself remove a safety control.
5. **BR-5 — Human override is always available.** The operator must always retain a manual, immediate way to halt trading and/or liquidate positions, regardless of the AI system's internal state.
6. **BR-6 — No unvalidated model touches live capital.** A model or strategy may only be connected to live capital after passing every stage of the model promotion pipeline defined in the PRD (§7.6) and, where required, explicit human sign-off (open question, §11).
7. **BR-7 — Full auditability.** Every trading decision (including NO TRADE) must be reconstructable after the fact: what was observed, what was decided, why, and by which model version. Explanations must reflect actual system reasoning, not be fabricated after the fact.
8. **BR-8 — Incremental risk exposure.** Business risk (capital committed, operational complexity, autonomy granted) must increase only in step with the incremental delivery roadmap (V0–V8); no phase may be skipped to accelerate live trading.
9. **BR-9 — Regulatory compliance is a precondition, not an afterthought.** No live trading (V5+) may begin until applicable Indian regulatory/exchange requirements for algorithmic trading have been reviewed and satisfied.

---

## 7. Business Process Overview (Current vs. Future State)

### 7.1 Current State (Manual / Ad Hoc)
- The operator (or no one) monitors markets manually or via simple tools.
- Decisions to trade are made discretionarily, without systematic multi-source analysis or consistent risk discipline.
- Post-trade review, if it happens, is informal and not systematically fed back into future decisions.

### 7.2 Future State (Target Business Process)
1. The system continuously observes market conditions during applicable hours.
2. It proposes a decision (BUY/SELL/HOLD/NO TRADE) with full supporting rationale.
3. A deterministic risk/supervisor gate approves or blocks the proposed action before anything reaches the broker.
4. Approved actions are executed, monitored, and eventually closed out.
5. Every completed trade is evaluated and logged for learning purposes.
6. Learnings feed a separate, offline research and validation pipeline.
7. Only validated improvements are promoted to live decision-making, under the model promotion business rule (BR-6).
8. The operator reviews dashboards and retains override authority throughout.
9. Capital scaling decisions are made periodically against the predefined criteria (BR-2), not automatically by the system.

---

## 8. Business Constraints

| Constraint | Description |
|---|---|
| **Capital** | ₹10,000 initial experimental capital; not to be increased without meeting documented criteria (BR-2). |
| **Regulatory** | Subject to applicable SEBI/exchange rules on algorithmic trading in India; not yet reviewed in detail (open item). |
| **Operational** | Single-operator system; no team of traders or compliance staff assumed at this stage. |
| **Time/Delivery** | Must be delivered incrementally (V0–V8); no fixed deadline has been set by the business at this stage (open question, §11). |
| **Vendor/Broker** | Dependent on selection of a broker with suitable API access and permissions (open item carried from PRD §6.3/§14). |

---

## 9. Business Risks

| Risk | Business Impact | Mitigation (Business-Level) |
|---|---|---|
| System causes real financial loss beyond the operator's stated tolerance | Direct financial harm; loss of trust in the system | Hard risk limits (BR-1, BR-4), capped initial capital, staged rollout (BR-8) |
| Regulatory non-compliance in algorithmic trading | Legal/regulatory exposure, potential trading suspension | Regulatory review required before V5 (BR-9) |
| Operator over-trusts the system due to a lucky early streak | Premature capital scaling, outsized future losses | BR-2: capital scaling only via predefined, documented criteria |
| System becomes a "black box" the operator can no longer interpret | Loss of governance/oversight, harder to catch failure early | BR-7: mandatory full auditability |
| Project scope creep (e.g., building all agents/instruments at once) | Delayed delivery, wasted effort, harder validation | BR-8: incremental exposure tied to the V0–V8 roadmap |
| Broker/API or data vendor unavailability or cost overrun | Delivery delay, degraded live performance | To be assessed once broker/vendor selection (open item) is resolved |

---

## 10. Business Success Criteria

The project is judged successful at the business level if, over time, it demonstrates:

1. **No breach of hard capital-preservation rules** (BR-1, BR-4) at any point, including during model or infrastructure failures.
2. **Zero instances of capital scaling outside the predefined criteria** (BR-2).
3. **Zero instances of an unvalidated model reaching live capital** (BR-6).
4. **100% reconstructability** of any past decision on request (BR-7).
5. **Demonstrated, statistically credible, risk-adjusted performance** sufficient to justify — per the operator's own predefined criteria — a decision to allocate more capital (not a guaranteed profit outcome).
6. **Operator confidence** that they can halt or override the system at any time without needing developer intervention (BR-5).
7. **Delivery discipline**: each version (V0–V8) reaches its own exit criteria before the next phase begins, with no phase skipped (BR-8).

Business success is explicitly **not** defined as hitting a specific win rate or daily P&L figure — this mirrors the Non-Goals already established in the PRD (§4.3) and Risk Philosophy (§9).

---

## 11. Open Business Questions (Require Operator Decision)

These carry forward from the PRD (§16) with business framing, plus additional items specific to this BRD:

1. What is the acceptable timeline/cadence for progressing through V0–V8? Is there any business urgency, or is this open-ended?
2. Which broker(s) are commercially available and acceptable to the operator, including cost/fee structure?
3. Is derivatives/options trading a near-term business priority, or purely a future extensibility item?
4. What is the desired profit-withdrawal policy (periodic withdrawal vs. full reinvestment), and does that policy itself need predefined rules (per BR-2's spirit)?
5. Is there a budget the operator is willing to commit to infrastructure/data/compute for the Research Brain, separate from trading capital?
6. What level of human sign-off is required before each model promotion — fully automated within gates, or explicit operator approval per promotion?
7. Has the operator reviewed, or does the operator need support reviewing, applicable Indian regulatory requirements for algorithmic trading before any live-capital phase (V5+)?
8. Is this project intended to remain strictly single-operator/personal-capital, or could it later extend to managing capital for others (which would materially change the business/regulatory/fiduciary picture and require this BRD to be revisited)?

---

## 12. Traceability to PRD

| BRD Section | Corresponding PRD Section |
|---|---|
| Business Objectives (§3) | PRD §4 Goals and Objectives |
| Business Justification (§4) | PRD §2 Product Vision, §3 Background |
| Business Rules (§6) | PRD §9 Risk Philosophy, §12 Constraints |
| Business Process (§7) | PRD §7 Functional Requirements (summary level) |
| Business Constraints (§8) | PRD §12 Constraints, §6.3 Open Scope Questions |
| Business Risks (§9) | PRD §15 Risks to the Program |
| Business Success Criteria (§10) | PRD §10 Success Metrics |
| Open Business Questions (§11) | PRD §16 Open Questions |

Any change to a Business Rule (§6) in this BRD must be reflected back into the PRD's Risk Philosophy and Constraints sections, and cascaded into the FRD/NFRD, to keep the Requirements Traceability Matrix consistent.

---

## 13. Document Governance

This BRD, like the PRD, is a living document. It should be reviewed whenever:
- Any Business Rule (§6) is proposed to change.
- Capital scaling criteria are defined or modified.
- Regulatory findings materially affect scope (e.g., restrictions on options, shorting, or algo trading generally).
- The operator's risk tolerance changes.

**Next recommended step:** resolve the Open Business Questions (§11) alongside the PRD's Open Questions (§16), then proceed to SOW and FRD drafting.