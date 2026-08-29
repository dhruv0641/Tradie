# ADR-0003: Deterministic Minimal-Dependency Isolation of the Safety-Critical Path

## Context & Problem Statement
The system must guarantee that hard risk limits, daily loss boundaries, emergency stops, and kill switches can never be bypassed, loosened, delayed, or overridden by any AI agent, LLM, or reinforcement-learning model (BRD BR-4, FRD-RISK-11, NFR-SAFE-1/2, HLD §8).

## Decision
Structurally isolate the safety-critical components—**Risk Engine (Module 6)**, **Supervisor (Module 7)**, and **Kill Switch / STOP (Module 11)**—inside the Trading Brain with the following hard architectural constraints:

1. **Zero External/AI Dependencies**:
   - Risk checks take only plain, immutable data (`CandidateTrade`, `CapitalState`, `StreakState`, `MarketState`, `RiskConfig`).
   - Zero import edges or network calls to AI model inference, LLMs, or async message brokers.
2. **Fail-Fast Sequential Evaluation**:
   - Checks evaluate in fixed precedence order: Kill Switch $\to$ Daily Loss $\to$ Drawdown Tiers $\to$ Exposure/Position Caps $\to$ Consecutive Losses $\to$ Sizing $\to$ Volatility/Liquidity $\to$ Confidence.
   - Any single failure immediately returns `passed=False` (no weighting, no soft scoring).
3. **Supervisor Precedence Enforcement**:
   - `Supervisor.decide()` has no code path or parameter that allows approval of a trade where `risk_result.passed == False`.
   - Active Kill Switch / STOP short-circuits the first statement in `decide()` to `HOLD` / `NO TRADE`.
4. **In-Memory Kill Switch & Synchronous Audit**:
   - `KillSwitch.is_active()` evaluates $O(1)$ in-memory with zero I/O contention.
   - `KillSwitch.activate()` logs synchronously to audit storage and takes effect in $<2$ seconds.
5. **100% Branch Test Coverage**:
   - CI builds require 100% branch test coverage on Modules 6, 7, and 11, verified via automated static analysis.

## Consequences
### Positive
- Guarantees deterministic, unbreakable capital protection regardless of AI hallucinations or bugs.
- Rapid $<2$s kill-switch activation independent of system load.
- Absolute auditability for regulatory and governance compliance.

### Negative / Risks
- Conservative sizing or false-positive risk triggers will result in `NO TRADE` outcomes, which is an accepted and desired behavior.

## Status
Accepted (Derived from RTLD §2, §5–§16, HLD §8, LLD §5–§7, §10).
