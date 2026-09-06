# AI / Agent Architecture & Design (ADD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | AI / Agent Architecture & Design (ADD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD, BRD, FRD, NFRD, TRD, HLD, RTLD, BTD, DDD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader FRD v0.1 (Modules 3–5, 10), TRD v0.1 (§9), HLD v0.1 (§6–§8, §12, §16) |

---

## 1. Purpose of This Document

The HLD decided *where* the AI components sit (Agent Roster, Regime Detector, Aggregator, Learning Pipeline — as components inside the Trading Brain / Research Brain split) and *how* they are isolated from the safety-critical path. The TRD stated the *technical properties* those components' training/serving infrastructure must have (TRD-ML-1–6). Neither document specifies what any individual agent actually **is**, what it consumes and produces, how many "kinds" of intelligence exist in the system, how they are combined into one decision, or how a model moves from an idea to something trusted with live capital.

This ADD is that document. It is the detailed design of the system's actual intelligence: the Agent Roster (FRD Module 4), the Regime Detector (FRD Module 3), the Aggregator (FRD Module 5), and the Learning & Model Lifecycle Pipeline (FRD Module 10) — the four components in HLD §6 that contain model logic, as opposed to the deterministic components (Risk Engine, Supervisor, Execution Engine) that this document explicitly does not touch.

This ADD does not select specific ML/DL frameworks, libraries, or vendor model APIs — that remains a TTD/ADR decision, made against the contracts and constraints defined here. Where this ADD proposes a specific technique for an agent (e.g., "trend agent uses a rule-based/statistical approach, not a black-box model"), that is a reasoned design proposal, flagged for operator confirmation, consistent with how HLD §4 handled its own open architectural choice.

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| No AI/LLM/probabilistic component may be a required dependency for hard risk-limit evaluation or kill-switch operation, and none may override a Risk Engine block. | BRD BR-4; FRD-RISK-11; NFR-SAFE-1/2; HLD §8 |
| Every agent's output — or its absence — must be logged for every evaluation cycle, distinguishing actual model output from any post-hoc explanation. | FRD-SIG-4; FRD-EVAL-2, FRD-EVAL-6 |
| An agent's failure must never crash the system or block the decision pipeline; a missing agent is "no view," not a fault, unless explicitly designated mandatory. | FRD-SIG-3 |
| NO TRADE is a first-class, valid outcome — the Aggregator must never force a selection among low-quality candidates to avoid an empty result. | FRD-AGG-4; BRD BR-3 |
| The Research Brain has no functional pathway to live execution or capital allocation; it only ever proposes a promotion, never actuates one. | FRD-X-4; HLD §10, §12 |
| Reinforcement learning, where used, trains only in a technically sandboxed environment incapable of submitting real orders, with a reward function that is not raw profit alone. | FRD-LEARN-9; TRD-ML-4 |
| Training workloads must never be able to degrade live decision latency — training and serving are technically separated. | TRD-ML-3 |
| Avoid unnecessary complexity — no agent, model type, or pipeline stage should be more elaborate than the ₹10,000-scale, single-operator project currently justifies. | TRD Guiding Principle 7; HLD §2 |
| The initial agent roster and the mandatory-vs-optional agent list are open items to be resolved here, not assumed from the Master Context's full candidate menu. | FRD-SIG-5; HLD §17 item 4 |

This ADD converts these constraints into an actual design for the system's intelligence layer — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:** the Agent Roster's internal design (candidate agent inventory, per-agent contract, technique classification); the Regime Detector's design; the Signal Aggregation / Trade Quality Scoring methodology; the model lifecycle in detail (candidate → validated → promoted → monitored → rolled back), including the entities that carry it (`ModelVersion`, `ValidationRunRecord`, `PromotionEvent`); the Research Brain's Learning Pipeline internal stages; reinforcement learning design constraints, where applicable; and how AI-generated outputs feed the decision record without becoming a source of fabricated explanation.

**Out of scope:** the Risk Engine, Supervisor, and Execution Engine's internal logic (owned by RTLD and the safety-critical LLD); numeric risk parameters (RTLD §14); backtesting cost/friction modeling and fill simulation (BTD); the full data schema for any entity referenced here (DDD); specific ML/DL/RL framework or vendor model selection (TTD/ADRs); the API contract for agent interfaces (API Spec); and UI layout of the AI-state dashboard panel (UI/UX Spec).

---

## 4. Design Philosophy for the Intelligence Layer

Before designing individual agents, four decisions apply across all of them:

1. **Not every agent needs to be a machine-learning model.** FRD-SIG-2 only requires a directional view (or "no view"), a confidence level, and the inputs used — it does not require the agent to be a trained model. A rule-based trend-following agent (e.g., moving-average relationship logic) satisfies the contract as fully as a gradient-boosted classifier does. Per Guiding Principle 7 and the priority order (reliability > maintainability > correctness > observability > performance > scalability > cost), **the default technique for each agent should be the simplest one that produces a defensible signal**, with statistical/ML techniques introduced only where a rule-based approach is genuinely insufficient. This is proposed per-agent in §6.

2. **An agent is a function, not a persona.** Regardless of technique, every agent has the same shape: `(instrument, timeframe, FeatureSet, RegimeClassification) → AgentSignalOutput`. This uniformity is what makes FRD-SIG-3's "failed agent = no view" behavior and Module 5's aggregation possible without special-casing each agent's internals.

3. **No agent — including any that might use a language model for a text-heavy input like news — sits anywhere near the safety-critical path.** This is already structurally guaranteed by HLD §8; this ADD does not weaken or need to restate that boundary, only design within it.

4. **Confidence is a number, not a feeling.** Every agent's confidence output must be a bounded, comparable, auditable value (§7.2) — never a free-text qualitative statement standing in for a number, since Module 5 has to combine confidences across agents of very different internal designs.

---

## 5. Regime Detector — Detailed Design

Implements FRD-REGIME-1–5 (Module 3).

| Aspect | Design |
|---|---|
| **Inputs** | The versioned FeatureSet (HLD §7) for the instrument/timeframe under evaluation — price/volatility statistics, volume profile, and, where available, cross-asset/breadth indicators. No agent-level outputs are consumed as an input to regime detection (regime is computed upstream of the Agent Roster, per HLD §7's pipeline order). |
| **Classification dimensions** | Trend state (trending / ranging), volatility level (relative, e.g., percentile-based), directional bias (bullish / bearish / neutral), risk sentiment (risk-on / risk-off, where cross-asset data supports it), and liquidity condition (normal / degraded). |
| **Technique proposal** | Rule-based/statistical classification (e.g., threshold and percentile logic over volatility and trend-strength indicators) is proposed as the default for the initial roster, not a trained classifier — regime detection needs to be interpretable and stable, and an opaque model here would work against FRD-EVAL-4's "what regime was detected" query needing a traceable answer. A learned regime classifier is a candidate future enhancement, developed and validated through the same Learning Pipeline (§10) as any other model, not assumed by default. |
| **Transition detection** | A transition is flagged distinctly from steady-state classification (FRD-REGIME-2) — implemented as a comparison between the current cycle's classification and a short rolling history, not merely "regime changed since last tick" (to avoid flagging noise as a transition). Exact smoothing/hysteresis parameters are an MLD-level detail, not fixed here. |
| **Consumers** | Broadcast to every Module 4 agent and to the Risk Engine (FRD-REGIME-3) as a single `RegimeClassification` object per cycle — agents may use it as a feature; the Risk Engine may use it only for risk-relevant purposes already defined in RTLD (this ADD does not grant the Risk Engine any new discretionary use of regime data). |
| **Isolation confirmation** | Per HLD §17 item 7: this design places the Regime Detector outside the safety-critical boundary. Nothing in this design gives the Risk Engine or Supervisor a call-out dependency on the Regime Detector at evaluation time beyond consuming its already-computed output for the current cycle — if the Regime Detector fails to produce a classification, the cycle proceeds with regime marked `UNKNOWN`, which downstream (per RTLD) can be treated as a liquidity/data-quality-adjacent condition rather than blocking the whole pipeline. |

---

## 6. Agent Roster — Candidate Inventory and Initial Proposal

FRD-SIG-5 leaves the initial roster open, to be determined here. Per HLD §17 item 4 and §16 (V3 first stands up "an initial validated subset"), this section proposes a starting roster rather than building all fourteen Master Context candidates at once — consistent with Guiding Principle 7 and with FRD-SIG-1's "each agent can be enabled/disabled independently" (the roster is meant to grow incrementally, not appear complete on day one).

### 6.1 Full Candidate Menu (from Master Context §10 / FRD-SIG-1), Classified

| Agent | Primary Inputs | Proposed Technique | Proposed Initial Tier |
|---|---|---|---|
| **Trend** | Price series, moving-average relationships, trend-strength indicators | Rule-based/statistical | **V3 initial roster** |
| **Momentum** | Rate-of-change, oscillator-style features | Rule-based/statistical | **V3 initial roster** |
| **Mean-Reversion** | Deviation from statistical mean/bands, volatility-normalized distance | Rule-based/statistical | **V3 initial roster** |
| **Price Action** | Candlestick/bar structure, support-resistance levels | Rule-based/statistical | **V3 initial roster** |
| **Signal** (composite technical) | Combination of the above feature families | Statistical / lightweight ML classifier | Candidate for V3, pending FRD-SIG-5 confirmation — may be subsumed by Aggregator's own scoring (§7) rather than existing as a separate agent; flagged as an open item (§13 item 1). |
| **Pattern** | Chart-pattern recognition over price series | ML (sequence/pattern model) | Later phase — meaningfully harder to validate and explain than the rule-based agents; deferred until V3's simpler roster has established the pipeline (per HLD §16). |
| **Order Flow** | Trade-by-trade/tick data, buy/sell pressure | Statistical, contingent on data availability | Later phase — depends on a market-data entitlement not yet confirmed (PRD §6.3, TRD-PIPE-5). |
| **Order Book** | Depth-of-book data | Statistical, contingent on data availability | Later phase — same data dependency as Order Flow. |
| **Volatility** | Realized/implied volatility measures | Rule-based/statistical | Later phase — meaningfully overlaps with Regime Detector's volatility dimension; needs a scoped, non-duplicative role before inclusion (open item, §13 item 2). |
| **Options** | Options-chain data (OI, IV skew, Greeks) | Statistical | Later phase — depends on the still-open initial live-instrument decision (PRD §6.3); irrelevant if the initial instrument is pure equity. |
| **News** | Financial news feed | ML (text classification / summarization), **not** a general-purpose LLM agent with discretionary reasoning | Later phase — requires a news data source and an explainability approach that satisfies FRD-EVAL-2 (§9 below) before inclusion. |
| **Sentiment** | Social/alternative sentiment data | ML (text/sentiment classification) | Later phase — same data-source and explainability prerequisites as News; may share infrastructure with the News agent. |
| **Cross-Asset** | Related-instrument/index/global-market data | Statistical | Later phase — depends on cross-asset data source scope. |
| **Event** | Scheduled events/announcements (earnings, macro releases) | Rule-based (calendar-driven) with statistical impact scoring | Later phase — relatively low-complexity once an events data source exists; could plausibly move earlier than other "later phase" agents. |

### 6.2 Proposed V3 Initial Roster

**Trend, Momentum, Mean-Reversion, and Price Action** are proposed as the initial four agents, because:

- All four are rule-based/statistical, requiring no training pipeline to stand up before the full pipeline shape (HLD §7) can be exercised end-to-end for the first time.
- They cover complementary, partially independent views of the same price data, so the Aggregator (§7) has genuine disagreement/agreement signal to work with from day one, rather than four near-duplicate opinions.
- None of them depend on a data entitlement beyond OHLCV/price data, which is already in scope for V0 (FRD-DATA-1 equivalent).
- They give the Learning Pipeline (§10) a natural, low-risk first subject: refining rule thresholds or introducing a first statistical/ML variant of one of these four, rather than the higher-complexity News/Sentiment/Pattern agents.

This is a **proposal, not a finalized decision** — it should be confirmed or revised by the operator per HLD §17 item 4, particularly if a different subset better matches whatever initial live-trading instrument is eventually chosen (PRD §6.3).

### 6.3 Mandatory vs. Optional Agents

Per FRD-SIG-3, this ADD proposes that **no agent in the initial roster is designated mandatory** — a cycle may legitimately proceed to the Aggregator with fewer than four agent outputs (e.g., one agent unavailable), since FRD-AGG-4 already provides the correct fallback (NO TRADE if aggregate quality is insufficient) without needing a separate "mandatory agent missing" special case. This should be revisited once News/Sentiment or any agent whose absence would meaningfully change risk exposure is added — at that point, a mandatory designation might be warranted specifically for *risk-relevant* absence, not general aggregation quality. Flagged as an open item (§13 item 3).

---

## 7. Signal Aggregation & Trade Quality Scoring — Detailed Design

Implements FRD-AGG-1–6 (Module 5).

### 7.1 Aggregation Methodology Proposal

Three methodology families were considered:

| Approach | Description | Assessment |
|---|---|---|
| **Weighted voting/scoring** | Each agent's directional view and confidence are combined via configurable weights (equal-weighted initially) into a single expected-value/direction score. | **Proposed for the initial roster.** Fully deterministic given agent outputs, trivially auditable (FRD-AGG-5's "weights/scores, disagreement" is a direct readout, not a derived approximation), and requires no training data of its own before V3 can run. |
| **Learned meta-model (stacking)** | A trained model takes agent outputs as features and produces the aggregate score/decision input. | Deferred. This would itself be a model requiring the full Learning Pipeline (§10) validation before being trusted — appropriate as a *later*, validated upgrade to the Aggregator, not a V3 starting point, per Guiding Principle 7. |
| **Rule-based consensus threshold** (e.g., "N of M agents must agree") | Simple agreement-counting. | Rejected as the sole mechanism — it discards each agent's confidence gradation (FRD-SIG-2 requires confidence, not just direction), which weighted scoring preserves. May still be layered on top of weighted scoring as an additional quality-gate check, not a replacement. |

**Proposed design:** weighted scoring produces the trade quality score and expected-value assessment (FRD-AGG-1/2); a configurable minimum-threshold gate (FRD-AGG-6) determines whether the result is passed onward at all, independent of any single agent's output.

### 7.2 Confidence and Score Normalization

For weighted scoring to be meaningful across heterogeneous agents (§4 point 4), every agent's confidence output must be normalized to the same bounded scale before aggregation (e.g., a common [0, 1] range) regardless of the agent's internal technique — a rule-based agent's confidence might derive from how far a threshold was exceeded, while a statistical agent's might derive from a model's predicted probability. The normalization function is agent-specific (defined per agent at implementation time) but the *contract* — bounded, comparable output — is fixed here and is not negotiable per-agent, since Module 5 cannot compare unnormalized scores meaningfully.

### 7.3 Dynamic Timeframe Selection

FRD-AGG-3 requires evaluating multiple candidate timeframes and selecting the most appropriate one per opportunity/regime. Proposed design: the Aggregator runs its weighted-scoring evaluation independently per candidate timeframe (each timeframe's Agent Roster outputs are computed separately — agents are timeframe-parameterized per §4 point 2's contract), and the Aggregator selects the timeframe with the highest resulting trade quality score, subject to that score also clearing the FRD-AGG-6 minimum threshold. If no timeframe clears the threshold, the result is NO TRADE regardless of how the timeframes compare to each other (consistent with FRD-AGG-4 — being the "best" of several rejected candidates is not the same as being acceptable).

### 7.4 Disagreement as Information, Not Noise

FRD-AGG-5 requires logging disagreement explicitly. Design implication: the Aggregator's output record includes not just the final score but a disagreement measure (e.g., dispersion between contributing agents' directional views/confidences). This is deliberately preserved through to the decision record (FRD-EVAL-1) because high disagreement despite a passing score is exactly the kind of pattern the Learning Pipeline (§10) should be able to later analyze — e.g., "trades approved despite high agent disagreement underperform trades approved with high agreement" is a hypothesis the system should be *able* to test, which requires the raw disagreement signal to survive into stored history, not just the final score.

---

## 8. Model Lifecycle — Detailed Design

Elaborates HLD §12's promotion handoff and FRD-LEARN-1–9 (Module 10) into the actual stage-by-stage design of how a model moves from idea to production and, if necessary, back out again.

### 8.1 Lifecycle States

```
IDEA / HYPOTHESIS  (informed by Module 9 trade evaluations — FRD-LEARN-2)
        │
        ▼
CANDIDATE  (a ModelVersion record created, status = "candidate")
        │
        ▼
IN VALIDATION  (FRD-LEARN-3 pipeline — §8.2 below)
        │
        ├── fails any stage ──► REJECTED  (ValidationRunRecord retained; not deleted)
        │
        ▼ (passes all stages)
VALIDATED  (meets/exceeds FRD-LEARN-4 promotion threshold vs. current production model)
        │
        ▼
PENDING REVIEW  (FRD-LEARN-5 risk review; human_signoff_ref populated if required)
        │
        ▼
PROMOTED  (live model-serving slot updated — Trading Brain-side action per HLD §12)
        │
        ├── monitored performance degrades beyond threshold (FRD-LEARN-7) ──► ROLLED BACK
        │                                                                          │
        │                                                                          ▼
        │                                                          PRIOR PRODUCTION VERSION restored
        ▼
SUPERSEDED  (a later model is promoted; this version retained per FRD-LEARN-6, not deleted)
```

Every transition in this diagram is itself logged per FRD-LEARN-8 — promotion, rejection, and rollback events each carry the evidence/metrics that drove them.

### 8.2 Validation Pipeline Stages (FRD-LEARN-3)

| Stage | Purpose | Design Note |
|---|---|---|
| **Backtesting** | Historical performance under BTD's cost/friction model | Uses the same Data Pipeline contract as live (TRD-PIPE-3) so this stage exercises realistic, not idealized, data. |
| **Out-of-sample testing** | Performance on data not used during model development | Requires a hard, enforced split between development data and this stage's data — the model/strategy must not have any development-time visibility into the out-of-sample window (guards against FRD-BACK-equivalent look-ahead concerns, generalized to model development). |
| **Walk-forward testing** | Performance stability as the model is periodically retrained/re-evaluated forward through time | Directly tests whether a model's edge persists rather than being an artifact of one static historical window. |
| **Stress testing** | Behavior under extreme/adverse historical or synthetic scenarios | Should include at minimum the worst historical regimes the Regime Detector (§5) has tagged, so stress testing is regime-aware, not generic. |
| **Robustness testing** | Sensitivity to small input/parameter perturbations | Flags models that are "sharp optima" — high backtest performance that collapses under minor realistic variation — a known overfitting signature the PRD explicitly warns against (PRD §15 "backtest overfitting"). |
| **Paper trading** | Real-time, real-market-data validation with simulated execution before any live exposure | The final gate before FRD-LEARN-4's promotion-threshold comparison; this is also where the model first runs against genuinely current data and the actual Trading Brain pipeline shape (HLD §11), not just replayed history. |

Each stage produces its own `ValidationRunRecord` (DDD §5.4, referenced but not redefined here); a candidate that fails any stage stops there — later stages are not attempted on a failed candidate, since passing walk-forward with a candidate that already failed out-of-sample testing would produce a misleading validation history.

### 8.3 Promotion Threshold and Comparison

FRD-LEARN-4 requires the candidate to meet or exceed a defined threshold against the *current production model*, using PRD §10's success metrics (risk-adjusted return, capital preservation, consistency, decision quality, and so on) — not a single scalar like backtest profit. The exact numeric threshold is an MLD-level decision (FRD-LEARN-4 explicitly defers it), but this ADD fixes the design principle: **the comparison is always candidate-vs-current-production on the same multi-dimensional metric set**, not candidate-vs-an-absolute-bar computed in isolation, so that a candidate cannot be promoted merely for being "good" in the abstract while being worse than what is already live.

### 8.4 Promotion, Human Sign-off, and Rollback

Consistent with HLD §12, the Research Brain proposes a `PromotionEvent`; it never actuates a promotion. The component that flips the live model-serving slot is Trading Brain-side. Where human sign-off is required (open item, BRD §11 item 6), the `human_signoff_ref` field blocks the transition to PROMOTED until populated (FRD-LEARN-5) — this ADD does not resolve whether sign-off is required for every promotion or only above some materiality threshold; that remains an operator decision (§13 item 4).

Rollback (FRD-LEARN-7) is designed as a **monitoring comparison**, not a one-time check at promotion: live/paper performance is continuously compared against the validated expected performance recorded at promotion time, and a degradation beyond a defined threshold triggers automatic reversion to the immediately prior production `ModelVersion` (never deleted, per FRD-LEARN-6). This makes rollback a safety mechanism that operates over the model's entire production lifetime, not just its first days live.

---

## 9. AI Output, Explainability, and Guarding Against Fabrication

This section elaborates FRD-EVAL-2 and FRD-EVAL-6 specifically as they apply to the Agent Roster and any text-consuming agent (News, Sentiment).

- **Structured output first, narrative second.** Every agent's actual output is the structured `AgentSignalOutput` (direction/no-view, normalized confidence, inputs used — §4, §7.2). Any natural-language explanation of *why* an agent produced that output is generated, if at all, as a clearly separate, labeled field — never merged into or substituted for the structured output, so that FRD-EVAL-2's distinction between (a) actual model output, (b) derived features, and (c) post-hoc explanation is preserved at the point of generation, not reconstructed later.
- **A News/Sentiment agent's role is bounded classification, not open-ended reasoning about the trade.** Where such an agent is later added (§6.1), its scope is to classify/score text into the same structured contract every other agent uses (direction/no-view, confidence) — it does not get a broader mandate to reason about position sizing, risk, or the final decision; that would blur the boundary this whole ADD is built around (§4 point 1–3) and would risk exactly the "plausible-sounding rationale" FRD-EVAL-6 prohibits.
- **No explanation without a record.** If an operator query (FRD-EVAL-4) asks why a decision was made and no decision record exists for that cycle/instrument, the system states that explicitly. This ADD does not introduce any component authorized to answer such a query by generating a plausible-sounding reconstruction — the decision record (FRD-EVAL-1) is the only legitimate source.

---

## 10. Research Brain — Learning Pipeline Internal Design

Elaborates HLD §6's "Learning Pipeline" component and FRD-LEARN-2 (candidate generation informed by trade evaluations).

| Stage | Design |
|---|---|
| **Candidate generation** | Informed by Module 9's variance-driver classification (FRD-EVAL-3: bad signal, bad timing, bad sizing, bad execution, unexpected event, regime change, data problem, model problem). A candidate is proposed as a targeted response to an observed pattern (e.g., "mean-reversion agent underperforms specifically in the high-volatility/risk-off regime combination") rather than as an undirected search — this keeps the Research Brain's output interpretable and keeps candidate volume proportionate to a single-operator project's review capacity. |
| **Feature/data reuse** | The Learning Pipeline uses the same Feature Engine and Data Pipeline contract as the live Trading Brain (TRD-ML-1, TRD-PIPE-3) — a candidate is trained/evaluated against features computed the same way they would be computed live, avoiding train/serve skew. |
| **Isolation** | Runs entirely within the Research Brain deployment (HLD §10) — no credential, network path, or write permission into Execution Engine or Capital Manager, regardless of what a candidate's logic contains. |
| **RL sandboxing** | Where a candidate involves reinforcement learning (§11), training occurs in a simulated/offline environment technically incapable of submitting real orders (TRD-ML-4) — this is not a permissions setting on an otherwise-capable environment, but an environment that structurally lacks an order-submission path at all, mirroring how the Research Brain as a whole lacks one (HLD §10). |
| **Output** | A `ModelVersion` plus its accumulated `ValidationRunRecord`s, handed off per §8.4 — the Learning Pipeline's job ends at proposing promotion, consistent with FRD-LEARN-1. |

---

## 11. Reinforcement Learning — Design Constraints (Where Used)

Per PRD FR-24 and FRD-LEARN-9, RL is explicitly optional, not assumed as part of the initial roster (§6.2 proposes no RL agents for V3). Where an RL component is introduced in a later phase:

- **Reward function** must incorporate return, risk, drawdown, volatility, transaction costs, slippage, and consistency — never raw profit alone (FRD-LEARN-9). This is a hard content requirement on the reward function's design, not a suggestion; a reward function scoped to return alone does not satisfy this ADD's constraints regardless of how well it backtests.
- **Training environment** is sandboxed per §10's RL sandboxing row — this applies during training *and* during any exploratory/online-learning phase, not only during an initial offline training run.
- **Validation** follows the same §8.2 pipeline as any other candidate — RL introduces no shortcut through backtesting, out-of-sample, walk-forward, stress, robustness, or paper trading.
- **No RL component gains any discretion over risk parameters, position sizing rules, or kill-switch behavior** — an RL agent's action space is scoped to the same `AgentSignalOutput` contract every other agent produces (§4 point 2); it does not get an expanded action space just because it is adaptive, since that would reintroduce exactly the AI-controls-safety coupling BRD BR-4 prohibits.

---

## 12. Traceability

| ADD Section | Source Requirement(s) |
|---|---|
| §4 Design philosophy | FRD-SIG-1–5; Guiding Principle 7 |
| §5 Regime Detector | FRD-REGIME-1–5 |
| §6 Agent Roster | FRD-SIG-1–5; HLD §17 item 4 |
| §7 Aggregation | FRD-AGG-1–6 |
| §8 Model lifecycle | FRD-LEARN-1, 3–8; HLD §12 |
| §9 Explainability guardrails | FRD-EVAL-1, 2, 4, 6 |
| §10 Learning Pipeline | FRD-LEARN-1, 2, 9; TRD-ML-1, 3 |
| §11 RL constraints | PRD FR-24; FRD-LEARN-9; TRD-ML-4 |

Every agent named in §6 and every lifecycle state in §8.1 should be entered into the Requirements Traceability Matrix against its FRD-ID, and the confirmation of §6.2's proposed initial roster should be logged as a formal decision once made — consistent with how HLD §4's architectural proposal is tracked.

---

## 13. Open Items Requiring Operator or Downstream Decision

1. **Whether a separate "Signal" (composite technical) agent is needed** (§6.1), or whether its role is fully absorbed by the Aggregator's own weighted-scoring logic (§7.1) — recommend resolving before V3 implementation begins, since it affects agent count.
2. **Scoped, non-duplicative role for a future Volatility agent** relative to the Regime Detector's own volatility dimension (§6.1) — needs definition before that agent is added.
3. **Whether any future agent (e.g., News/Sentiment) should be designated mandatory** for risk-relevant absence, distinct from general aggregation-quality NO TRADE behavior (§6.3) — revisit when such an agent is added, not before.
4. **Human sign-off materiality threshold for promotion** (§8.4; carried from BRD §11 item 6) — whether every promotion requires sign-off or only those above a defined significance level.
5. **Confirm §6.2's proposed initial four-agent roster** (Trend, Momentum, Mean-Reversion, Price Action) or specify an alternative before V3 development begins.
6. **Exact promotion-threshold metric weighting** (§8.3) — deferred to MLD per FRD-LEARN-4, flagged here so MLD authorship has a clear open dependency.

---

## 14. Document Governance

This ADD is a living document and must be reviewed whenever:
- §6.2's proposed initial agent roster is confirmed, revised, or rejected by the operator.
- A new agent is added to the roster (§6.1's "later phase" agents moving forward) — its technique classification and any new data dependency should be re-validated against §4's design philosophy before implementation.
- FRD-LEARN-4's promotion threshold is formally defined in the MLD, to confirm §8.3's comparison design still holds against the actual metric weighting chosen.
- RTLD, BTD, or DDD changes in a way that affects an entity or contract referenced here (`ModelVersion`, `ValidationRunRecord`, `PromotionEvent`, `AgentSignalOutput`, `FeatureSet`, `RegimeClassification`).

**Next recommended step:** the operator reviews and confirms §6.2 (initial agent roster) and the open items in §13; MLD work (defining the promotion threshold and exact per-agent modeling detail) and LLD work on the Aggregator's weighted-scoring implementation should proceed next, since §6.2's roster choice is the input both of those downstream documents need first.
