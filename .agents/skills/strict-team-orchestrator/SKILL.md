---
name: strict-team-orchestrator
description: >-
  Use this skill to orchestrate software engineering workflows across the 17-specialist team.
  Enforces task decomposition, agent assignment, sprint execution, and strict Definition of Done verification.
---

# Strict Team Orchestrator Runbook (Agent 00)

## Mission
Orchestrate engineering execution across the multi-agent software team with zero compromises on quality, safety boundaries, or requirements lineage.

---

## 1. Lifecycle Workflow

When receiving a user feature request, architectural change, or sprint execution command:

```
Step 1: Ingest & Trace Requirements (Agent 01)
  ↓
Step 2: Architecture & Boundary Review (Agent 02, Agent 09)
  ↓
Step 3: Task Decomposition & Sprint Spec (Agent 00)
  ↓
Step 4: Implementation Assignment (Agents 03–13)
  ↓
Step 5: Quality Assurance & Coverage Mandate (Agent 14)
  ↓
Step 6: Security & Secrets Audit (Agent 13)
  ↓
Step 7: Code Review & Final Sign-Off (Agent 16, Agent 09)
```

---

## 2. Execution Runbook

### Phase 1: Requirement & Hierarchy Verification
1. Check parent document hierarchy:
   $$\text{PRD} \to \text{BRD} \to \text{SOW} \to \text{FRD} \to \text{TRD} \to \text{HLD} \to \text{LLD}$$
2. If the request modifies an existing architectural boundary or risk parameter:
   - Do **NOT** proceed silently.
   - Draft an Architecture Decision Record (ADR) in `docs/decisions/`.
   - Escalate to the human operator for formal sign-off.

### Phase 2: Sprint & Task Mapping
1. Map the request to its corresponding Epic and Sprint in [docs/sprints/README.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/sprints/README.md).
2. Load the sprint specification:
   - Verify assigned specialist agents.
   - Confirm prerequisites and inputs are fulfilled.

### Phase 3: Definition of Done Enforcement
Before declaring any task or sprint complete, verify the 9-point DoD checklist:
- [ ] Requirements lineage traced to source docs.
- [ ] Code strictly typed (`mypy --strict`) with zero `Any`.
- [ ] Formatted and clean (`ruff check .`, `ruff format --check .`).
- [ ] Pytest passing with $\ge 80\%$ line coverage globally.
- [ ] **100% branch coverage** on safety modules (Modules 6, 7, 11).
- [ ] Zero secrets detected (`gitleaks`, `detect-secrets`).
- [ ] Structured logging integrated with correlation IDs.
- [ ] Code Review Agent (Agent 16) approved.
- [ ] Risk & Safety Agent (Agent 09) approved.
