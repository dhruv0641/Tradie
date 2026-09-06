---
name: qa-test-enforcer
description: >-
  Use this skill to design, implement, and run automated tests.
  Enforces Test-Driven Development (TDD), 100% safety branch coverage,
  failure injection testing, and automated coverage validation.
---

# QA Test Enforcer Runbook (Agent 14)

## Mission
Ensure system reliability, edge-case resilience, and 100% test coverage compliance across all modules. No code ships without comprehensive tests.

---

## 1. Test Creation Workflow (TDD)

1. **Before Writing Code**:
   - Write unit tests covering normal paths, boundary conditions, and invalid inputs.
   - For financial functions: Write tests verifying `Decimal` precision, zero division handling, and extreme values.
2. **For Safety-Critical Code** (`src/risk_engine/`, `src/supervisor/`, `src/kill_switch/`):
   - Map out the complete decision tree.
   - Write test cases for **every single branch condition**.
   - Verify that **100% branch coverage** is achieved (`--cov-branch --cov-fail-under=100`).
3. **For Data Ingestion & Features**:
   - Write tests verifying point-in-time calculation guarantees (zero future data leakage).
   - Write tests for data quarantine on bad ticks ($High < Low$, negative volume, extreme jumps).
4. **For Execution & Broker Adapters**:
   - Write idempotency tests verifying duplicate order submissions return existing order states without placing second orders.
   - Write reconnection tests simulating broker socket drops during active states.

---

## 2. Test Execution Commands

```powershell
# 1. Execute fast unit tests
pytest -v tests/unit/

# 2. Execute database & storage integration tests
pytest -v tests/integration/

# 3. Verify safety-critical path with 100% branch coverage enforcement
pytest --cov=src/risk_engine --cov=src/supervisor --cov=src/kill_switch --cov-branch --cov-report=term-missing --cov-fail-under=100 tests/safety/

# 4. Execute global test suite with 80% line coverage enforcement
pytest --cov=src --cov-branch --cov-report=term-missing --cov-report=xml --cov-fail-under=80 tests/
```

---

## 3. QA Sign-Off Criteria

QA sign-off is granted only when:
- All unit, integration, and safety tests pass cleanly (zero failures, zero errors).
- Safety-critical code paths achieve **100% branch coverage**.
- General modules achieve $\ge 80\%$ line coverage.
- Failure injection and chaos scenarios demonstrate graceful degradation.
