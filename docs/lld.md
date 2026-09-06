# Low-Level Design (LLD)
## AI Trader — Autonomous Intelligent Trading System
### Volume 1: Safety-Critical Path (Risk Engine, Supervisor, Kill Switch), Execution Engine Reconciliation, and Aggregator Scoring

| | |
|---|---|
| **Document Type** | Low-Level Design (LLD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from RTLD v0.1, HLD v0.1, TTD v0.1, ADD v0.1, FRD v0.1, NFRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader RTLD v0.1 (rules/numbers), HLD v0.1 (architecture/boundaries), TTD v0.1 (technology) |
| **Related Documents** | ADD v0.1 (Aggregator methodology, §7), FRD v0.1 (Modules 5, 6, 7, 8, 11), DDD (schema — not yet drafted, §17) |

---

## 1. Purpose of This Document

The RTLD defines *what the numbers and rules are*; the HLD defines *where components sit and how they're isolated*; the TTD defines *what technology implements them*. None of the three specify the actual classes, functions, data structures, and control flow a developer would write. This LLD is that detail — implementable pseudocode and interface contracts for the components named, precise enough to code directly against and to write the verification tests HLD §8 and NFR-SAFE-4/5 require.

Per HLD §19 and SOW §6.4, the safety-critical isolated component (Risk Engine, Supervisor, kill switch/STOP — FRD Modules 6, 7, 11) carries the most technical and safety risk and was flagged to proceed **first**, ahead of other modules' detailed design. Per ADD §13's own recommended next step, the Aggregator's weighted-scoring implementation (FRD Module 5) was flagged to proceed **next**. This document covers those three modules plus the Execution Engine's reconciliation/idempotency logic (FRD Module 8), since TRD-DR-2/3 and NFR-REL-5 make that logic a direct precondition for the safety-critical path resuming safely after a restart. **This is Volume 1 of the LLD, not the complete LLD** — see §16 for what remains.

Consistent with the project's engineering principle of not silently inventing detail, every class/function shape below is a **reasoned design proposal**, implementable against the RTLD/HLD/TTD as currently drafted, and should be confirmed or revised once those upstream documents' own open items (RTLD §18, HLD §17) resolve.

---

## 2. Scope

**In scope (Volume 1):**
- Risk Engine (Module 6): class design, per-check function signatures, evaluation order, config binding to RTLD §14's Numeric Parameter Register.
- Supervisor (Module 7): decision-gate logic, precedence enforcement, interaction with Risk Engine and kill switch.
- Kill switch / manual STOP (Module 11): state machine, activation paths, dependency-minimal wiring, reset semantics.
- Execution Engine (Module 8): startup reconciliation, safe-state fallback, idempotent order submission, duplicate-prevention.
- Aggregator (Module 5): weighted-scoring algorithm, confidence normalization contract, dynamic timeframe selection, disagreement computation.
- The verification tests each component's isolation/precedence property requires (NFR-SAFE-4/5), stated as test-case specifications.

**Out of scope (deferred to later LLD volumes — §16):** Data Pipeline/Feature Engine/Regime Detector internals; Agent Roster per-agent implementations (owned by MLD §6, this LLD only consumes their output contract); Learning Pipeline/model-promotion mechanics beyond what §8's handoff already specifies structurally in HLD §12; Dashboard/Control Service UI; the full data schema (DDD, not yet drafted); backtesting engine internals (BTD owns the mechanics; this LLD's Risk Engine/Aggregator code is written once and used by both live and backtest paths per TRD-PIPE-3/HLD §15, but the backtest harness itself is BTD's document).

---

## 3. Guiding Principles and Constraints Carried Forward (Not Reopened)

| Constraint | Source | Concrete implication for this LLD |
|---|---|---|
| Risk Engine/Supervisor/kill switch have minimal runtime dependencies — no model-inference service, external LLM API, or general-purpose event bus in their call path. | TRD-ARCH-3; HLD §8 | Every function in §5–§7 below takes only plain data (dataclasses/primitives) as arguments — never an agent object, model handle, or async event-bus subscription. |
| Kill-switch state is checked **first**, structurally, before Aggregator output is even read. | HLD §8; FRD-X-5 | `Supervisor.decide()`'s first line is a kill-switch check — not "one of the conditions evaluated," but a short-circuit before any other input is touched. |
| All hard limits are an all-must-pass checklist; any single breach blocks, regardless of favorable factors elsewhere. | RTLD §13.1 step 7; NFRD-SAFE-4 | `RiskEngine.evaluate()` returns on first failing check (fail-fast), never a weighted/averaged score. |
| Every RTLD-* numeric value is externalized configuration, never hardcoded, and every value change is itself logged. | RTLD §14; NFR-MAINT-3 | `RiskConfig` is loaded from the environment-specific config store (TTD §12/§15), versioned, and the active `RiskConfig` version ID is stamped onto every `DecisionRecord`. |
| No unlogged decision may occur — every cycle, including NO TRADE/HOLD, produces a decision record. | HLD §7; FRD-X-3 | Every public entry point in §5–§8 returns a result object designed to be written to the decision-record store unconditionally by the caller (Evaluation Service, outside this LLD's scope) — none of these functions have a "silent" return path. |
| No AI/LLM component may be a required dependency for hard risk-limit evaluation or kill-switch operation. | BRD BR-4 | Verified structurally in §9 via an import/dependency check, not by convention. |

---

## 4. Shared Data Structures (Provisional — Pending DDD)

These are the in-memory/interchange shapes this LLD's functions consume and produce. **They are provisional stand-ins for the DDD's eventual formal schema** (§17 open item) — field names below should be reconciled against DDD §5 once that document exists, not treated as the final schema.

```python
@dataclass(frozen=True)
class CandidateTrade:
    instrument: str
    direction: Literal["BUY", "SELL"]
    entry_price: Decimal
    stop_price: Decimal
    timeframe: str
    trade_quality_score: float          # from Aggregator, §8
    expected_value: Decimal             # from Aggregator, post-cost per FR-25
    confidence: float                   # normalized [0,1], from Aggregator

@dataclass(frozen=True)
class CapitalState:
    current_capital: Decimal
    peak_equity: Decimal                # for drawdown calc, RTLD §8
    session_start_capital: Decimal      # for daily loss calc, RTLD §7
    currently_deployed: Decimal
    open_position_count: int
    trades_today: int

@dataclass(frozen=True)
class StreakState:
    consecutive_losses: int             # scope (rolling vs. session) — RTLD §18 item 8, open

@dataclass(frozen=True)
class MarketState:
    instrument: str
    current_volatility: Decimal
    trailing_20session_avg_volatility: Decimal
    data_quality: Literal["VALIDATED", "QUARANTINED", "STALE"]
    exchange_condition: Literal["NORMAL", "HALTED", "CIRCUIT"]

@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    failed_check: str | None            # e.g. "daily_loss_limit"
    rtld_param_id: str | None           # e.g. "RTLD-4" — for audit traceability
    reason: str | None
    config_version: str                 # which RiskConfig snapshot was in force

@dataclass(frozen=True)
class Decision:
    outcome: Literal["BUY", "SELL", "HOLD", "NO_TRADE"]
    reason: str
    risk_check: RiskCheckResult
    kill_switch_active: bool
```

---

## 5. Risk Engine — Detailed Design (FRD Module 6)

### 5.1 Class Shape

```python
class RiskConfig:
    """Loaded from externalized config (TTD §12/§15); one RTLD-* field each; versioned."""
    max_risk_per_trade_pct: Decimal          # RTLD-3
    max_daily_loss_pct: Decimal              # RTLD-4
    hard_drawdown_halt_pct: Decimal          # RTLD-5
    extreme_loss_killswitch_pct: Decimal     # RTLD-6
    max_portfolio_exposure_pct: Decimal      # RTLD-7
    max_position_size_pct: Decimal           # RTLD-8
    max_simultaneous_positions: int          # RTLD-9
    max_trades_per_day: int                  # RTLD-10
    consec_loss_reduce_trigger: int          # RTLD-11
    consec_loss_pause_trigger: int           # RTLD-12
    vol_reduce_multiple: Decimal             # RTLD-13
    vol_block_multiple: Decimal              # RTLD-14
    min_confidence_threshold: float          # RTLD-16
    version: str                             # config snapshot identifier, for audit (§3)

class RiskEngine:
    def __init__(self, config: RiskConfig, kill_switch: "KillSwitch"):
        self._config = config
        self._kill_switch = kill_switch      # read-only reference; RiskEngine never mutates it

    def evaluate(
        self,
        candidate: CandidateTrade,
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
    ) -> RiskCheckResult:
        ...
```

### 5.2 Evaluation Order (Fail-Fast, per RTLD §13.1 Step 7)

```python
def evaluate(self, candidate, capital, streak, market) -> RiskCheckResult:
    checks: list[Callable[[], RiskCheckResult]] = [
        lambda: self._check_kill_switch(),
        lambda: self._check_daily_loss(capital),
        lambda: self._check_drawdown_tier(capital),
        lambda: self._check_exposure_position_caps(candidate, capital),
        lambda: self._check_consecutive_loss_tier(streak),
        lambda: self._check_per_trade_risk_and_sizing(candidate, capital, streak),
        lambda: self._check_volatility_liquidity_market(candidate, market),
        lambda: self._check_model_confidence(candidate),
    ]
    for check in checks:
        result = check()
        if not result.passed:
            return result   # fail-fast: first breach wins, no averaging (NFRD-SAFE-4)
    return RiskCheckResult(passed=True, failed_check=None, rtld_param_id=None,
                            reason="all checks passed", config_version=self._config.version)
```

Each `_check_*` method is a **pure function of its arguments and `self._config`** — no I/O, no network call, no model inference — satisfying TRD-ARCH-3's minimal-dependency requirement at the function-signature level, not just the component-boundary level.

### 5.3 Representative Check Implementations

```python
def _check_kill_switch(self) -> RiskCheckResult:
    if self._kill_switch.is_active():
        return RiskCheckResult(False, "kill_switch", None,
                                "kill switch/STOP is active", self._config.version)
    return RiskCheckResult(True, None, None, None, self._config.version)

def _check_daily_loss(self, capital: CapitalState) -> RiskCheckResult:
    loss = capital.session_start_capital - capital.current_capital
    limit = capital.session_start_capital * self._config.max_daily_loss_pct
    if loss >= limit:
        return RiskCheckResult(False, "daily_loss_limit", "RTLD-4",
                                f"daily loss {loss} >= limit {limit}", self._config.version)
    return RiskCheckResult(True, None, None, None, self._config.version)

def _check_per_trade_risk_and_sizing(self, candidate, capital, streak) -> RiskCheckResult:
    # Position sizing per RTLD §6 — computed here, not in the Aggregator, since
    # the size depends on capital/exposure state the Aggregator does not own.
    risk_pct = self._config.max_risk_per_trade_pct
    if streak.consecutive_losses >= self._config.consec_loss_reduce_trigger:
        risk_pct = risk_pct * Decimal("0.5")   # RTLD-11 tier-1 reduction
    risk_amount = capital.current_capital * risk_pct
    stop_distance = abs(candidate.entry_price - candidate.stop_price)
    if stop_distance == 0:
        return RiskCheckResult(False, "undefined_stop", "RTLD-3",
                                "no computable stop distance", self._config.version)
    raw_qty = (risk_amount / stop_distance).to_integral_value(rounding=ROUND_FLOOR)
    if raw_qty <= 0:
        return RiskCheckResult(False, "unsizeable", "RTLD-3",
                                "risk budget cannot buy 1 unit at this stop distance",
                                self._config.version)
    # ... apply exposure-headroom and max-position-value caps (RTLD §6 formula),
    # final_qty = min(raw_qty, position_cap_qty, exposure_cap_qty); attach to result
    # via a side-channel field (elided here) consumed by position-sizing output —
    # full field list is a DDD-dependent detail (§17).
    return RiskCheckResult(True, None, None, None, self._config.version)
```

The remaining checks (`_check_drawdown_tier`, `_check_exposure_position_caps`, `_check_consecutive_loss_tier`, `_check_volatility_liquidity_market`, `_check_model_confidence`) follow the same shape: read the relevant `RiskConfig` field(s), compare against `capital`/`streak`/`market`/`candidate`, return `RiskCheckResult`. Each cites its RTLD-* parameter ID in the result per §3's audit requirement.

### 5.4 Open Design Detail

`_check_volatility_liquidity_market`'s liquidity-impact sub-check cannot be finalized (empty `rtld_param_id: RTLD-18`) until broker/instrument selection resolves (RTLD §18 item 2 / TTD §17) — this LLD leaves the function signature in place with a `NotImplementedError` guard rather than a guessed threshold, so the gap is loud, not silently defaulted to "always pass."

---

## 6. Kill Switch / Manual STOP — Detailed Design (FRD Module 11)

### 6.1 State Machine

```
INACTIVE ──(trigger)──▶ ACTIVE ──(operator reset, explicit)──▶ INACTIVE
```

No transition from ACTIVE back to INACTIVE exists except the explicit, authenticated operator-reset path (RTLD §16 "Reset" — never automatic, regardless of trigger source).

```python
class TriggerSource(Enum):
    MANUAL_OPERATOR = "manual_operator"
    EXTREME_DRAWDOWN = "extreme_drawdown"      # RTLD-6, auto
    # additional auto-trigger sources are an HLD-confirmed open item (RTLD §18 item... N/A here;
    # any future source added here must be reviewed against TRD-ARCH-3 before being wired in.

class KillSwitch:
    def __init__(self, audit_log: "AuditLog"):
        self._state = KillSwitchState.INACTIVE
        self._audit_log = audit_log            # direct, synchronous write — see §6.2

    def is_active(self) -> bool:
        return self._state == KillSwitchState.ACTIVE     # O(1), in-memory, no I/O

    def activate(self, source: TriggerSource, reason: str) -> None:
        self._state = KillSwitchState.ACTIVE
        self._audit_log.record_sync(event="kill_switch_activated",
                                     source=source, reason=reason,
                                     timestamp=utc_now())               # RTLD-17: <2s target

    def reset(self, operator_auth: "OperatorAuthToken") -> None:
        if not operator_auth.is_valid():          # TRD-SEC-3
            raise PermissionError("kill switch reset requires authenticated operator action")
        self._state = KillSwitchState.INACTIVE
        self._audit_log.record_sync(event="kill_switch_reset",
                                     operator=operator_auth.operator_id,
                                     timestamp=utc_now())
```

### 6.2 Dependency-Minimal Wiring (Implements HLD §8, NFR-SAFE-2)

- `KillSwitch.is_active()` is a plain in-memory boolean read — **no** database query, no network call, no lock contention with the Aggregator/Agent Roster. This is what makes it safe for `RiskEngine._check_kill_switch()` (§5.3) to call it as the very first check without incurring the latency/failure surface of anything else in the pipeline.
- `Dashboard STOP button → KillSwitch.activate(MANUAL_OPERATOR, ...)` is a direct function call (or the shortest available IPC/HTTP hop if Dashboard and Trading Brain are different processes per TTD §15) — **not** routed through the Aggregator, Agent Roster, or the general message-passing path ruled out in TTD §10.
- `_audit_log.record_sync(...)` is a **synchronous, blocking** write (unlike the async-tolerant application logs elsewhere) specifically because RTLD §16's <2-second activation target and BR-7's full-auditability requirement both apply to this exact event — an unlogged kill-switch activation would itself be a safety-critical logging gap (TRD-OBS-2).

### 6.3 Verification Test Specification (Implements NFR-SAFE-4)

| Test ID | Scenario | Expected Result |
|---|---|---|
| KS-TEST-1 | All upstream agents/Aggregator recommend a high-quality BUY; kill switch is ACTIVE. | `Supervisor.decide()` returns HOLD/NO_TRADE regardless of Aggregator output — proves independence from favorable upstream signals. |
| KS-TEST-2 | Aggregator/Agent Roster process is artificially stalled (simulated hang). | `KillSwitch.activate()` and `is_active()` both complete within RTLD-17's <2s target, unaffected by the stalled process — proves the minimal-dependency property, not just the logical wiring. |
| KS-TEST-3 | Kill switch activated via `EXTREME_DRAWDOWN` auto-trigger at exactly RTLD-6's 10% threshold. | Activation fires at the threshold, not after it, and blocks all new order submission from that point forward. |
| KS-TEST-4 | Reset attempted with an invalid/missing operator auth token. | `PermissionError` raised; state remains ACTIVE. |

This suite (or its equivalent) must run and pass on every deployment touching the Risk Engine, Supervisor, or kill-switch code (TRD-CI-2) — re-run requirement per RTLD §16's own testing clause.

---

## 7. Supervisor — Detailed Design (FRD Module 7)

```python
class Supervisor:
    def __init__(self, risk_engine: RiskEngine, kill_switch: KillSwitch):
        self._risk_engine = risk_engine
        self._kill_switch = kill_switch

    def decide(
        self,
        candidate: CandidateTrade | None,   # None if Aggregator itself produced no candidate
        capital: CapitalState,
        streak: StreakState,
        market: MarketState,
        has_open_position: bool,
    ) -> Decision:
        # Precedence: kill switch is checked before the Aggregator's candidate is even
        # inspected (FRD-X-5; HLD §8's "checked first, structurally").
        if self._kill_switch.is_active():
            outcome = "HOLD" if has_open_position else "NO_TRADE"
            return Decision(outcome, "kill switch/STOP active",
                             risk_check=RiskCheckResult(False, "kill_switch", None,
                                                         "active", self._risk_engine._config.version),
                             kill_switch_active=True)

        if candidate is None:
            return Decision("NO_TRADE", "no candidate cleared confidence/EV gates upstream",
                             risk_check=RiskCheckResult(True, None, None, None,
                                                         self._risk_engine._config.version),
                             kill_switch_active=False)

        risk_result = self._risk_engine.evaluate(candidate, capital, streak, market)
        if not risk_result.passed:
            # Supervisor cannot approve what the Risk Engine blocked (FRD-SUP-6) —
            # there is no override path here, by construction: no parameter exists
            # on this method that could grant one.
            return Decision("NO_TRADE", f"risk check failed: {risk_result.failed_check}",
                             risk_check=risk_result, kill_switch_active=False)

        outcome = candidate.direction  # "BUY" or "SELL"
        return Decision(outcome, "cleared all gates", risk_check=risk_result,
                         kill_switch_active=False)
```

**Note on FRD-SUP-6 enforcement:** the absence of any "override" or "force-approve" parameter on `Supervisor.decide()` is deliberate — RTLD/FRD's "Supervisor cannot approve what Risk Engine blocked" is enforced by the method signature having no code path that returns BUY/SELL without `risk_result.passed == True`, not by a runtime `if` check that a future edit could accidentally bypass. A code reviewer checking this property should be checking the **shape of the function**, not tracing every call site.

---

## 8. Aggregator — Detailed Design (FRD Module 5, per ADD §7)

Implements ADD §7.1's proposed weighted-scoring methodology (equal-weighted initially, per-agent weights configurable).

### 8.1 Confidence Normalization Contract (ADD §7.2)

```python
@dataclass(frozen=True)
class AgentSignalOutput:
    agent_id: str
    direction: Literal["LONG", "SHORT", "NO_VIEW"]
    confidence: float          # already normalized to [0, 1] by the agent per ADD §7.2's contract
    inputs_used: dict          # for FRD-EVAL-2's explainability requirement
```

The Aggregator does **not** perform normalization itself — ADD §7.2 places that responsibility on each agent so the Aggregator can remain agent-agnostic; the Aggregator's only obligation is to reject (log and treat as `NO_VIEW`) any output outside `[0, 1]`, defensively, rather than silently accepting a malformed agent output.

### 8.2 Weighted Scoring

```python
class AggregatorConfig:
    agent_weights: dict[str, float]      # equal-weighted default per ADD §7.1
    min_quality_threshold: float          # FRD-AGG-6 gate

def aggregate(
    outputs: list[AgentSignalOutput],
    config: AggregatorConfig,
) -> "AggregationResult":
    usable = [o for o in outputs if o.direction != "NO_VIEW"]
    if not usable:
        return AggregationResult(passed=False, score=0.0, direction=None,
                                  disagreement=0.0, reason="no agent expressed a view")

    total_weight = sum(config.agent_weights.get(o.agent_id, 1.0) for o in usable)
    signed_scores = [
        (1 if o.direction == "LONG" else -1) * o.confidence * config.agent_weights.get(o.agent_id, 1.0)
        for o in usable
    ]
    weighted_score = sum(signed_scores) / total_weight        # in [-1, 1]
    disagreement = population_stdev([  # ADD §7.4 — preserved into the decision record, not discarded
        (1 if o.direction == "LONG" else -1) * o.confidence for o in usable
    ])

    quality_score = abs(weighted_score)      # magnitude, independent of direction
    passed = quality_score >= config.min_quality_threshold
    direction = ("BUY" if weighted_score > 0 else "SELL") if passed else None

    return AggregationResult(
        passed=passed, score=quality_score, direction=direction,
        disagreement=disagreement,
        reason="cleared threshold" if passed else "below min_quality_threshold (FRD-AGG-6)",
    )
```

### 8.3 Dynamic Timeframe Selection (ADD §7.3)

```python
def select_best_timeframe(
    per_timeframe_outputs: dict[str, list[AgentSignalOutput]],
    config: AggregatorConfig,
) -> "AggregationResult":
    results = {tf: aggregate(outs, config) for tf, outs in per_timeframe_outputs.items()}
    passing = {tf: r for tf, r in results.items() if r.passed}
    if not passing:
        # Best-of-rejected is not acceptable (FRD-AGG-4) — NO TRADE regardless of
        # how the timeframes compare to each other.
        return AggregationResult(passed=False, score=0.0, direction=None,
                                  disagreement=0.0, reason="no timeframe cleared threshold")
    best_tf = max(passing, key=lambda tf: passing[tf].score)
    return passing[best_tf]
```

### 8.4 Expected-Value Computation

Expected value (RTLD §13.1 step 5's EV gate) is computed **downstream of** `aggregate()`'s quality score, using the realistic cost/friction model owned by BTD (FR-25) — this LLD's Aggregator produces the quality score and direction only; EV computation calls into the shared cost-model function BTD's document specifies, rather than duplicating that logic here (avoids the exact divergence risk TRD-PIPE-3 warns about for data contracts, applied here to cost-model logic).

---

## 9. Execution Engine — Reconciliation and Idempotency (FRD Module 8)

### 9.1 Startup Reconciliation (Implements TRD-DR-2/3, NFR-REL-5)

```python
class ExecutionEngine:
    def __init__(self, broker: "BrokerAdapter", db: "PositionStore", risk_engine: RiskEngine):
        self._broker = broker
        self._db = db
        self._reconciled = False

    def startup_reconcile(self) -> ReconciliationResult:
        try:
            broker_state = self._broker.get_positions_and_open_orders()
        except BrokerConnectionError:
            self._reconciled = False
            return ReconciliationResult(ok=False, reason="broker unreachable at startup")

        local_state = self._db.get_last_known_state()
        mismatches = diff_positions(broker_state, local_state)
        if mismatches:
            self._db.record_reconciliation_discrepancy(mismatches)   # BR-7 auditability
            self._reconciled = False
            return ReconciliationResult(ok=False, reason=f"{len(mismatches)} mismatch(es)")

        self._db.commit_reconciled_state(broker_state)
        self._reconciled = True
        return ReconciliationResult(ok=True, reason="reconciled clean")

    def submit_order(self, decision: Decision, sized_trade: CandidateTrade) -> OrderResult:
        if not self._reconciled:
            # TRD-DR-3: never "assume state was fine and continue trading."
            return OrderResult(submitted=False, reason="unreconciled state — safe-state hold")
        ...
```

`ExecutionEngine.submit_order()` is structurally incapable of submitting while `self._reconciled` is `False` — there is no parameter or flag on the method that bypasses this, mirroring §7's Supervisor-override note: the safety property is a property of the code shape, not a runtime check someone could accidentally skip.

### 9.2 Idempotent Submission (Implements TRD-EXEC-2, FRD-RISK duplicate-prevention)

```python
def _generate_client_order_id(decision_record_id: str) -> str:
    # Deterministic from the decision record's own ID, so retrying the *same*
    # decision never produces a second client-order-id, even across a process
    # restart (the decision_record_id, not a random UUID, is the source of truth).
    return f"aitrader-{decision_record_id}"

def submit_order(self, decision, sized_trade) -> OrderResult:
    if not self._reconciled:
        return OrderResult(submitted=False, reason="unreconciled state — safe-state hold")

    client_order_id = _generate_client_order_id(decision.decision_record_id)
    existing = self._db.get_order_submission(client_order_id)
    if existing is not None:
        # Already submitted (e.g., this is a retry after a crash) — return the
        # prior result rather than submitting again (TRD-EXEC-2).
        return existing

    result = self._broker.place_order(client_order_id=client_order_id,
                                       instrument=sized_trade.instrument,
                                       direction=sized_trade.direction,
                                       quantity=sized_trade.final_quantity,
                                       price=sized_trade.entry_price)
    self._db.record_order_submission(client_order_id, result)   # single source of truth
    return result
```

### 9.3 Broker Disconnection Handling (RTLD §11, NFR-REL-4)

```python
def on_broker_disconnect(self, detected_at: datetime) -> None:
    self._reconciled = False
    deadline = detected_at + timedelta(seconds=self._config.reconnection_window_s)  # RTLD-15, 30s default
    self._audit_log.record_sync(event="broker_disconnected", timestamp=detected_at)

def on_reconnection_window_elapsed(self) -> None:
    if not self._reconciled:
        # Escalate to Risk Engine / operator per RTLD §11 — new order submission
        # stays blocked (already true via §9.1's structural guard) and this is
        # additionally surfaced as a system-health event (TTD §13's /health check).
        self._health_reporter.report_degraded("broker_disconnected_past_reconnection_window")
```

---

## 10. Isolation and Precedence — Structural Verification (Implements NFR-SAFE-5)

A dependency-graph check (run in CI per TRD-CI-2, using `mypy`/import-linter per TTD §14) must confirm, on every change touching §5–§7:

1. **No import edge** from `risk_engine.py`, `supervisor.py`, or `kill_switch.py` into any Agent Roster module, model-inference library, or external LLM client library.
2. **No import edge** from `risk_engine.py`/`supervisor.py`/`kill_switch.py` into any general-purpose messaging/event-bus module (none exists per TTD §10, but this guards against one being added later without review).
3. `Supervisor.decide()`'s kill-switch check (§7) occurs as the **first statement** in the function body — a lint rule or a targeted unit test (KS-TEST-1, §6.3) should fail the build if this is ever reordered.
4. `RiskEngine.evaluate()` has **no code path** that returns `passed=True` after an earlier check has already returned `passed=False` — enforced by the fail-fast loop shape in §5.2, checked by a mutation test that flips the early-return and confirms the test suite catches it.

These checks are what makes HLD §8's isolation claim ("a code review / dependency-graph check should confirm no such edge exists") an executable CI gate rather than a one-time manual review.

---

## 11. Regime Detector — Note on §8's Open Boundary Question

HLD §17 item 7 leaves open whether the Regime Detector should sit inside the safety-critical isolated boundary. This LLD's answer, consistent with the design above: **no** — `RiskEngine.evaluate()` and `Supervisor.decide()` (§5, §7) take `MarketState`/`CandidateTrade` as plain data, already computed upstream; neither function calls into the Regime Detector directly. This satisfies HLD §17 item 7's request for a dependency-graph check (§10 above covers it) but does not by itself resolve whether the Regime Detector's *output* being wrong could create a hidden risk-relevant dependency — that is a data-quality question for the Regime Detector's own (not-yet-written) LLD, not a code-boundary question this volume can close alone.

---

## 12. Configuration Loading and Versioning

```python
def load_risk_config(environment: Literal["research", "paper", "live"]) -> RiskConfig:
    # Environment-specific config store (TTD §12/§15) — paper and live never share
    # a config file by default (TRD-DEPLOY-2).
    raw = config_store.load(f"risk_config.{environment}.yaml")
    config = RiskConfig(**raw, version=raw["_version"])
    audit_log.record_sync(event="risk_config_loaded", environment=environment,
                           version=config.version)
    return config
```

Every `RiskConfig` change is itself an audited event (RTLD §14's closing requirement) — this function's `audit_log.record_sync` call is not optional instrumentation, it is the mechanism that requirement is implemented through.

---

## 13. Testing Requirements Summary (Implements TRD-CI-1–3)

| Component | Required test categories |
|---|---|
| Risk Engine | Unit test per `_check_*` method (boundary values at exactly the RTLD-* threshold, one unit above, one below); fail-fast ordering test; config-version stamping test. |
| Kill switch | KS-TEST-1–4 (§6.3); latency test confirming `activate()`→`is_active()` visible state change completes well under RTLD-17's 2s target under load. |
| Supervisor | Precedence test (kill switch overrides any candidate); no-override-path test (static/code-shape check per §10 item 4, not just a runtime assertion). |
| Aggregator | Normalization-rejection test (malformed agent output outside [0,1]); NO_VIEW handling; timeframe-selection "no timeframe passes → NO TRADE" test (§8.3); disagreement calculation known-answer test. |
| Execution Engine | Reconciliation-mismatch → safe-state test; idempotency test (same decision submitted twice → one broker order); broker-disconnect → escalation-after-window test. |

All of the above are **known-answer/regression tests** in the TRD-CI-3 sense — fixed inputs, fixed expected outputs — not property-based or fuzz tests alone, since the safety-critical requirement is exact, auditable correctness at specific thresholds, not general robustness.

---

## 14. Traceability

| LLD Section | RTLD Reference | HLD Reference | ADD/FRD Reference |
|---|---|---|---|
| §5 Risk Engine | RTLD §5–§12, §14 | HLD §6, §8 | FRD Module 6, FRD-RISK-1–11 |
| §6 Kill switch | RTLD §16 | HLD §8 | FRD Module 11, FRD-RISK-12, FRD-DASH-7, FRD-X-5 |
| §7 Supervisor | RTLD §13.1 steps 7–9 | HLD §7, §8 | FRD Module 7, FRD-SUP-2/5/6 |
| §8 Aggregator | RTLD §13.1 steps 3–5 | HLD §6, §7 | ADD §7; FRD Module 5, FRD-AGG-1–6 |
| §9 Execution Engine | RTLD §11 | HLD §14 | FRD Module 8, FRD-EXEC-5/6/7; TRD-DR-2/3 |
| §10 Structural verification | — | HLD §8 | NFR-SAFE-4/5 |

Every class/function named above should be entered into the Requirements Traceability Matrix against its RTLD/FRD/NFR-ID, and §10's CI checks should be entered as standing gates, not one-time verifications.

---

## 15. Open Items Carried Into Implementation

1. **Liquidity-impact threshold (RTLD-18)** — §5.4's `_check_volatility_liquidity_market` liquidity sub-check has a placeholder guard, not a value, pending broker/instrument selection (TTD §17).
2. **Data staleness threshold (RTLD-19)** — affects when `MarketState.data_quality` is set to `STALE` upstream of this LLD's checks; not this LLD's to resolve, but this LLD's `_check_volatility_liquidity_market` consumes whatever value NFRD confirms.
3. **Rolling vs. session-based consecutive-loss counting (RTLD §18 item 8)** — `StreakState.consecutive_losses`'s reset semantics are not fixed here; §5.3's `_check_per_trade_risk_and_sizing` reads whatever value it's given, but the component that computes `StreakState` (not in this LLD's scope) needs this resolved.
4. **Confidence-threshold methodology (RTLD-16)** — `RiskConfig.min_confidence_threshold` and `AggregatorConfig.min_quality_threshold` are two related but distinct gates (RTLD §13.1 steps 4 and 7's final sub-check); confirm with the operator whether these should in fact be the same configured value or intentionally different, since RTLD's own text lists confidence in both places without clarifying.
5. **Auto-trigger sources for the kill switch beyond `EXTREME_DRAWDOWN`** (RTLD §16 "to be confirmed at HLD") — `TriggerSource` enum in §6.1 is intentionally left extensible but any addition must re-pass the §10 dependency checks before being wired in.
6. **DDD does not yet exist** — §4's data structures are provisional; once the DDD is drafted, every dataclass in §4 should be reconciled field-by-field against it, and any divergence resolved by updating this LLD, not by the implementation silently diverging from both.

---

## 16. Remaining LLD Scope (Future Volumes)

Not covered in this volume, to be produced as separate LLD volumes once their prerequisite documents/decisions are ready:

- **Volume 2 — Data Pipeline, Feature Engine, Regime Detector** (depends on data-vendor selection, TTD §17, and the DDD).
- **Volume 3 — Agent Roster per-agent implementations** (depends on MLD §6's per-agent formulas, already specified there at the algorithm level — this volume would be the code-structure wrapper, e.g. how each agent conforms to the `AgentSignalOutput` contract used in §8 above).
- **Volume 4 — Learning Pipeline and Model Promotion Handoff** (depends on HLD §12's handoff design and BRD §11 item 6's human-signoff resolution).
- **Volume 5 — Dashboard/Control Service** (depends on the UI/UX Spec and the API Spec, neither yet drafted).
- **Volume 6 — Capital Manager** (depends on RTLD §15's open items, particularly the live/paper divergence tolerance band).

---

## 17. Document Governance

This LLD must remain consistent with the RTLD (numbers/rules), HLD (boundaries), and TTD (technology). Any implementation detail here that cannot satisfy an RTLD rule or HLD boundary must either (a) trigger a documented exception with operator sign-off, or (b) trigger revision of the RTLD/HLD first — never be implemented silently in contradiction of either, consistent with every other document in this suite's governance clause.

This LLD should be revisited whenever:
- Any RTLD §14 Numeric Parameter Register value changes (affects `RiskConfig` field semantics, not just its value).
- The DDD is drafted (§4's provisional structures must be reconciled against it).
- Broker/data-vendor selection resolves (§15 items 1–2 move from placeholder to implementable).
- Any §13 test category reveals the design above does not behave as specified (per NFR-SAFE-4's requirement that this be demonstrated, not assumed).

**Next recommended step:** implement §5–§10 against this design, write and pass the §13 test suite (especially KS-TEST-1–4) before any other module is wired to call into the Supervisor, then proceed to Volume 2 (Data Pipeline/Feature Engine/Regime Detector) once data-vendor selection (TTD §17) resolves — consistent with HLD §16's V0–V3 sequencing, where the full safety-critical pipeline shape exists end-to-end (against simulated decisions) before real-time data or live execution are introduced.
