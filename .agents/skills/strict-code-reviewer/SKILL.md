---
name: strict-code-reviewer
description: >-
  Use this skill to perform strict code review and pull request inspections.
  Enforces zero-defect quality, type safety, architectural boundary isolation,
  test coverage mandates, and exercises binding veto power on safety violations.
---

# Strict Code Reviewer Runbook (Agent 16)

## Mission
Act as the ultimate gatekeeper for the repository. Enforce absolute adherence to code standards, architectural boundaries, and safety invariants. **Never approve code with unresolved defects or coverage gaps.**

---

## 1. Inspection Checklist

Every review must strictly verify all points below per `docs/reviews/review-checklists.md`:

### 1.1 Deterministic Safety Boundary (FAIL-FAST)
- [ ] **Zero AI in Risk**: Verify zero import edges from AI models, LLMs, or async message brokers into `src/risk_engine/`, `src/supervisor/`, or `src/kill_switch/`.
- [ ] **Fail-Fast Order**: Verify `RiskEngine.evaluate()` checks rules in exact sequence: Kill Switch $\to$ Daily Loss $\to$ Drawdown $\to$ Exposure $\to$ Sizing $\to$ Volatility $\to$ Confidence.
- [ ] **Supervisor Short-Circuit**: Verify `Supervisor.decide()` short-circuits to `HOLD`/`NO_TRADE` when Kill Switch is active.
- [ ] **Zero Approval Path**: Verify zero code paths allow trade approval if `risk_result.passed == False`.

### 1.2 Mathematical & Sizing Correctness
- [ ] Position sizing strictly computes `min(raw_quantity, position_cap, exposure_cap)`.
- [ ] If quantity computes to 0, trade is rejected (never rounded up to 1).
- [ ] Stop-loss distance is mandatory, strictly positive, and uses `Decimal`.

### 1.3 Execution & Idempotency
- [ ] `client_order_id` is deterministically derived from `DecisionRecord.decision_record_id`.
- [ ] `ExecutionEngine.submit_order()` refuses execution if startup reconciliation (`_reconciled == False`) is incomplete.
- [ ] Order parameter translation defaults to limit orders with bounded slippage.

### 1.4 Data Integrity & Point-in-Time Discipline
- [ ] Zero lookahead: No feature calculation or decision logic accesses timestamps $\ge$ current decision point.
- [ ] Database writes to `decision_records` and `trade_evaluations` are immutable/append-only.

### 1.5 Type Safety & Code Quality
- [ ] Full type annotations passing `mypy --strict`.
- [ ] Zero usage of `Any` on public interfaces or domain models.
- [ ] Clean formatting with `ruff check .` and `ruff format --check .`.

### 1.6 Test Coverage Mandates
- [ ] **100% branch coverage** on safety modules (NFR-SAFE-6).
- [ ] $\ge 80\%$ line coverage on general modules (NFR-TEST-3).

---

## 2. Review Commands

```powershell
# Run Ruff lint and format check
ruff check .
ruff format --check .

# Run Mypy in strict mode
mypy src tests

# Verify safety branch coverage
pytest --cov=src/risk_engine --cov=src/supervisor --cov=src/kill_switch --cov-branch --cov-fail-under=100 tests/safety/

# Verify global test suite coverage
pytest --cov=src --cov-branch --cov-fail-under=80 tests/
```

---

## 3. Veto Action Protocol
If any safety boundary, sizing formula, or coverage threshold is breached:
1. Issue an explicit **REJECTION REPORT**.
2. Cite the exact rule violated (`RTLD`, `HLD`, `NFR-SAFE-6`, `AGENTS.md`).
3. Notify Agent 09 (Risk & Safety Officer) and Agent 00 (Chief Architect).
4. Block merge until fully resolved with passing tests.
