# Quality, Linting & Testing Standards

| | |
|---|---|
| **Document Role** | Testing Pyramid, Branch Coverage & Quality Mandates |
| **Enforcement Agents** | Agent 14 (QA & Testing Lead), Agent 16 (Code Reviewer) |
| **Status** | Active Baseline v1.0 |

---

## 1. Static Type Checking & Code Quality

### 1.1 Strict Mypy Mandates
All Python source code under `src/` and `tests/` must compile with `mypy --strict`. The following flags are enforced:
- `disallow_untyped_defs = true`: Every function must declare parameter and return types.
- `disallow_incomplete_defs = true`: Partial type annotations are forbidden.
- `check_untyped_defs = true`: Functions without decorators are still strictly checked.
- `no_implicit_optional = true`: `None` must be explicitly declared as `Optional[T]` or `T | None`.
- `warn_return_any = true`: Functions returning `Any` are rejected.
- `strict_equality = true`: Equality checks between incompatible types trigger errors.

### 1.2 Zero-Any Invariant
The usage of `Any` on public domain models, execution interfaces, and risk functions is **strictly prohibited**. Developers must use:
- Generic types `TypeVar` / `ParamSpec`
- Structural subtyping via `typing.Protocol`
- Discriminated union types via `typing.Literal`

---

## 2. The Testing Pyramid

Testing is divided into four distinct test categories:

```
          ▲
         / \     Stage 4: Failure Injection & Chaos Tests
        /   \    Stage 3: Safety-Critical Boundary Isolation (100% Branch)
       /     \   Stage 2: Integration Tests (TimescaleDB, Parquet, Mock Feeds)
      /_______\  Stage 1: Unit Tests (Fast, In-Memory, Deterministic)
```

### 2.1 Stage 1: Unit Tests (`tests/unit/`)
- Pure, fast, isolated in-memory tests.
- Execution time: $<5$ seconds for entire unit suite.
- Zero network calls; zero external service dependencies.
- Decimal arithmetic verification and boundary edge cases.

### 2.2 Stage 2: Integration Tests (`tests/integration/`)
- Multi-component interaction with real TimescaleDB (via testcontainers).
- Parquet read/write roundtrip and point-in-time range query tests.
- Feed handler tick aggregation and candle assembly validation.

### 2.3 Stage 3: Safety-Critical Path Tests (`tests/safety/`)
- Governed by **NFR-SAFE-6**: Mandatory **100% branch coverage** on:
  - `src/risk_engine/` (Module 6)
  - `src/supervisor/` (Module 7)
  - `src/kill_switch/` (Module 11)
- Every single branch, edge case, and error condition must be exercised:
  - Kill switch active $\to$ immediate rejection.
  - Daily loss limit breach $\to$ halt and reject.
  - Drawdown limit breach $\to$ halt and reject.
  - Sizing quantity calculation bounds and zero quantity rejection.
  - Consecutive loss circuit breaker cooldown trigger.
  - Quarantined or stale data suppression.

### 2.4 Stage 4: Failure Injection & Bias Tests
- Simulated broker socket disconnects during active order submission.
- Duplicate order submission attacks (idempotency verification).
- Known-answer backtesting suites: Verification of zero lookahead bias ($t \ge T$ lookups raise exceptions).

---

## 3. Test Coverage Thresholds

| Module / Layer | Line Coverage Mandate | Branch Coverage Mandate | Failure Policy |
|---|---|---|---|
| **Safety-Critical Path** (`risk_engine`, `supervisor`, `kill_switch`) | **100%** | **100%** (NFR-SAFE-6) | **Hard CI Failure** — Merge blocked |
| **Execution & Broker Layer** (`execution`, `broker_adapter`) | $\ge 90\%$ | $\ge 85\%$ | **Hard CI Failure** — Merge blocked |
| **Data Platform & Storage** (`data`, `infrastructure`) | $\ge 85\%$ | $\ge 80\%$ | **Hard CI Failure** — Merge blocked |
| **Feature Engine & Agents** (`features`, `agents`, `aggregator`) | $\ge 85\%$ | $\ge 80\%$ | **Hard CI Failure** — Merge blocked |
| **Global Repository Average** | $\ge \mathbf{80\%}$ (NFR-TEST-3) | $\ge 75\%$ | **Hard CI Failure** — Merge blocked |

---

## 4. Verification Commands

```powershell
# 1. Lint and format validation
ruff check .
ruff format --check .

# 2. Strict static type analysis
mypy src tests

# 3. Fast unit tests execution
pytest tests/unit

# 4. Full test suite with branch coverage enforcement
pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=80 tests/

# 5. Safety-critical 100% branch coverage verification
pytest --cov=src/risk_engine --cov=src/supervisor --cov=src/kill_switch --cov-branch --cov-fail-under=100 tests/safety/
```
