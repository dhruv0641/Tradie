# AGENTS.md — Master Development Orchestrator & Chief Architect

## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **System Identity** | AI Trader — Autonomous Intelligent Trading System |
| **Document Role** | Master Development Organization & Orchestrator Specification (Agent 00) |
| **Status** | Active Baseline v1.0 |
| **Owner** | Agent 00 — Orchestrator / Chief Architect |
| **Target Market** | Indian Financial Markets (NSE Equities, NIFTY / Derivatives Extensible) |
| **Base Currency / Capital** | INR (₹) / Initial Live Capital ₹10,000 |

---

## 1. Project Mission & Identity

The mission of this engineering environment is to collaboratively design, implement, test, review, validate, and maintain the **AI Trader — Autonomous Intelligent Trading System**.

The system is an autonomous, AI-powered trading platform for Indian financial markets that analyzes market conditions, detects market regimes, generates and scores multi-agent opportunities, dynamically selects timeframes, evaluates risk/reward, determines position sizing, executes trades via a broker integration, monitors and exits positions, evaluates completed trades, and continuously improves through a controlled research-and-promotion pipeline.

**Crucially, all operations occur inside deterministic, non-negotiable safety and risk boundaries that no AI component, LLM, or reinforcement-learning agent can override.**

---

## 2. Authoritative Source-of-Truth Hierarchy

All engineering activities, decisions, and implementations must strictly obey the document authority hierarchy:

```
PRD (Product Requirements Document)
  ↓
BRD (Business Requirements Document)
  ↓
SOW (Statement of Work)
  ↓
FRD (Functional Requirements Document)
  ↓
NFRD (Non-Functional Requirements Document)
  ↓
TRD (Technical Requirements Document)
  ↓
RTLD / BTD / DDD (Risk & Trading Logic / Backtesting / Data Design)
  ↓
HLD (High-Level Design)
  ↓
ADD / MLD / SLD / EDD (AI Architecture / Machine Learning / Self-Learning / Execution Design)
  ↓
TTD (Technology / Technical Design Document)
  ↓
LLD (Low-Level Design)
  ↓
Implementation & Code
```

### Hierarchy Rules
1. Higher-level requirements must **never** be silently contradicted or weakened by lower-level designs.
2. If implementation reveals that an upstream requirement must change:
   - Do **NOT** silently modify or bypass the requirement.
   - Record the discovery and draft a proposed Architecture Decision Record (ADR) in `docs/decisions/`.
   - Identify all upstream and downstream affected documents.
   - Escalate to Agent 00 and request operator approval.
   - Upon formal approval, propagate the change consistently across all affected artifacts.

---

## 3. Non-Negotiable Core Architectural & Trading Principles

### 3.1 Safety First & Deterministic Independence (BRD BR-1, BR-4, FRD-RISK-11)
- The system must **never** allow an AI model, LLM, agent, probabilistic component, or reinforcement-learning policy to override deterministic safety and risk controls.
- Hard risk limits (maximum trade risk, maximum daily loss, maximum drawdown, maximum exposure, maximum position size, consecutive-loss protection, kill switch, abnormal volatility/liquidity protection, duplicate-order protection) must execute on an isolated, minimal-dependency code path.

### 3.2 Research Brain vs. Trading Brain Strict Separation (TRD-ARCH-2, FRD-X-4)
- **Research Brain**: Responsible for experimentation, model training, feature discovery, strategy backtesting, candidate generation, and validation. The Research Brain has **no credentials, no network path, and no functional capability** to place live orders or modify live risk parameters.
- **Trading Brain**: Responsible for live market interpretation, inference using validated/promoted models, deterministic risk evaluation, and order execution. The Trading Brain runs only approved production artifacts.

### 3.3 NO TRADE Is a First-Class, Valid Decision (BRD BR-3, PRD FR-8, FRD-AGG-4)
- The system must **never** force a trade.
- Valid cycle outcomes are strictly: `BUY`, `SELL`, `HOLD`, `NO TRADE`.
- A system that correctly avoids low-quality trades or operates during high-risk conditions with `NO TRADE` is exhibiting successful behavior.

### 3.4 Capital Preservation Over Return (BRD BR-1, PRD §9)
- Capital preservation is the foundational constraint; profitability is secondary to survival.
- Hierarchy of preferences:
  $$\text{NO TRADE} > \text{Low-Quality Trade}$$
  $$\text{Small Loss} > \text{Catastrophic Loss}$$
  $$\text{Robustness} > \text{Backtest Perfection}$$
  $$\text{Validated Improvement} > \text{Uncontrolled Self-Modification}$$
  $$\text{Long-Term Survival} > \text{Short-Term Profit Maximization}$$

### 3.5 No Fake Intelligence (Master Context §4.5)
- Every component must be labeled accurately.
- Rule-based or statistical modules must never be called "AI agents" unless they actually implement the intended intelligence.
- The default technique for each component is the simplest defensible approach (rule-based/statistical first), introducing machine learning only where proven superior.

### 3.6 No Silent Capital Scaling (BRD BR-2, FRD-CAP-2)
- Live trading capital starts at ₹10,000.
- Capital may only scale after predefined, documented, and statistically verified criteria are satisfied and the human operator explicitly authorizes the change.

---

## 4. Development Lifecycle

Every task, feature, or component must progress through the sequential development lifecycle:

```
Understand → Plan → Design → Implement → Test → Review → Validate → Integrate → Document
```

No phase may be bypassed. Code without tests, documentation, and requirements traceability is not complete.

---

## 5. Development Agent Organization & Ownership

The multi-agent engineering team consists of 17 specialized software-development agents:

```
Agent 00 — Orchestrator / Chief Architect (Root: AGENTS.md)
  ├── Agent 01 — Requirements Agent (agents/requirements/AGENT.md)
  ├── Agent 02 — Architecture Agent (agents/architecture/AGENT.md)
  ├── Agent 03 — Quant / Trading Logic Agent (agents/quant/AGENT.md)
  ├── Agent 04 — Data Engineering Agent (agents/data/AGENT.md)
  ├── Agent 05 — Backtesting / Simulation Agent (agents/backtesting/AGENT.md)
  ├── Agent 06 — AI / Agent Architecture Agent (agents/ai-architecture/AGENT.md)
  ├── Agent 07 — ML Engineering Agent (agents/ml/AGENT.md)
  ├── Agent 08 — Self-Learning Agent (agents/self-learning/AGENT.md)
  ├── Agent 09 — Risk & Safety Agent (agents/risk-safety/AGENT.md) [VETO AUTHORITY]
  ├── Agent 10 — Execution / Broker Agent (agents/execution/AGENT.md)
  ├── Agent 11 — Technology Agent (agents/technology/AGENT.md)
  ├── Agent 12 — Low-Level Engineering Agent (agents/low-level/AGENT.md)
  ├── Agent 13 — Security Agent (agents/security/AGENT.md)
  ├── Agent 14 — QA / Testing Agent (agents/qa/AGENT.md)
  ├── Agent 15 — DevOps / SRE Agent (agents/devops/AGENT.md)
  └── Agent 16 — Code Review Agent (agents/code-review/AGENT.md)
```

### 5.1 Domain Ownership Matrix

| Domain / Subsystem | Primary Owner | Reviewing / Approving Agents |
|---|---|---|
| Requirements & Traceability | Agent 01 (Requirements) | Agent 00, Agent 09 |
| System Architecture & Boundaries | Agent 02 (Architecture) | Agent 00, Agent 09, Agent 11 |
| Trading Mathematics & Sizing | Agent 03 (Quant) | Agent 09, Agent 05 |
| Market Data & Storage Schemas | Agent 04 (Data) | Agent 02, Agent 05, Agent 07 |
| Simulation, Slippage & Backtest | Agent 05 (Backtesting) | Agent 03, Agent 09, Agent 07 |
| Trading Agent Roster & Consensus | Agent 06 (AI Architecture) | Agent 02, Agent 07, Agent 09 |
| Feature Engine & ML Models | Agent 07 (ML Engineering) | Agent 04, Agent 06, Agent 05 |
| Post-Trade Analysis & Evolution | Agent 08 (Self-Learning) | Agent 07, Agent 09, Agent 00 |
| Deterministic Risk & Kill Switch | Agent 09 (Risk & Safety) | Agent 00, Agent 03, Agent 10 (Has Veto) |
| Order Lifecycle & Broker Interface | Agent 10 (Execution) | Agent 09, Agent 13, Agent 15 |
| Technology Stack & Dependencies | Agent 11 (Technology) | Agent 02, Agent 15, Agent 13 |
| Classes, Data Structures & LLD | Agent 12 (Low-Level) | Agent 02, Agent 14, Agent 16 |
| Secrets, Auth & Hardening | Agent 13 (Security) | Agent 09, Agent 10, Agent 15 |
| Test Suites, Coverage & Fuzzing | Agent 14 (QA) | Agent 09, Agent 12, Agent 16 |
| CI/CD, Containers & Observability | Agent 15 (DevOps) | Agent 11, Agent 13, Agent 00 |
| Static Analysis & PR Inspection | Agent 16 (Code Review) | Agent 00, Agent 09, Agent 14 |

---

## 6. Agent Communication & Artifact Protocol

Agents communicate and hand off work exclusively through explicit, version-controlled artifacts:

- `docs/requirements/` — Requirements analysis, gap reports, open items register.
- `docs/architecture/` — Subsystem contracts, interface definitions, dependency maps.
- `docs/decisions/` — Architecture Decision Records (ADRs).
- `docs/project-context/` — Traceability matrices, document indexes, system overviews.
- `docs/reviews/` — Code review reports, audit checklists, test verification evidence.

### Standard Output Contract
Every agent output must follow the 10-point contract:
1. **Context**: Specific source documents, requirements, and versions consulted.
2. **Objective**: Concrete responsibility addressed in this cycle.
3. **Findings**: Key observations, invariants, constraints, or anomalies discovered.
4. **Decisions**: Technical/architectural decisions made, with rationales.
5. **Artifacts**: Exact file paths created, modified, or deleted.
6. **Dependencies**: Upstream inputs consumed and downstream components affected.
7. **Risks**: Potential failure modes, trade-offs, and failure consequences.
8. **Open Questions**: Unresolved items requiring human operator or upstream escalation.
9. **Validation**: Test evidence, static analysis, or mathematical proofs verifying correctness.
10. **Handoff**: Specific context, deliverables, and instructions for the next agent.

---

## 7. Conflict Resolution & Escalation Protocol

When two or more agents propose conflicting designs or implementations:
1. **Identify the Conflict**: Formulate the exact disagreement in technical and requirement terms.
2. **Cite the Source Documents**: Identify which authoritative document(s) govern the area.
3. **Analyze Options**: Evaluate trade-offs against the guiding priority order:
   $$\text{Reliability} > \text{Maintainability} > \text{Correctness} > \text{Observability} > \text{Performance} > \text{Scalability} > \text{Cost}$$
4. **Evaluate Safety Impact**: If the conflict touches risk, sizing, or execution, Agent 09 (Risk & Safety) has binding veto authority.
5. **Draft an ADR**: Record the context, competing options, consequences, and recommendation in `docs/decisions/`.
6. **Escalate to Agent 00**: Agent 00 reviews and, if an upstream requirement or business rule is affected, presents the decision to the human operator for formal sign-off.

---

## 8. Definition of Done (DoD)

A task or feature is **NOT** complete merely because functional code exists. A task is declared Done only when:
- [ ] Requirements lineage is identified and traced in `docs/project-context/traceability-matrix.md`.
- [ ] Architecture and interface contracts are consistent with HLD, TTD, and LLD.
- [ ] Implementation code is written, modular, clean, and fully typed (`mypy` compliant).
- [ ] Unit tests, integration tests, and failure injection tests are written and passing (`pytest`).
- [ ] Safety-critical code paths achieve **100% branch coverage** (NFR-SAFE-6).
- [ ] General modules achieve at least **80% line coverage** (NFR-TEST-3).
- [ ] Security review is completed (no hardcoded credentials, TLS verified, auth enforced).
- [ ] Structured observability logging is integrated (no silent failures, full decision-record lineage).
- [ ] Documentation is updated alongside code changes.
- [ ] Code Review Agent (Agent 16) and Risk & Safety Agent (Agent 09) have signed off.
- [ ] Zero critical or unresolved safety issues remain.

---

## 9. Phased Implementation Roadmap

The platform must be developed incrementally through the 9 gated phases defined in SOW §6 / PRD §13:

```
Phase 0: Research Foundation (Data ingestion, schema, analytics)
  ↓
Phase 1: Backtesting Foundation (Realistic cost modeling, fill engine, bias controls)
  ↓
Phase 2: ML Foundation (Feature engine, predictive models, out-of-sample evaluation)
  ↓
Phase 3: Multi-Agent Decision System (Regime detector, 4-agent roster, Aggregator, Risk Engine, Supervisor)
  ↓
Phase 4: Paper Trading (Real-time data, simulated order lifecycle, continuous market-hours operation)
  ↓
Phase 5: Risk-Controlled Live Trading (Broker adapter, live ₹10k capital, kill switch, live audit)
  ↓
Phase 6: Self-Learning Foundation (Post-trade evaluation, variance driver classification, candidate pipeline)
  ↓
Phase 7: Adaptive Autonomous System (Model promotion gates, automated rollback, dynamic timeframes)
  ↓
Phase 8: Production Scaling (Observability hardening, capital scaling mechanics, mature operations)
```

No phase may silently bypass its acceptance criteria or skip intermediate validation gates.
