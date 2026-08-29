# Execution Design Document (EDD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Execution Design Document (EDD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD, BRD, FRD, NFRD, TRD, HLD, RTLD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader FRD v0.1 (Module 8), TRD v0.1 (§8), HLD v0.1 (§9, §11, §14), RTLD v0.1 (§16) |

---

## 1. Purpose of This Document

FRD Module 8 states *what* the Execution Engine must do (authenticate, place/modify/cancel orders, track state, prevent duplicates, handle failures). TRD §8 states the *technical properties* its broker integration must have. HLD §9 places it behind a Broker Adapter Interface and HLD §14 sketches failure-mode responses at the architecture level. RTLD §16 specifies the kill switch's behavior, which the Execution Engine must obey. None of these documents specify the actual **mechanics**: the order lifecycle state machine, the exact idempotency mechanism, how a Supervisor decision is translated into concrete order parameters, how reconciliation actually runs on restart, or how the 2-second and 5-second latency targets (NFRD §14) are actually budgeted across the pipeline.

This EDD is that document — the detailed design of Module 8, the one component in the architecture that is *not* AI/model logic (that's ADD/MLD/SLD's territory) but is instead the deterministic, safety-adjacent bridge between an approved decision and a real order. Consistent with TRD-ARCH-3/HLD §8, this EDD's design must not introduce any dependency that could couple order execution's correctness to a slow or unavailable AI component.

Consistent with the project's engineering principle of not silently inventing critical requirements, every numeric value below is a **derived, reasoned proposal**, flagged **Proposed — pending operator sign-off** in the Execution Parameter Register (§13), in the same style as RTLD §14, BTD §6, MLD §11, and the SLD §10 register.

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| The Execution Engine shall prioritize correctness and safety over speed unless a validated strategy has a documented low-latency requirement. | FRD-EXEC-9; PRD FR-17 |
| The Execution Engine must not silently continue as if orders succeeded on broker/API failure; it must escalate to the Risk Engine and, where configured, to human notification. | FRD-EXEC-6 |
| A broker change must not require changes to the Risk Engine, Supervisor, or Evaluation modules — the integration is fully abstracted. | TRD-EXEC-4; HLD §9 |
| The Research Brain has no path to the Execution Engine at all — this component exists only inside the Trading Brain. | HLD §6, §10 |
| The kill switch, once triggered, blocks all new order submission immediately and independent of any other module's state; it does not automatically liquidate positions. | RTLD §16 |
| On unplanned restart, the system must reconcile position/order state against the broker before resuming automated decision-making, and default to a safe state (HOLD/NO TRADE only) if reconciliation cannot be confirmed. | TRD-DR-2/3 |
| Order submission must be idempotent (client-order-ID support) to enable duplicate-order prevention. | TRD-EXEC-2; FRD-EXEC-5 |
| A single build/release of the Trading Brain is what's promoted from Paper to Live — only the execution target (simulated vs. real broker) and configuration differ between environments. | HLD §11 |
| Order submission latency (Supervisor approval → order sent to broker) is proposed at under 2 seconds under normal conditions; this is a placeholder pending operator confirmation. | NFR-PERF-3 |

This EDD converts these constraints into the actual execution mechanics — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:** the order lifecycle state machine; the Broker Adapter Interface's detailed method contract; idempotent order submission and duplicate-prevention mechanics; the translation of a Supervisor decision into concrete order parameters; position/portfolio state tracking and reconciliation; connection-health monitoring and disconnection handling; restart reconciliation mechanics; emergency liquidation design; environment-specific execution behavior (research/paper/live); and the latency budget decomposing NFR-PERF-3's 2-second target across pipeline steps.

**Out of scope (belongs elsewhere):** broker/vendor selection itself (open item, PRD §6.3/TRD-EXEC-6); position-sizing and risk-limit numeric values (RTLD); the kill switch's activation triggers and dependency-isolation design (already fully specified in RTLD §16 and HLD §8 — this EDD only consumes that design, it does not redefine it); backtesting fill simulation (BTD §7, which models execution for the *research* environment only); the AI/agent logic that produces a decision (ADD/MLD); and the API contract's wire format (API Spec).

---

## 4. Order Lifecycle State Machine

Implements FRD-EXEC-3 (order status tracking).

```
                 ┌──────────┐
                 │  PENDING  │  (decision approved, order not yet sent)
                 └─────┬────┘
                       │ submitted to broker (§6)
                       ▼
                 ┌──────────┐
                 │ SUBMITTED │
                 └─────┬────┘
              ┌────────┼────────┬─────────────┐
              ▼        ▼        ▼             ▼
        ┌─────────┐┌────────┐┌──────────┐┌──────────┐
        │ REJECTED ││ FILLED ││ PARTIALLY││ CANCELLED │
        │          ││        ││  FILLED   ││  (by us   │
        │          ││        ││          ││ or broker)│
        └─────────┘└────┬───┘└─────┬────┘└──────────┘
                         │          │ (remainder cancelled
                         │          │  or continues working —
                         │          │  §6.3)
                         ▼          ▼
                   ┌──────────────────┐
                   │ TERMINAL: settled │
                   │ into Position     │
                   │ state (§8)        │
                   └──────────────────┘
```

Every state transition is timestamped and logged (FRD-EXEC-10) as a discrete order-lifecycle event, not inferred after the fact from polling snapshots — this matters for FRD-EVAL-1's decision record, which must be able to show exactly when and how a Supervisor-approved decision became (or failed to become) an actual position.

A `PENDING` order that has not reached `SUBMITTED` within a bounded time (§13) is treated as a submission failure and escalated per §9, not left indefinitely pending.

---

## 5. Broker Adapter Interface — Detailed Contract

Elaborates TRD-EXEC-1/4 and HLD §9's abstraction requirement with the actual method surface every broker implementation must provide, regardless of which broker is eventually selected (PRD §6.3).

| Method | Purpose | Design Notes |
|---|---|---|
| `authenticate()` | Establish/refresh a broker session | Must expose success/failure and session-expiry information distinctly — a silent re-authentication that masks an underlying credential problem is not acceptable (feeds §9's connection-health monitoring). |
| `place_order(order_request)` | Submit a new order | `order_request` includes a client-generated idempotency key (§6.1) — the adapter must pass this through to the broker's native idempotency mechanism where one exists, or implement an equivalent guard itself where the broker has none. |
| `modify_order(order_id, changes)` | Modify a working order | Only valid for orders in `SUBMITTED` or `PARTIALLY_FILLED` state (§4); the adapter rejects a modify request against a terminal-state order rather than silently no-op-ing. |
| `cancel_order(order_id)` | Cancel a working order | Same state validity constraint as `modify_order`. |
| `get_order_status(order_id)` **or** subscribe to a push feed | Query/receive order state | The adapter must support at least polling; a push/streaming feed is preferred where the broker offers one, since it reduces the latency between a fill and the system knowing about it (§12). |
| `get_positions()` | Query current broker-side positions | Used by reconciliation (§10), not trusted as the sole source of truth during normal operation (internal position tracking, §8, is authoritative moment-to-moment; broker-side state is the reconciliation reference). |
| `get_account_state()` | Query available capital/margin | Consumed by the Risk Engine (out of scope here) and by Capital Manager, not redefined by this EDD. |
| `heartbeat()` / connection-health signal | Detect session/connection liveness | Feeds §9's disconnection detection directly. |

This method surface is the internal contract every broker adapter implementation must satisfy — it does not itself select a broker, consistent with TRD-EXEC-6 leaving that selection open.

---

## 6. From Supervisor Decision to Order

### 6.1 Idempotency Key Design

Every order derived from a single Supervisor decision (a single `DecisionRecord`) carries a client-generated idempotency key derived deterministically from that decision's own unique identifier (e.g., the `DecisionRecord` ID itself, or a stable hash of it) — never a freshly random key per submission attempt. This is the mechanism that satisfies FRD-EXEC-5: if a submission times out and the Execution Engine retries, the retry carries the *same* key, so a broker supporting client-order-ID deduplication will reject or recognize the duplicate rather than executing the same decision twice. Where the selected broker has no native idempotency support (TRD-EXEC-2's "directly or via a wrapper"), the Execution Engine maintains its own local idempotency ledger keyed the same way, checked before every submission attempt.

### 6.2 Order Parameter Translation

A Supervisor-approved `BUY`/`SELL` decision (FRD-SUP-3) carries, at minimum: instrument, direction, position size (from the Risk Engine's sizing rule, RTLD-owned, not redefined here), and the timeframe/urgency context. The Execution Engine translates this into concrete broker order parameters:

| Decision Attribute | Order Parameter | Design Note |
|---|---|---|
| Instrument | Broker instrument identifier | Mapped through a static instrument-identifier table maintained alongside the Data Source Adapter's own instrument mapping (HLD §9), so the two never silently drift out of sync. |
| Direction (BUY/SELL) | Order side | Direct mapping. |
| Position size | Order quantity | Taken as-is from the Risk Engine's output — the Execution Engine never independently recalculates or rounds size in a way that changes it beyond what the broker's own lot-size/tick constraints require (and any such adjustment is logged, not silent). |
| Timeframe/urgency | Order type (market vs. limit) | **Proposed default: limit order at a price bounded by a configurable maximum allowable slippage from the decision-time quote**, not a raw market order — this reflects FRD-EXEC-9's correctness-over-speed priority: a market order in a fast-moving or illiquid instrument could fill far from the price the trade was actually evaluated against, silently invalidating the Risk Engine's expected-risk calculation for that trade. A market order is used only where the limit order's price bound would be so wide it provides no real protection (e.g., a highly liquid, tightly-spread instrument) — this threshold is an Execution Parameter Register entry (§13). |

### 6.3 Partial Fill Handling

Where an order is `PARTIALLY_FILLED` (§4), the Execution Engine does not automatically resubmit for the unfilled remainder — per FRD-EXEC-4/FRD-EVAL-1, the position that actually resulted (the filled quantity) is what gets tracked and evaluated; treating a partial fill as if it silently became a full fill would corrupt both position tracking and the trade's later evaluation against its original risk/reward expectation. Whether to resubmit for the remainder is a decision the Supervisor makes fresh, on the next evaluation cycle, informed by the now-partial position — it is not an automatic Execution Engine behavior, consistent with keeping trade decisions (Supervisor's job) and order mechanics (Execution Engine's job) separated.

---

## 7. Order Submission Latency Budget

Elaborates NFR-PERF-3's proposed 2-second target (Supervisor approval → order sent to broker) into a budget across the steps that occur inside that window:

| Step | Proposed Budget | Notes |
|---|---|---|
| Idempotency key generation + local ledger check (§6.1) | < 50 ms | Purely local, no network call. |
| Order parameter translation (§6.2) | < 50 ms | Purely local. |
| Broker authentication check (reuse existing session, no re-auth in the common case) | < 100 ms | A session-expiry re-authentication, if needed, is *not* included in this budget — it is treated as a connection-health event (§9), not routine order-submission latency. |
| Network round-trip: order placement request to broker acknowledgment | < 1,500 ms | The dominant, least-controllable component — bounded by broker infrastructure, not this system's design; monitored (TRD-OBS-4) so a broker whose typical latency exceeds this budget is visible as a systemic issue, not attributed to a code defect. |
| Logging the `SUBMITTED` state transition (§4) | < 300 ms | Must not block on this write completing before returning control to the pipeline (§13's async logging note), but must not be silently dropped either (TRD-OBS-2). |

**Total: ~2,000 ms**, consistent with NFR-PERF-3's placeholder target. If real broker latency (once selected, PRD §6.3) makes this budget unrealistic, that is a signal to revisit NFR-PERF-3 itself, not to quietly let the Execution Engine run over budget unmeasured.

---

## 8. Position and Portfolio State Tracking

Implements FRD-EXEC-4.

- **Source of truth during normal operation**: the Execution Engine's internally maintained position ledger, updated synchronously as order-lifecycle events (§4) are processed — average entry price, quantity, unrealized P&L (marked against current market data), and realized P&L (on closing fills) are all derived from this ledger, not recomputed ad hoc by other modules.
- **Every module that needs position state** (Risk Engine for exposure checks, Capital Manager, Dashboard) reads this ledger through a defined interface (TRD-API-2), never by independently querying the broker directly — this keeps a single, consistent view of "what does the system believe it holds," which is a prerequisite for RTLD's exposure/position-count limits meaning what they claim to mean.
- **Ledger updates are transactional** (TRD-DATA-2): a fill updating a position must not partially apply — e.g., a partial fill's quantity, average price, and any resulting realized-P&L adjustment update together or not at all.

---

## 9. Connection Health and Disconnection Handling

Elaborates FRD-EXEC-6/TRD-EXEC-3 and NFR-REL-4's proposed 30-second reconnection window into an actual sequence.

```
Heartbeat/session-status signal missed or degraded
        │
        ▼
Reconnection attempts begin (immediate, then backoff)
        │
        ├── reconnects within 30s (NFR-REL-4 placeholder) ──► resume normal operation;
        │                                                       log the disconnection event
        │                                                       (duration, cause if known)
        │                                                       regardless of outcome
        ▼ (30s elapses, still disconnected)
Escalate to Risk Engine (FRD-RISK-9) — affected instrument(s), or system-wide
for a full broker-connection loss, suppressed toward NO TRADE / HOLD
        │
        ▼
Human notification (where configured, per FRD-EXEC-6) — Dashboard alert,
consistent with TRD-OBS-4's single-source-of-truth health signal
        │
        ▼
Reconnection attempts continue in the background (do not block the rest
of the Trading Brain pipeline, which continues operating in the
suppressed/safe state for the affected scope)
```

Critically, **new decisions are never made on the assumption that a disconnected broker's last-known state is still accurate** — an instrument (or the whole system, for a full broker outage) suppresses toward NO TRADE/HOLD for the duration of the disconnection, per HLD §14's failure-mode table, which this EDD implements rather than redefines.

---

## 10. Restart Reconciliation

Implements TRD-DR-2/3.

1. On any process restart (planned or unplanned), before the Execution Engine accepts any new Supervisor-approved decision, it queries the broker for current positions and open orders (`get_positions`, `get_order_status`/equivalent, §5).
2. This broker-reported state is compared against the Execution Engine's last-persisted internal ledger (§8) as of the restart.
3. **If they match** (within a defined tolerance for timing artifacts — e.g., an order that filled in the seconds around the restart itself): the internal ledger is confirmed and normal operation resumes.
4. **If they do not match**: the system does not guess which is correct. It logs the discrepancy in full, escalates to human notification, and remains in the safe state (HOLD/NO TRADE only, no new order submission) until either (a) the discrepancy is explained and resolved automatically (e.g., a fill event that arrives late and, once applied, closes the gap), or (b) the operator manually confirms/corrects the state (TRD-DR-3).
5. Only after reconciliation is confirmed does the Execution Engine begin accepting new decisions — this is a hard gate on the startup sequence itself, not an advisory check that logs a warning and proceeds anyway.

---

## 11. Emergency Liquidation

Implements FRD-EXEC-8, consuming RTLD §16's kill-switch specification (not redefining it).

- Liquidation is **not** an automatic consequence of kill-switch activation (RTLD §16: "the kill switch's default effect is 'stop digging,' not 'force-exit'"). It is a distinct, explicit action available to the operator via the Dashboard.
- When invoked, the Execution Engine submits closing orders for all open positions (or a specified subset, if the operator scopes the liquidation) using the same order-parameter translation discipline as §6.2 — including the same limit-order-with-bounded-slippage default, **except** that the operator may explicitly override to a market order for liquidation specifically, since "exit regardless of price" can be a deliberate choice in a genuine emergency in a way it should not be for a routine entry.
- Liquidation orders are logged with the same rigor as any other order (§4), and their outcome (filled, partially filled, rejected) is surfaced back to the operator immediately — a liquidation request that fails to fully execute (e.g., due to a liquidity gap) must be visible as such, not presented as "liquidation complete" when it wasn't.
- Where market conditions genuinely prevent liquidation (FRD-EXEC-8's "where market conditions allow"), the system reports this explicitly rather than silently retrying indefinitely without surfacing the failure.

---

## 12. Environment-Specific Execution Behavior

Elaborates HLD §11's environment topology specifically for the Execution Engine's behavior in each mode.

| Environment | Execution Engine Behavior | Notes |
|---|---|---|
| **Research/Backtest** | Not present/invoked at all — no order-submission code path exists in this mode | Consistent with HLD §11; this EDD's mechanics (§4–§10) simply do not apply here. Fill simulation for this environment is BTD's domain (BTD §7), not this document's. |
| **Paper** | Full order-lifecycle state machine (§4) runs against simulated fills, using real-time market data for pricing | The Broker Adapter Interface (§5) is implemented by a paper-trading adapter that simulates realistic fill behavior (informed by, but distinct from, BTD's historical-replay fill model) — no real order reaches any broker. This is also where the §6.2 limit-order-slippage-bound default should first be calibrated against observed behavior, since paper trading is the first point real-time market microstructure is actually visible to the system. |
| **Live** | Full order-lifecycle state machine (§4) runs against the real Broker Adapter implementation, with live credentials | Everything in §5–§11 applies at full force; this is the only environment where §9's escalation and §10's reconciliation carry real capital consequences. |

Per HLD §11, the *same* Execution Engine code runs in Paper and Live — only the Broker Adapter implementation (simulated vs. real) and credentials differ, which is what makes this EDD's design (order lifecycle, idempotency, reconciliation) something paper trading actually validates, rather than something tested for the first time at V5.

---

## 13. Execution Parameter Register

All entries are **Proposed — pending operator sign-off**, consistent with RTLD §14, BTD §6, MLD §11, and SLD §10.

| Parameter | Proposed Value | Section |
|---|---|---|
| `PENDING`-to-`SUBMITTED` timeout before escalation | 5 seconds | §4 |
| Default order type | Limit, bounded by max allowable slippage from decision-time quote | §6.2 |
| Max allowable slippage bound for limit-order default | TBD — depends on instrument liquidity, pending broker/instrument selection (PRD §6.3) | §6.2 |
| Market-order fallback threshold (when limit bound provides "no real protection") | TBD — depends on typical spread of selected instrument(s) | §6.2 |
| Order submission latency budget (total) | ~2,000 ms, decomposed per §7 | §7 |
| Reconnection window before Risk Engine escalation | 30 seconds (carried from NFR-REL-4 placeholder) | §9 |
| Reconciliation state-match tolerance window | TBD — small, to absorb timing artifacts around restart moment | §10 |

The two liquidity-dependent TBD values above cannot be finalized before broker/instrument selection resolves (PRD §6.3, TRD-EXEC-6) — this mirrors RTLD §18 item 2's identical dependency for the liquidity-impact threshold, and both should be resolved together once that selection is made.

---

## 14. Traceability

| EDD Section | Source Requirement(s) |
|---|---|
| §4 Order lifecycle | FRD-EXEC-2, 3, 10 |
| §5 Broker Adapter Interface | TRD-EXEC-1, 2, 4; HLD §9 |
| §6 Decision-to-order translation | FRD-EXEC-2, 5, 9 |
| §7 Latency budget | NFR-PERF-3 |
| §8 Position/portfolio tracking | FRD-EXEC-4; TRD-DATA-2 |
| §9 Connection health | FRD-EXEC-6; TRD-EXEC-3; NFR-REL-4 |
| §10 Restart reconciliation | FRD-EXEC-7; TRD-DR-2/3 |
| §11 Emergency liquidation | FRD-EXEC-8; RTLD §16 |
| §12 Environment-specific behavior | HLD §11 |

Every parameter in §13 should be entered into the Requirements Traceability Matrix alongside its FRD/TRD/NFR lineage.

---

## 15. Open Items Requiring Operator or Downstream Decision

1. **Broker selection** (PRD §6.3, carried through TRD-EXEC-6) — blocks finalizing §5's adapter implementation and §13's liquidity-dependent parameters.
2. **Max allowable slippage bound and market-order fallback threshold** (§6.2, §13) — depend on the selected instrument's typical liquidity; cannot be set from first principles alone.
3. **NFR-PERF-3's 2-second target itself** — §7's budget shows it is achievable only if broker round-trip latency stays under ~1.5 seconds; this should be validated against the actual selected broker's typical latency, not assumed.
4. **Whether limit-order default should have a maximum wait time before auto-cancelling** (e.g., a limit order that never fills) — not addressed above; needs a defined policy (auto-cancel-and-re-evaluate vs. leave working) before V5.

---

## 16. Document Governance

This EDD is a living document and must be reviewed whenever:
- Broker selection (§15 item 1) resolves, to finalize §5's adapter contract implementation and §13's liquidity-dependent parameters.
- Paper trading (V4) produces real fill/latency data, to calibrate §6.2's slippage bound and validate §7's latency budget against reality.
- RTLD §16's kill-switch specification changes in a way that affects §11's liquidation design.
- HLD §11's environment topology changes in a way that affects §12.

**Next recommended step:** the operator reviews open item 4 (limit-order timeout policy) since it's the one gap in this design not already tied to the broker-selection dependency; broker/instrument selection (PRD §6.3) remains the single highest-leverage open item blocking this EDD's remaining TBD values.