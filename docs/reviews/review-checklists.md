# Engineering & Code Review Checklists

## 1. Safety & Architecture Inspection Checklist (Mandatory for PRs)

Every pull request must be inspected against these criteria prior to approval by Agent 16 (Code Review) and Agent 09 (Risk & Safety):

- [ ] **Deterministic Safety Boundary**:
  - [ ] Zero import edges from AI/LLM models or async brokers into `src/risk_engine/`, `src/supervisor/`, or `src/kill_switch/`.
  - [ ] `RiskEngine.evaluate()` evaluates in the strict fail-fast order (Kill Switch $\to$ Daily Loss $\to$ Drawdown $\to$ Exposure $\to$ Sizing $\to$ Volatility $\to$ Confidence).
  - [ ] `Supervisor.decide()` short-circuits to `HOLD`/`NO_TRADE` when Kill Switch is active.
  - [ ] Zero code paths allow `Supervisor` to approve a trade if `risk_result.passed == False`.
- [ ] **Mathematical & Sizing Correctness**:
  - [ ] Position sizing strictly computes `min(raw_quantity, position_cap, exposure_cap)`.
  - [ ] If raw quantity computes to 0, the trade is rejected (never rounded up).
  - [ ] Stop-loss distance is mandatory and strictly positive.
- [ ] **Execution & Idempotency**:
  - [ ] `client_order_id` is deterministically derived from `DecisionRecord.decision_record_id`.
  - [ ] `ExecutionEngine.submit_order()` refuses execution if `_reconciled == False`.
  - [ ] Order parameter translation defaults to limit orders with bounded slippage.
- [ ] **Data Integrity & Point-in-Time Discipline**:
  - [ ] No feature or decision logic accesses data with timestamps $\ge$ current decision point.
  - [ ] All database writes to `decision_records` and `trade_evaluations` are immutable/append-only.
- [ ] **Type Safety & Code Quality**:
  - [ ] Full type annotations passing `mypy --strict`.
  - [ ] Zero usage of `Any` on domain interfaces.
  - [ ] Formatting and linting clean (`ruff check`).
- [ ] **Test Coverage Mandates**:
  - [ ] 100% branch coverage on safety-critical modules (6, 7, 11).
  - [ ] $\ge 80\%$ line coverage on general modules.
  - [ ] Known-answer tests and failure injection tests included where applicable.
- [ ] **Security & Secrets**:
  - [ ] Zero plaintext API keys or credentials in code, comments, or test files.
  - [ ] TLS verification enabled on all HTTP/WebSocket client calls.
