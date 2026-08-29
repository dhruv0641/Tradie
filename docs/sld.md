# Self-Learning Design Document (SLD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Self-Learning Design Document (SLD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD, BRD, FRD, NFRD, SOW, RTLD, BTD, ADD, MLD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader FRD v0.1 (Modules 9, 10), SOW v0.1 (§6.7–§6.8, V6–V7), ADD v0.1 (§8, §10), MLD v0.1 (§9–§10) |

---

## 1. Purpose of This Document

ADD §8 defined the model lifecycle *state machine* (candidate → validated → promoted → monitored → rolled back) and ADD §10 sketched the Learning Pipeline's internal stages at a component level. MLD §9–§10 then defined the *numeric* promotion threshold and overfitting guardrails those stages check against. What none of those documents specify is the **process** that actually closes the loop: how a completed trade becomes a lesson, how a lesson becomes a hypothesis, how a hypothesis becomes a candidate worth spending validation effort on, how the system decides *when* to look for lessons at all, and how continuous monitoring after promotion actually detects degradation in practice rather than in principle.

This is exactly the V6 ("Self-Learning Trader") and V7 ("Adaptive Autonomous Trader") scope named in SOW §6.7–§6.8: the post-trade evaluation pipeline, the candidate-generation workflow, and the automated-rollback mechanism, treated as an end-to-end operational loop rather than as isolated components. This SLD is that operational design — it does not redefine the lifecycle states (ADD §8), the promotion math (MLD §9), or the validation pipeline stages (ADD §8.2/MLD), all of which it treats as fixed inputs.

Consistent with the project's engineering principle of not silently inventing critical requirements, every cadence and threshold below is a **derived, reasoned proposal**, flagged **Proposed — pending operator sign-off** in the Self-Learning Parameter Register (§10).

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| The Research Brain has no functional pathway to live execution or capital allocation; it only ever proposes a promotion, never actuates one. | FRD-X-4; ADD §10 |
| A candidate must pass backtest → out-of-sample → walk-forward → stress → robustness → paper trading, in that order, before production consideration. | FRD-LEARN-3; ADD §8.2 |
| All promotion criteria (Sharpe, drawdown, walk-forward efficiency, sample size, robustness) must hold simultaneously; none is optimized in isolation. | MLD §9.2 |
| A deployed model's live/paper performance is continuously compared against its validated expected performance, with automatic rollback on defined degradation. | FRD-LEARN-7; ADD §8.4 |
| Every promotion, rejection, and rollback event is logged with the evidence/metrics that drove it. | FRD-LEARN-8 |
| Candidate generation is informed by Module 9's trade-evaluation variance-driver classification, not an undirected search. | FRD-LEARN-2; ADD §10 |
| Reinforcement learning, where used, trains only in a sandboxed environment and its reward function is never raw profit alone. | FRD-LEARN-9; ADD §11 |
| NO TRADE is a first-class outcome; the self-learning loop must never create pressure toward trading more often as an implicit objective. | BRD BR-3; PRD FR-8 |
| Avoid unnecessary complexity — no self-learning mechanism should be more elaborate than a single-operator, ₹10,000-scale project currently justifies. | TRD Guiding Principle 7 |

This SLD converts these constraints into an operational loop — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:** the trade-evaluation-to-lesson pipeline (extending FRD Module 9's variance-driver classification into a pattern-detection process); the hypothesis-to-candidate generation workflow (Module 10 entry point); the operational cadence governing when evaluation, candidate generation, and monitoring actually run; the statistical mechanics of post-promotion degradation detection (elaborating FRD-LEARN-7 into an actual test, not just a stated requirement); self-learning-specific safety guardrails (rate limiting, cooldown periods, human-review triggers) that prevent the loop itself from becoming a source of instability; and failure modes of the loop as a system, distinct from failure modes of any individual model.

**Out of scope (belongs elsewhere):** the lifecycle state machine and promotion handoff mechanics (ADD §8, §12); the validation pipeline's internal stage definitions (ADD §8.2); feature engineering, regime taxonomy, per-agent formulas, and the promotion-threshold formula itself (MLD §4–§9); backtesting cost/friction modeling (BTD); hard risk-limit numeric values (RTLD); and specific ML/DL framework or scheduling-technology selection (TTD/ADRs).

---

## 4. The Self-Learning Loop — Overview

```
 [Live/Paper Trading Brain]
        │  every completed trade
        ▼
 STAGE 1: Trade Evaluation & Lesson Extraction  (§5)
        │  structured lessons, accumulated over time
        ▼
 STAGE 2: Hypothesis & Candidate Generation  (§6)
        │  a proposed, scoped model/parameter change
        ▼
 STAGE 3: Validation Pipeline  (ADD §8.2 / MLD §9 — not redefined here)
        │  ValidationRunRecord evidence
        ▼
 STAGE 4: Promotion Decision  (MLD §9.2 criteria — not redefined here)
        │  promoted candidate replaces prior production model
        ▼
 STAGE 5: Continuous Monitoring & Degradation Detection  (§7)
        │  degradation detected → automatic rollback (ADD §8.4)
        │  no degradation → informs next cycle's Stage 1 evaluation
        └──────────────────────────────────────────────────► (loop closes)
```

Every stage writes to the same audit trail (decision records, `ValidationRunRecord`, `PromotionEvent`, `RollbackEvent` — DDD-defined entities, not redefined here) so the loop as a whole is auditable end-to-end, not just at the promotion moment (FRD-LEARN-8).

---

## 5. Stage 1 — Trade Evaluation & Lesson Extraction

Extends FRD-EVAL-3's per-trade variance-driver classification (bad signal, bad timing, bad sizing, bad execution, unexpected event, regime change, data problem, model problem) into a process that accumulates evidence across trades, not just per-trade.

### 5.1 Per-Trade Evaluation (Already Defined, Referenced)

Each completed trade already produces a `TradeEvaluation` record (FRD-EVAL-3) comparing expected outcome at entry against actual outcome at exit, with a classified variance driver. This SLD does not change that per-trade mechanic; it defines what happens *across* many such records.

### 5.2 Pattern Detection (New — Aggregation Across Trades)

On a defined cadence (§10), the system aggregates `TradeEvaluation` records and looks for statistically supported patterns along dimensions already available in the data — never inventing a new dimension not already captured by the decision record:

- **By regime dimension** (MLD §5.1's five dimensions): e.g., "trades entered while `MEAN_REVERSION` agent had highest weight and volatility state was `HIGH` underperform trades entered under `NORMAL` volatility."
- **By contributing agent**: e.g., "trades where the Price Action agent's confidence was the sole driver of a passing aggregate score (ADD §7.3) underperform trades with broad agent agreement."
- **By variance driver**: e.g., "a disproportionate share of 'bad timing' classifications cluster around a specific regime transition."

A pattern is only surfaced as a candidate hypothesis (§6) if it clears a minimum evidence bar — proposed: a minimum sample size (consistent with MLD §9.2's sample-size discipline) and a statistical significance check comparable in spirit to MLD §9.3's promotion significance test — so that Stage 1 does not manufacture hypotheses from noise. A pattern that does not clear this bar is logged as an **observed-but-unconfirmed** note, not discarded, so it can accumulate further evidence in later cycles rather than being re-derived from scratch each time.

### 5.3 What Stage 1 Explicitly Does Not Do

Stage 1 never modifies a live parameter, agent, or model directly — its only output is a structured hypothesis record consumed by Stage 2. This mirrors ADD §10's isolation design: pattern detection is analysis, not action, and the Research Brain boundary (ADD §10) applies to this stage exactly as it does to the rest of the Learning Pipeline.

---

## 6. Stage 2 — Hypothesis & Candidate Generation

### 6.1 From Hypothesis to Candidate

A hypothesis from §5.2 becomes a candidate only when it can be expressed as a **scoped, testable change**: a specific parameter revision (e.g., a Model Parameter Register entry per MLD §11), a specific agent's confidence-formula change, a new aggregation weight set, or — least frequently — a new agent or a rule-based-to-statistical upgrade for an existing agent (subject to MLD §10's complexity-ceiling justification). A hypothesis that cannot be expressed this concretely (e.g., "the system should just be smarter about volatility") is not converted into a candidate — it is logged as requiring further Stage 1 analysis before it is actionable.

### 6.2 Candidate Scoping Discipline

Each candidate changes **one thing at a time** where practical (e.g., one agent's one parameter, or one weighting scheme revision) rather than bundling multiple hypotheses into a single candidate. This is a deliberate constraint, not an efficiency compromise: bundling makes it impossible to attribute a validation-stage pass or fail to the specific change that caused it, which would undermine both MLD §9's comparison procedure and this SLD's own §5.2 pattern-attribution going forward. Where two hypotheses are causally linked (e.g., a parameter change that only makes sense alongside a related regime-dimension change), they may be bundled, but the candidate record must state the linkage explicitly, not present it as if it were a single atomic change.

### 6.3 Candidate Generation Is Not Continuous

Candidates are generated on a defined cadence (§10), not the instant a hypothesis clears the §5.2 evidence bar. This is a deliberate throttle: continuous candidate generation would create validation-pipeline backlog pressure that, left unchecked, could create an incentive to shortcut §8.2-of-ADD's validation stages — exactly the "uncontrolled self-modification" PRD §9 explicitly ranks below "proven improvement."

---

## 7. Stage 5 — Continuous Monitoring & Degradation Detection

Elaborates FRD-LEARN-7 and ADD §8.4's rollback design into an actual operational mechanism.

### 7.1 What Is Monitored

For every promoted model, live/paper performance (the same metrics defined in MLD §8, computed on a rolling basis) is compared against the **validated expected performance** recorded at promotion time (the evidence bundle behind that model's `PromotionEvent`) — not against an arbitrary external benchmark, and not against the *current* production model (since the model being monitored *is* the current production model).

### 7.2 Degradation Detection Mechanic

Rather than a single-trade trigger (which would be noise-prone) or a purely time-based check (which could let a degrading model run too long), degradation detection uses a **rolling-window comparison with a minimum evidence bar**, mirroring MLD §9.3's promotion significance discipline in reverse:

- A rolling window of the most recent N trades (proposed: same minimum sample size as MLD §9.2's promotion bar, 30 trades) for the live model is compared against its validated expected performance on the same metrics (Sharpe, max drawdown at minimum).
- If the rolling-window Sharpe falls below the validated expectation by more than a defined margin (proposed: expected Sharpe minus one standard error of the validated estimate — i.e., performance has dropped outside what the original validation's own uncertainty would predict), **and** this holds for two consecutive rolling-window evaluations (to avoid a single unlucky window triggering an unnecessary rollback), automatic rollback (ADD §8.4) is triggered.
- A **hard override**: regardless of the statistical test above, if rolling-window max drawdown breaches the RTLD-defined drawdown limit for that capital allocation, rollback is triggered immediately — this is not a self-learning-loop decision at all, but the existing RTLD/Risk Engine mechanism (out of scope here) simply also being a trigger this loop must respect and never suppress.

### 7.3 Rollback Is Not a Verdict on the Model Alone

A rollback event (§7.2) is itself fed back into Stage 1 (§5) as a trade-evaluation-equivalent data point — *why* did the promoted model degrade: was it a regime shift the validation period didn't cover, an overfitting artifact the walk-forward test underestimated, or a genuine change in market conditions? This closes the loop shown in §4: a rollback is not a dead end, it is itself a lesson.

---

## 8. Self-Learning Safety Guardrails

These exist specifically because a self-modifying system is a different risk category from a static one, even when every individual promotion passes MLD §9.2's criteria.

| Guardrail | Design |
|---|---|
| **Cooldown period per agent/parameter** | After a promotion affecting a given agent or parameter, a minimum cooldown period (proposed: sufficient live/paper trades to gather a fresh evaluation sample, e.g., the same 30-trade minimum) must elapse before another candidate affecting the *same* agent/parameter can be proposed — prevents the loop from thrashing (promote, degrade, revise, promote again) faster than evidence can actually accumulate. |
| **Concurrent candidate limit** | A small maximum number of candidates (proposed: 1) may be in the validation pipeline (ADD §8.2) at a time — consistent with Guiding Principle 7 and a single-operator project's realistic review capacity (PRD §16 item 6's open question on promotion sign-off level), and it keeps §6.2's one-change-at-a-time attribution discipline enforceable in practice, not just in principle. |
| **Rollback-triggered pause** | Two rollbacks within a defined lookback period (proposed: any 90-day window) for the *same* agent/parameter area triggers a mandatory pause on further candidates in that area until an operator reviews the pattern — an automated loop that keeps confidently promoting and then rolling back the same kind of change is a signal the loop's own hypothesis-generation (§6) needs review, not just the individual models. |
| **No self-referential objective** | The loop's own success metric (e.g., "candidates promoted per month") is never fed back as an optimization target anywhere in Stages 1–2 — the only objective any candidate is evaluated against is MLD §9.2's trading-performance criteria, never "does this make the learning pipeline look productive." |
| **Human visibility, not just human sign-off** | Independent of whether human sign-off is required for a given promotion (open item, BRD §11 item 6 / ADD §13 item 4), every hypothesis, candidate, promotion, and rollback in this loop is visible on the Dashboard (FRD Module 11) — the guardrails above reduce how often a human *must* act, but they do not reduce what a human *can* see. |

---

## 9. Failure Modes of the Loop Itself

Distinct from failure modes of any individual model (already covered by MLD's overfitting guardrails and ADD's validation pipeline):

| Failure Mode | Mitigation |
|---|---|
| **Hypothesis starvation** — too few completed trades to ever clear §5.2's evidence bar | Expected and acceptable at low trade volume (early V6); the loop should surface this explicitly (e.g., "N trades evaluated, no pattern yet meets significance bar") rather than lowering the bar to force a hypothesis into existence. |
| **Hypothesis overproduction** — too many marginal patterns surfacing at once as trade volume grows | Addressed by §8's concurrent candidate limit and cooldown guardrails — the validation pipeline's throughput, not the hypothesis-generation rate, is the intended bottleneck. |
| **Repeated promote/rollback oscillation** | Addressed by §8's rollback-triggered pause. |
| **Regime-shift misattribution** — a model degrades because the market genuinely changed, and the loop "fixes" a model that was never actually broken | Addressed by §7.3's requirement that a rollback's root cause be classified (regime shift vs. overfitting vs. other) before generating a corrective hypothesis — a regime-shift-attributed rollback should inform Stage 1's regime-conditioned pattern detection (§5.2) rather than triggering an immediate re-tune of the same parameter. |
| **Validation-pipeline backlog** | Addressed by §6.3's throttled candidate-generation cadence and §8's concurrent-candidate limit — the loop is designed to never generate candidates faster than the validation pipeline (ADD §8.2) can honestly process them. |

---

## 10. Self-Learning Parameter Register

All entries below are **Proposed — pending operator sign-off**, consistent with RTLD §14, BTD §6, and MLD §11.

| Parameter | Proposed Value | Section |
|---|---|---|
| Pattern-detection (Stage 1) run cadence | Weekly, or every N completed trades, whichever is less frequent (TBD exact N) | §5.2 |
| Minimum sample size for a hypothesis to clear the evidence bar | Same as MLD §9.2 promotion sample size (30) | §5.2 |
| Candidate-generation (Stage 2) cadence | No more frequent than the cooldown period below permits per agent/parameter | §6.3 |
| Monitoring rolling-window size | 30 trades | §7.2 |
| Degradation trigger | Rolling Sharpe below validated expectation − 1 standard error, sustained across 2 consecutive windows | §7.2 |
| Cooldown period per agent/parameter after promotion | ≥ 30 live/paper trades | §8 |
| Concurrent candidate limit | 1 | §8 |
| Rollback-triggered pause threshold | 2 rollbacks in same agent/parameter area within 90 days | §8 |

The exact pattern-detection cadence (weekly vs. trade-count-based) is left partially open (TBD) because it depends on realized trade frequency, which is itself unknown until paper trading (V4) produces real data — this MLD-adjacent register deliberately avoids guessing a cadence number that trade volume alone should determine.

---

## 11. Traceability

| SLD Section | Source Requirement(s) |
|---|---|
| §5 Trade evaluation & lesson extraction | FRD-EVAL-3; FRD-LEARN-2 |
| §6 Hypothesis & candidate generation | FRD-LEARN-2; ADD §10; MLD §10 |
| §7 Monitoring & degradation detection | FRD-LEARN-7; ADD §8.4 |
| §8 Safety guardrails | PRD §9; TRD Guiding Principle 7; BRD §11 item 6 |
| §9 Loop failure modes | PRD §15; SOW §6.7–§6.8 acceptance criteria |

Every parameter in §10 should be entered into the Requirements Traceability Matrix alongside its FRD/ADD/MLD lineage, and SOW §6.8's V7 acceptance criterion ("a deliberately degraded model can be shown triggering an automatic rollback") should be tested directly against §7.2's mechanic before V7 is considered complete.

---

## 12. Open Items Requiring Operator or Downstream Decision

1. **Exact pattern-detection cadence** (§10) — weekly vs. trade-count-based — pending real trade-frequency data from V4 paper trading.
2. **Concurrent candidate limit of 1** (§8) — confirm this is not overly restrictive once the initial four-agent roster (ADD §6.2) grows; may warrant revision as the system matures into later V-phases.
3. **Human sign-off cadence for hypothesis review** (distinct from promotion sign-off, BRD §11 item 6) — should every hypothesis that clears §5.2's bar be visible to the operator before a candidate is even generated, or only at promotion time? This SLD assumes the latter (§8's "visibility, not sign-off" default) but flags it for confirmation.
4. **90-day rollback-pause lookback window** (§8) — a placeholder; should be revisited once real rollback frequency data exists.

---

## 13. Document Governance

This SLD is a living document and must be reviewed whenever:
- Real trade-frequency data from V4 (paper trading) resolves the TBD cadence in §10.
- A rollback-triggered pause (§8) actually fires, to confirm the 90-day window and same-area detection logic behaved as intended.
- ADD's lifecycle state machine (§8) or MLD's promotion criteria (§9) change in a way that affects this SLD's Stage 3/4 references.
- SOW §6.8's V7 acceptance criteria are formally tested, to confirm §7.2's degradation mechanic satisfies them in practice.

**Next recommended step:** the operator reviews and confirms the guardrail values in §8 and §10, since these govern how aggressively the system is allowed to modify itself once V6 is reached; the exact cadence values marked TBD should be resolved from V4 paper-trading data rather than fixed now.