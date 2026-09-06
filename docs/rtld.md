# Risk & Trading Logic Design (RTLD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Risk & Trading Logic Design (RTLD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from BRD v0.1, PRD v0.1, FRD v0.1, NFRD v0.1, SOW v0.1, TRD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, BRD v0.1, FRD v0.1, NFRD v0.1 |

---

## 1. Purpose of This Document

The PRD, BRD, FRD, and NFRD all defer the *actual numeric risk limits and trading-logic mechanics* to this document, by design (PRD §9, FRD-RISK-14, FRD-CAP-6, NFRD §14). This RTLD is where those numbers and mechanics are formally derived and specified: the deterministic risk engine's rules (FRD Module 6), the decision state machine (FRD Module 5/7), position sizing, capital-scaling thresholds (FRD Module 12), and the kill-switch/STOP behavior (FRD-RISK-12, NFRD-SAFE-2/3).

Consistent with the project's engineering principle of not silently inventing critical requirements, every numeric value below is presented as a **derived, reasoned proposal**, not a silently finalized fact. Each is explicitly flagged **Proposed — pending operator sign-off** in the Numeric Parameter Register (§14). Nothing in this document may be treated as authorizing live trading until the operator has reviewed and accepted (or amended) these values, and until the BRD/PRD/SOW preconditions for V5 are otherwise satisfied.

This RTLD binds downstream design (HLD, LLD, Execution Design, Test Strategy): any implementation of Module 6 (Risk Engine), Module 7 (Supervisor), Module 11 (kill switch/STOP), or Module 12 (Capital & Growth Management) must conform to the rules and precedence defined here.

---

## 2. Governing Principles (Carried Forward, Not Reopened)

These are settled upstream and are inputs to, not outputs of, this document:

| Principle | Source |
|---|---|
| Capital preservation precedes return generation whenever they conflict. | BRD BR-1 |
| ₹1,000 is a stated *extreme-case tolerance ceiling*, not a routine target or a permission to intentionally risk that amount. | PRD §9 |
| Hard risk limits and kill-switch logic must be deterministic, independent of any AI/LLM/probabilistic component, and unable to be overridden by one. | BRD BR-4; FRD-RISK-11; NFRD-SAFE-1 |
| NO TRADE is a first-class, legitimate outcome and must never be discouraged by tuning or evaluation pressure. | BRD BR-3; PRD FR-8 |
| Capital may only scale via predefined, documented, previously agreed criteria; the system may never decide to scale its own capital. | BRD BR-2; FRD-CAP-2 |
| No unvalidated model may touch live capital. | BRD BR-6; FRD-X-4 |
| The operator retains an immediate, AI-independent manual override at all times. | BRD BR-5; FRD-DASH-7 |

This RTLD's job is to convert these qualitative principles into deterministic, testable rules and numbers — not to revisit whether they hold.

---

## 3. Scope of This Document

**In scope:**
- Numeric derivation of every risk limit referenced in FRD-RISK-1 through FRD-RISK-14.
- Position-sizing formula and worked examples.
- The BUY/SELL/HOLD/NO TRADE decision logic and the precedence order in which the Risk Engine and Supervisor evaluate constraints.
- Kill-switch and manual STOP behavioral specification.
- Capital-scaling, capital-decrease, halt, and withdrawal criteria (FRD-CAP-2, FRD-CAP-6), to the extent the operator's open policy questions (BRD §11) allow.
- A consolidated, versionable configuration register of every numeric parameter, each flagged for operator sign-off.

**Out of scope (belongs to other documents):**
- Broker/execution mechanics (order types, retry logic) — Execution Design.
- Signal-generation/agent internals and the aggregation/scoring algorithm's model details — HLD/LLD, ML Design.
- Backtesting cost/friction modeling mechanics — Backtesting Design (values here assume that modeling exists and is realistic, per FR-25/26).
- Regulatory/compliance review of algorithmic trading rules — separate compliance workstream (BRD BR-9), a precondition for V5 independent of this RTLD.
- Final broker/instrument selection — still an open item (PRD §6.3); where a rule depends on it, this is flagged.

---

## 4. Capital Base and Risk Budget

| Item | Value | Basis |
|---|---|---|
| **Initial live trading capital** | ₹10,000 | PRD §9; BRD §8 |
| **Extreme-case tolerance ceiling** | ₹1,000 (10% of capital) | PRD §9 — explicitly a ceiling, not a target |
| **Design principle** | Every hard-halt limit in this RTLD is set **below** the ₹1,000 ceiling, so the ceiling is never intentionally approached in normal operation — it is a last-resort backstop, not a working assumption. | PRD §9 |

All percentage-based limits below are computed against **current allocated live trading capital** (FRD-CAP-1), which starts at ₹10,000 and only changes via the mechanisms in §12/§13 — never through unrealized P&L alone. This avoids limits silently loosening on a winning streak or tightening in a way that isn't auditable.

---

## 5. Per-Trade Risk Limit (FRD-RISK-3)

**Rule:** No single trade may be sized such that a full stop-loss exit would lose more than a fixed fraction of current capital, regardless of any agent's confidence score.

| Parameter | Proposed Value | Rationale |
|---|---|---|
| **Max risk per trade** | **1% of current capital** (₹100 at ₹10,000) | At this scale, 1% allows roughly 8–10 consecutive full losses before the 8% drawdown halt (§7) is reached — enough to avoid a single bad trade or short losing streak forcing a halt, while keeping any one trade's damage small relative to the ₹1,000 ceiling. |

**Enforcement:** every candidate trade must carry a predefined stop-loss price at the point the Risk Engine evaluates it (FRD-RISK-1/2). A trade without a defined, distance-computable stop is rejected outright — "risk unknown" is treated the same as "risk too high," never approved by default.

---

## 6. Position Sizing (FRD-RISK-2, FR-10)

**Method:** fixed-fractional sizing, driven by the per-trade risk limit and the trade's stop distance — deterministic and fully auditable, per FRD-RISK-2's requirement.

**Formula:**

```
Risk_Amount (₹)     = Current_Capital × Max_Risk_Per_Trade_Pct
Stop_Distance (₹/unit) = |Entry_Price − Stop_Price|
Raw_Quantity        = floor( Risk_Amount / Stop_Distance )
Position_Value (₹)  = Raw_Quantity × Entry_Price

Final_Quantity = min(
    Raw_Quantity,
    floor(Max_Position_Value_₹ / Entry_Price),        # §8 cap
    floor(Exposure_Headroom_₹ / Entry_Price)           # §8 cap
)
```

Where `Exposure_Headroom_₹ = Max_Portfolio_Exposure_₹ − Currently_Deployed_₹`.

**Worked example** (at ₹10,000 capital, defaults from §5/§8):
- Risk_Amount = ₹10,000 × 1% = ₹100
- Entry = ₹250, Stop = ₹240 → Stop_Distance = ₹10
- Raw_Quantity = floor(100 / 10) = 10 shares → Position_Value = ₹2,500
- Max_Position_Value cap (§8) = ₹2,000 → binding constraint
- **Final_Quantity = floor(2,000 / 250) = 8 shares** (Position_Value = ₹2,000; actual risk at stop = 8 × ₹10 = ₹80, i.e., 0.8% of capital — under budget because the position-size cap bound before the risk cap did)

This illustrates why **all** caps in §7–§11 must be evaluated together, not just the per-trade risk limit in isolation — the tightest constraint governs.

**If `Raw_Quantity` computes to 0** (i.e., the risk budget cannot buy even one unit at the given stop distance), the trade is rejected as un-sizeable, not rounded up — rounding up would silently exceed the per-trade risk limit.

---

## 7. Maximum Daily Loss Limit (FRD-RISK-4)

| Parameter | Proposed Value | Rationale |
|---|---|---|
| **Max daily loss** | **3% of capital at start of session** (₹300 at ₹10,000) | Roughly 3× the per-trade risk limit — tight enough to stop a genuinely bad day well before it threatens the drawdown/kill-switch tiers, loose enough not to halt trading on an ordinary run of 2–3 losing trades. |

**Behavior on breach:** all new trade entries are blocked for the remainder of the trading day/session (FRD-RISK-4). Existing open positions are **not** force-closed by this limit alone (that is the drawdown/kill-switch tier's job, §9) — they continue to be managed (stops, exits) under existing rules. Blocking resets automatically at the start of the next session; it does not require operator action (distinguishing it from the drawdown halt in §8, which does).

---

## 8. Maximum Drawdown Limit (FRD-RISK-5)

**Definition:** drawdown is measured peak-to-trough on **total account equity** (realized + mark-to-market unrealized), not on realized P&L alone, so open losing positions count toward the limit in real time.

| Tier | Threshold | Behavior |
|---|---|---|
| **Hard drawdown halt** | **8% of capital from peak equity** (₹800) | All new trade entries blocked; the system does **not** resume automatically — it requires explicit operator action to resume (FRD-RISK-5). Open positions continue to be managed per existing exit rules unless the operator separately invokes emergency liquidation (§11). |
| **Extreme-loss circuit breaker (kill switch trigger)** | **10% of capital from peak equity** (₹1,000 — the PRD's stated ceiling) | Automatically invokes the kill switch (§11): immediate block on all new orders, and the system flags open positions for operator decision. This tier exists so the stated ceiling is a hard, automatic backstop, never a target the strategy logic is allowed to approach as "acceptable." |

The 8%/10% two-tier design gives the operator a 2-percentage-point (₹200) buffer between "trading is paused, come look at this" and "the absolute stated tolerance has been touched." This buffer is itself a proposed design choice, not derived from any source document, and should be explicitly confirmed or adjusted by the operator.

---

## 9. Maximum Exposure, Position Size, and Simultaneous Positions (FRD-RISK-6, FRD-RISK-7)

| Parameter | Proposed Value | Rationale |
|---|---|---|
| **Max portfolio exposure** | **50% of capital deployed at any time** (₹5,000) | At ₹10,000-scale with a single-operator, conservative early posture (V5), keeping at least half of capital uncommitted preserves flexibility to react and avoids the whole account being simultaneously at risk to a correlated market move. |
| **Max single position size** | **20% of capital** (₹2,000) | Prevents any one instrument/position from dominating the account; also caps single-name concentration risk independent of the per-trade stop-loss risk cap in §5. |
| **Max simultaneous open positions** | **3** | Keeps the position count small enough to be manually reviewable on the dashboard (PRD FR-30) and consistent with a non-HFT, correctness-over-speed posture (NFR-PERF-1). |
| **Max trades per trading day** | **5** | Guards against inadvertent overtrading/churn, which would erode capital through costs/slippage even without any single trade breaching other limits (FRD-RISK-7). |

All four apply simultaneously; a candidate trade is blocked if it would breach **any** of them, independent of the others.

---

## 10. Consecutive-Loss Protection (FRD-RISK-8)

| Tier | Trigger | Response |
|---|---|---|
| **Tier 1 — size reduction** | 3 consecutive losing trades (same session or rolling, per §14 config) | Per-trade risk (§5) is reduced by 50% (i.e., 0.5% of capital) for subsequent trades until a winning trade resets the counter. |
| **Tier 2 — session pause** | 5 consecutive losing trades | New entries blocked for the remainder of the session, independent of whether the daily loss limit (§7) has itself been breached in ₹ terms — this catches a string of small losses that individually stay under the ₹ limit but collectively signal something is off (regime mismatch, model degradation). |

This is a behavioral circuit breaker distinct from the ₹-denominated daily loss limit: it responds to a *pattern* (losing streak), not just a *magnitude* (₹ lost), consistent with FRD-RISK-8's framing.

---

## 11. Volatility, Liquidity, Abnormal-Market, and Broker/Data-Failure Protection (FRD-RISK-9)

| Condition | Proposed Rule |
|---|---|
| **Abnormal volatility** | If an instrument's short-term volatility (e.g., realized vol or ATR over the active timeframe) exceeds **2× its trailing 20-session average**, position size for that instrument is halved; if it exceeds **3×**, no new entries are approved for that instrument until volatility normalizes. |
| **Insufficient liquidity** | If the position size computed in §6 would represent more than a configurable share of average traded volume/depth for the instrument (exact threshold instrument/broker-dependent — open item, see §15), the trade is blocked or resized down to a liquidity-safe quantity. |
| **Stale/missing data** | Per FRD-DATA-9: if critical data for an instrument is stale or missing beyond the staleness threshold (to be confirmed with NFR-DATA-1), new decisions for that instrument are suppressed — this surfaces as a forced NO TRADE, not a silent skip. |
| **Detected exchange-level abnormal conditions** (e.g., circuit filters, trading halts on the instrument) | Forced NO TRADE / HOLD for that instrument for the duration of the condition. |
| **Broker/API disconnection or failure** | Per NFR-REL-4: after the reconnection window (proposed 30 seconds) elapses without recovery, new order submission is blocked and the event is escalated to the Risk Engine and to operator notification (FRD-EXEC-6). Existing open positions are not assumed filled/unfilled — status must be reconciled on reconnection before any further action, never assumed. |

These are evaluated per-instrument, so a failure condition on one instrument does not necessarily block trading on others unless it is a system-wide condition (e.g., broker disconnection, which is system-wide by nature).

---

## 12. Minimum Model-Confidence Threshold (FRD-RISK-10)

| Parameter | Proposed Value | Rationale |
|---|---|---|
| **Minimum confidence to approve a trade** | **60% on the system's defined confidence/trade-quality scale (0–100)** | A trade with a below-threshold confidence score is rejected regardless of computed expected value or trade-quality score elsewhere in the pipeline — confidence is a gate, not merely an input to be averaged away by other high-scoring factors. |

This threshold is a placeholder in the fullest sense: unlike the ₹-denominated limits above (which are derived directly from the ₹10,000/₹1,000 figures already fixed upstream), this one depends entirely on how Module 4/5's confidence scoring is ultimately implemented (HLD-level decision, not yet made). It is included here to establish that such a gate **must exist and be enforced deterministically outside the AI's discretion** (FRD-RISK-11) — the exact number should be revisited once the scoring methodology is designed and back-tested.

---

## 13. Decision Logic: BUY / SELL / HOLD / NO TRADE

### 13.1 Pipeline and Evaluation Order

Per FRD §9 and FRD-X-1, every evaluation cycle proceeds in a fixed, auditable order. Each stage can only narrow or block the outcome of the prior stage — no later stage can grant authority a hard rule already removed:

1. **Data validation** — if critical data is stale/missing (§11), forced **NO TRADE** for the affected instrument; pipeline does not proceed further for it.
2. **Regime detection** — classifies current conditions; feeds all downstream stages but does not itself block/approve.
3. **Signal generation & aggregation** — produces a candidate opportunity, expected value, and trade-quality/confidence score.
4. **Confidence gate (§12)** — below threshold → **NO TRADE**, pipeline stops.
5. **Expected-value gate** — non-positive expected value after realistic cost/friction assumptions (per FR-25 methodology) → **NO TRADE**.
6. **Position sizing (§6)** — computes size under all caps (§5, §9); a size of 0 → **NO TRADE**.
7. **Risk Engine hard-limit evaluation (§5–§12)** — evaluated as an all-must-pass checklist, not weighted or averaged; **any single breach blocks the trade**, independent of how favorable other factors are (FRD-RISK-11, NFRD-SAFE-4). Order of checks within this stage does not matter functionally (all must pass), but for diagnostic logging purposes, checks are evaluated in this order: kill switch/STOP state → daily loss limit → drawdown tier → exposure/position/simultaneous-position caps → consecutive-loss tier → per-trade risk/sizing → volatility/liquidity/abnormal-market → model-confidence.
8. **Supervisor gate** — consults the Risk Engine result (FRD-SUP-2); cannot approve anything the Risk Engine has blocked (FRD-SUP-6); if the kill switch or manual STOP is active, Supervisor output is constrained to HOLD or exit-only regardless of upstream recommendation (FRD-SUP-5).
9. **Final decision** — one of exactly four outcomes: **BUY, SELL, HOLD, NO TRADE**. HOLD applies to open positions where no action is warranted; NO TRADE applies where no new position is warranted. Both are logged identically to BUY/SELL in the decision record (FRD-EVAL-1) — there is no "no decision" state.

### 13.2 NO TRADE Triggers (Non-Exhaustive, Illustrative)

NO TRADE is the default outcome unless every gate above is explicitly passed. Concretely, NO TRADE results from (among others): stale/missing data, confidence below threshold, non-positive expected value, un-sizeable position, any hard risk-limit breach, abnormal volatility/liquidity/market condition, active kill switch/STOP, or exchange-level halt on the instrument. Per BRD BR-3, none of these triggers may be tuned away to increase trade frequency — a high NO TRADE rate is not itself evidence of a problem.

---

## 14. Numeric Parameter Register

All values below are **proposed defaults derived in this RTLD** and must be explicitly confirmed, adjusted, or rejected by the operator before V5 (live capital) begins, per BRD BR-8/§9 and SOW §6.6/§9. None should be treated as final by silent acceptance.

| ID | Parameter | Proposed Value | Section | Status |
|---|---|---|---|---|
| RTLD-1 | Initial live capital | ₹10,000 | §4 | Fixed (PRD §9) |
| RTLD-2 | Extreme-case tolerance ceiling | ₹1,000 (10%) | §4 | Fixed (PRD §9) |
| RTLD-3 | Max risk per trade | 1% of capital (₹100) | §5 | ☐ Pending operator sign-off |
| RTLD-4 | Max daily loss | 3% of capital (₹300) | §7 | ☐ Pending operator sign-off |
| RTLD-5 | Hard drawdown halt (manual resume required) | 8% of capital (₹800) | §8 | ☐ Pending operator sign-off |
| RTLD-6 | Extreme-loss circuit breaker / kill-switch trigger | 10% of capital (₹1,000) | §8 | ☐ Pending operator sign-off |
| RTLD-7 | Max portfolio exposure | 50% of capital (₹5,000) | §9 | ☐ Pending operator sign-off |
| RTLD-8 | Max single position size | 20% of capital (₹2,000) | §9 | ☐ Pending operator sign-off |
| RTLD-9 | Max simultaneous open positions | 3 | §9 | ☐ Pending operator sign-off |
| RTLD-10 | Max trades per day | 5 | §9 | ☐ Pending operator sign-off |
| RTLD-11 | Consecutive-loss size reduction trigger | 3 losses → −50% size | §10 | ☐ Pending operator sign-off |
| RTLD-12 | Consecutive-loss session-pause trigger | 5 losses → pause session | §10 | ☐ Pending operator sign-off |
| RTLD-13 | Abnormal-volatility size reduction | >2× 20-session avg → −50% size | §11 | ☐ Pending operator sign-off |
| RTLD-14 | Abnormal-volatility block | >3× 20-session avg → no new entries | §11 | ☐ Pending operator sign-off |
| RTLD-15 | Broker reconnection window before escalation | 30 seconds | §11 (= NFR-REL-4) | ☐ Pending operator sign-off (shared with NFRD) |
| RTLD-16 | Minimum model-confidence threshold | 60 / 100 | §12 | ☐ Pending — also depends on HLD scoring design |
| RTLD-17 | Kill-switch/STOP activation time | <2 seconds | §16 (= NFR-SAFE-3) | ☐ Pending operator sign-off (shared with NFRD) |
| RTLD-18 | Liquidity impact threshold | Not yet set | §11 | ☐ Open — depends on broker/instrument selection (§15) |
| RTLD-19 | Data staleness threshold | Not yet set | §11 | ☐ Open — pending NFR-DATA-1 confirmation |

All RTLD-* values must be implemented as **externalized configuration** (NFR-MAINT-3), never hardcoded, so they can be tuned by the operator without a code change/redeploy, and every change to any value in this table must itself be logged (traceable to who/when/why changed) consistent with BR-7's full-auditability requirement.

---

## 15. Capital Scaling Criteria (FRD-CAP-2, FRD-CAP-6)

Per BRD BR-2, capital may only increase when **all** predefined criteria below are satisfied and the operator explicitly approves the change (FRD-CAP-3) — the system evaluates and reports against these criteria; it never actuates a capital increase itself (FRD-X-4-adjacent logic extended to Module 12).

| Criterion | Proposed Threshold | Notes |
|---|---|---|
| **Minimum sample size** | ≥30 closed live trades, over a minimum 3-month live evaluation window | 30 trades is a commonly used floor for basic statistical relevance; the time floor prevents a lucky short burst from qualifying. |
| **Consistency** | Positive expectancy demonstrated across at least 2 distinct market regimes (per Module 3 regime classification) | Prevents scaling on a result that only worked in one favorable regime. |
| **Drawdown adherence** | Zero breaches of the hard drawdown halt (RTLD-5, 8%) during the evaluation window | Directly enforces BO-1/BO-5 as a scaling gate, not just a live-trading gate. |
| **Risk-adjusted return** | Sortino ratio ≥ 1.0 over the evaluation window (placeholder — see note) | Sortino preferred over Sharpe here since it penalizes only downside volatility, aligning with the capital-preservation-first philosophy (PRD §9). |
| **Robustness** | Underlying strategy/model has passed out-of-sample, walk-forward, stress, and Monte Carlo testing per FR-27, with no material degradation versus in-sample results | Guards against backtest overfitting (a named program risk, PRD §15). |
| **Live/paper performance divergence** | Live results within a defined tolerance band of what paper trading predicted (band not yet set — open item) | Detects execution-quality or model-degradation issues invisible in paper trading alone. |
| **Model stability** | Zero automatic rollback events (FR-23) during the evaluation window | A rollback during the window resets the clock on this criterion. |
| **Execution quality** | Realized slippage within expected bounds from backtest assumptions; zero duplicate-order incidents (target from PRD §10) | |
| **Operational reliability** | Uptime and connectivity failure rate meeting whatever NFR-REL targets are ultimately confirmed | Ties this criterion to the NFRD rather than inventing a separate number here. |

**Capital increase mechanics (proposed, pending operator confirmation):** when all criteria are met, the system generates a scaling recommendation with supporting evidence (FRD-CAP-4) but takes no action; the operator separately approves a step increase, proposed at **+25% of current live capital per approved event** (e.g., ₹10,000 → ₹12,500), rather than an unbounded jump, so that BR-8's incremental-exposure principle applies to capital scaling itself, not only to the V0–V8 roadmap.

**Capital decrease / halt:** triggered automatically by the drawdown/kill-switch tiers (§8) or the consecutive-loss session pause (§10), or manually by the operator at any time (BR-5). None of these require the scaling-criteria evaluation above — they are safety actions, not scaling decisions, and take effect immediately.

**Withdrawal policy:** explicitly **not defined** in this RTLD — this remains an open business decision (BRD §11 item 4 / PRD §16 item 4). This document does not silently assume "reinvest everything" or "withdraw periodically"; whichever policy the operator chooses should itself get predefined, documented rules before implementation, in the same spirit as BR-2.

---

## 16. Kill Switch and Manual STOP Specification (FRD-RISK-12, FRD-DASH-7)

| Property | Specification |
|---|---|
| **Activation triggers** | (a) Operator manually invokes STOP from the dashboard (FRD-DASH-7); (b) automatic activation when the extreme-loss circuit breaker (RTLD-6, 10% drawdown) fires; (c) any condition the Risk Engine design later designates as auto-triggering (to be confirmed at HLD). |
| **Effect** | Immediately blocks all new order submission, independent of any other module's state (FRD-RISK-12; FRD-X-5) — this takes precedence over an in-flight Supervisor decision. |
| **Dependency profile** | Must execute on a dedicated, minimal-dependency code path such that a crashed agent, slow model call, or degraded upstream module cannot prevent it from taking effect (NFR-SAFE-2; TRD-ARCH-3). |
| **Timing** | Proposed target: under 2 seconds from trigger to "no new orders will be submitted" state (NFR-SAFE-3), independent of market conditions for the halt-new-entries mode. |
| **Position handling** | Halting new entries does **not** automatically liquidate open positions — liquidation is a separate, explicit action (FRD-EXEC-8), available to the operator, and used where market conditions allow. The kill switch's default effect is "stop digging," not "force-exit," since a forced exit under abnormal conditions (e.g., a liquidity event) could itself realize unnecessary loss. |
| **Reset** | Requires explicit operator action to resume trading — never automatic, regardless of trigger source (consistent with FRD-RISK-5's drawdown-halt behavior). |
| **Testing requirement** | Must be demonstrated to block a disallowed action even when all upstream agents/models recommend it, proving independence (NFR-SAFE-4); this test is part of V5 acceptance (SOW §6.6) and must be re-run on every change to the Risk Engine or kill-switch code path. |

---

## 17. Interaction With the Model Promotion Pipeline

This RTLD's hard limits apply identically regardless of which model version is currently live — a newly promoted model inherits the same risk configuration; it does not get a "grace period" with looser limits, nor does it need special risk parameters to be promoted (per FR-23/BR-6, promotion is about *decision quality*, not about earning looser risk treatment). If a future validated strategy specifically requires different risk parameters (e.g., a different timeframe with different volatility characteristics), that requires an explicit, documented change to this RTLD's Numeric Parameter Register (§14) — never an implicit override embedded in the new model.

---

## 18. Open Items Requiring Operator Decision Before This RTLD Can Be Finalized

1. **Confirm or adjust every "Pending operator sign-off" row in §14** — this RTLD proposes defaults; none should be silently accepted.
2. **Liquidity-impact threshold (RTLD-18)** — cannot be finally set until broker/instrument selection (PRD §6.3) resolves, since it depends on available depth/volume data.
3. **Data staleness threshold (RTLD-19)** — depends on NFR-DATA-1 being confirmed in the NFRD.
4. **Confidence-threshold methodology (RTLD-16)** — the 60/100 figure is a structural placeholder; the actual scoring scale is an HLD-level design decision not yet made.
5. **Live/paper divergence tolerance band (§15)** — not yet quantified; needed before the capital-scaling criteria can be operationalized.
6. **Level of human sign-off per model promotion** — carried from BRD §11 item 6; affects whether §17's "promotion never changes risk parameters implicitly" rule needs an additional explicit-approval step.
7. **Position-count vs. dashboard reviewability assumption (§9, RTLD-9)** — the "3 simultaneous positions" figure assumes manual reviewability matters at this stage; confirm this is still desired once the dashboard (Module 11) design is further along.
8. **Rolling vs. session-based consecutive-loss counting (§10)** — whether the streak counter resets each session or persists across sessions is not yet decided; affects RTLD-11/12 behavior at session boundaries.

---

## 19. Traceability

| RTLD Section | Source Requirement(s) |
|---|---|
| §5 Per-trade risk | PRD FR-9/FR-11; FRD-RISK-1, FRD-RISK-3 |
| §6 Position sizing | PRD FR-10; FRD-RISK-2 |
| §7 Daily loss limit | FRD-RISK-4 |
| §8 Drawdown / kill-switch trigger | FRD-RISK-5; PRD §9 (₹1,000 ceiling) |
| §9 Exposure / position / trade-count caps | FRD-RISK-6, FRD-RISK-7 |
| §10 Consecutive-loss protection | FRD-RISK-8 |
| §11 Volatility/liquidity/abnormal-market/broker-failure | FRD-RISK-9; FRD-DATA-9; NFR-REL-4 |
| §12 Model-confidence threshold | FRD-RISK-10 |
| §13 Decision logic | PRD FR-5–FR-8; FRD Module 5 (Aggregation), Module 7 (Supervisor); FRD-SUP-2, FRD-SUP-5, FRD-SUP-6; FRD-X-1 |
| §14 Parameter register | FRD-RISK-14; NFR-MAINT-3 |
| §15 Capital scaling | BRD BR-2; FRD-CAP-2, FRD-CAP-6 |
| §16 Kill switch / STOP | FRD-RISK-12; FRD-DASH-7; FRD-X-5; NFR-SAFE-2/3/4 |
| §17 Promotion interaction | FRD-LEARN-5; BRD BR-6 |
| §18 Open items | BRD §11; PRD §16; NFRD §14/§15 |

Every hard limit implemented in code (Module 6 Risk Engine, Module 7 Supervisor, Module 11 kill switch, Module 12 Capital Management) must cite the relevant RTLD-* parameter ID from §14 in its configuration and in decision-record logging, so that an audit (BR-7) can show not just *that* a limit was applied but *which version of this RTLD's numbers* was in force at the time.

---

## 20. Document Governance

This RTLD is a living document and must be reviewed whenever:
- Any value in the Numeric Parameter Register (§14) is proposed to change.
- Capital is scaled up or down (§15), since limits are computed against current capital.
- Broker/instrument selection is finalized (resolves §18 items 2–3).
- A new market/timeframe/instrument class is added, since volatility/liquidity assumptions (§11) may not transfer.
- Any V5+ acceptance test (SOW §6.6, NFR-SAFE-4) reveals a limit does not behave as specified here.

**Next recommended step:** the operator reviews and formally signs off on §14 (or returns specific line items for revision), in parallel with resolving the open items in §18; only then should HLD/LLD work on Modules 6, 7, 11, and 12 proceed to implementation, per BRD BR-8's incremental-exposure principle.
