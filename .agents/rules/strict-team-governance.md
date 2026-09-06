# Strict Team Governance & Engineering Laws

## 1. Non-Negotiable Core Engineering Principles

1. **Safety First & Deterministic Independence**:
   - Hard risk limits (daily loss limit, max drawdown, max exposure, position size caps, consecutive loss circuit breakers, kill switch) execute on an isolated, zero-dependency code path.
   - **No AI model, LLM, prompt, or reinforcement-learning policy may EVER loosen, override, or bypass deterministic safety limits.**
   - Agent 09 (Risk & Safety) holds absolute, binding **veto power** over any change touching risk, execution, or capital.

2. **Research Brain vs. Trading Brain Strict Separation**:
   - The **Research Brain** (offline experimentation, model training, backtesting, candidate generation) has **zero network routes, zero broker credentials, and zero runtime capability** to place live orders or modify live risk configurations.
   - The **Trading Brain** runs only approved, immutable, version-controlled production artifacts.

3. **NO TRADE Is a First-Class Decision**:
   - The system must **never** force a trade. Valid cycle decisions are strictly: `BUY`, `SELL`, `HOLD`, `NO_TRADE`.
   - Standing down during unquantified, choppy, or high-risk conditions with `NO_TRADE` is an explicitly successful outcome.

4. **Capital Preservation Over Return**:
   - Hierarchy of preferences:
     $$\text{NO TRADE} > \text{Low-Quality Trade} > \text{Small Loss} > \text{Catastrophic Loss}$$
     $$\text{Robustness} > \text{Backtest Perfection}$$
     $$\text{Long-Term Survival} > \text{Short-Term Profit Maximization}$$

5. **No Fake Intelligence**:
   - Never label a component an "AI agent" if it is a rule-based heuristic or mathematical formula.
   - Default to the simplest defensible statistical or rule-based method. Introduce machine learning only where rigorous out-of-sample outperformance is proven.

6. **No Silent Capital Scaling**:
   - Live trading starts at ₹10,000. Capital scales only upon satisfying all predefined mathematical criteria (RTLD §15) and requires formal, explicit human operator authorization.

---

## 2. Zero-Tolerance Code Quality Laws

1. **Strict Type Annotations**:
   - All code must pass `mypy --strict`.
   - `disallow_untyped_defs = true`, `disallow_incomplete_defs = true`, `check_untyped_defs = true`.
   - **Zero usage of `Any`** on domain interfaces, public APIs, or safety functions. Use typed Generics, Protocols, or strict Pydantic models.

2. **Static Formatting & Linting**:
   - All code must pass `ruff check .` with zero errors and zero warnings.
   - Line length strictly capped at 100 characters.
   - All imports must be cleanly sorted and categorized via `ruff-format` / `isort`.

3. **Zero Secrets in Source Control**:
   - Staged commits are scanned via pre-commit hooks (`gitleaks`, `detect-secrets`).
   - Plaintext API keys, tokens, passwords, or connection strings in code, comments, or test files trigger immediate rejection.

4. **Fail-Fast & Zero Silent Failures**:
   - Never write bare `except:` or `except Exception: pass`.
   - Log all caught exceptions with structured JSON context and traceback via `structlog`.
   - Missing required configurations or corrupted data must trigger an immediate, graceful abort.

5. **Financial Arithmetic Integrity**:
   - Never use floating-point numbers (`float`) for prices, quantities, balances, fees, or P&L.
   - Always use Python's `Decimal` class for financial precision.

6. **Immutable Audit Trail**:
   - Database writes to `decision_records` and `trade_evaluations` must be append-only.
   - Every execution cycle, including `NO_TRADE` and `HOLD`, must produce a structured, timestamped `DecisionRecord`.

---

## 3. The 10-Point Agent Output Contract

Every deliverable produced by an agent must provide:
1. **Context**: Source documents, requirements, and versions consulted.
2. **Objective**: Specific engineering responsibility addressed.
3. **Findings**: Key observations, invariants, constraints, or anomalies discovered.
4. **Decisions**: Technical/architectural choices made with explicit rationales.
5. **Artifacts**: Exact file paths created, modified, or deleted.
6. **Dependencies**: Upstream inputs consumed and downstream components affected.
7. **Risks**: Potential failure modes, trade-offs, and mitigation strategies.
8. **Open Questions**: Unresolved items requiring operator or upstream architectural escalation.
9. **Validation**: Automated test evidence, static analysis, or mathematical proofs verifying correctness.
10. **Handoff**: Specific context, deliverables, and instructions for the next agent.

---

## 4. Definition of Done (DoD)

A task or sprint is declared **DONE** only when:
- [ ] Requirements lineage is identified and traced in `docs/project-context/traceability-matrix.md`.
- [ ] Architecture and interface contracts are consistent with HLD, TTD, and LLD.
- [ ] Code is modular, clean, and passes `mypy --strict`.
- [ ] Unit and integration tests pass cleanly via `pytest`.
- [ ] Safety-critical code paths achieve **100% branch coverage** (NFR-SAFE-6).
- [ ] General modules achieve at least **80% line coverage** (NFR-TEST-3).
- [ ] Pre-commit secret scanning passes cleanly.
- [ ] Structured observability logging (`structlog`) is integrated with correlation IDs.
- [ ] Documentation and specifications are updated in sync with code.
- [ ] Principal Code Reviewer (Agent 16) and Risk & Safety Officer (Agent 09) have approved.
