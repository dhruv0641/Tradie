# ADR-0000: Architecture Decision Record (ADR) Process & Authority Governance

## Status
Accepted

## Context & Problem Statement
The AI Trader engineering environment involves 17 specialized development agents operating across a 16-document authority hierarchy. A higher-level document must never be silently contradicted or weakened by a lower-level design or implementation choice. We need a formalized, deterministic process for recording decisions, resolving trade-offs, managing open items, and escalating upstream requirement changes to the System Owner/Operator.

## Document Authority Hierarchy
Engineering activities, designs, and code changes must strictly adhere to the document authority order:
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
ADD / MLD / SLD / EDD (Detailed AI, ML, Self-Learning, Execution Designs)
  ↓
TTD (Technology / Technical Design Document)
  ↓
LLD (Low-Level Design)
  ↓
Implementation & Code
```

## Decision: ADR Governance Workflow
When an engineering, quantitative, or implementation discovery indicates that an upstream requirement or design must change:

1. **No Silent Mutation**: Do NOT modify upstream requirements or bypass them in code.
2. **Draft Proposed ADR**: Draft an ADR under `docs/decisions/` using `docs/decisions/TEMPLATE.md`.
3. **Trace Impact**: Identify every upstream and downstream document affected using the Traceability section of each authoritative document and `docs/requirements/TRACEABILITY_MATRIX.md`.
4. **Evaluate Against Priority Order**:
   $$\text{Reliability} > \text{Maintainability} > \text{Correctness} > \text{Observability} > \text{Performance} > \text{Scalability} > \text{Cost}$$
5. **Safety Veto Check**: Agent 09 (Risk & Safety) inspects the proposal. If safety or deterministic limits are touched, Agent 09 has absolute veto authority.
6. **Operator Sign-off**: Escalate to the System Owner/Operator (single accountable decision-maker). No change touching capital, risk limits, or BRD rules (BR-1 to BR-9) may proceed without explicit operator sign-off.
7. **Downstream Document Propagation**: Upon approval, update all affected documents across the entire chain—never update just the code.

## Consequences
### Positive
- Eliminates architectural drift and silent assumption propagation.
- Guarantees complete auditability and alignment with operator intent.
- Preserves the integrity of the document hierarchy.

### Negative / Risks
- Adds deliberate documentation overhead before code changes are merged (mitigated by preventing catastrophic real-money trading errors).
