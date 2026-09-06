# Machine Learning Design Document (MLD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Machine Learning Design Document (MLD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD, BRD, FRD, NFRD, TRD, HLD, RTLD, BTD, ADD (all v0.1) |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader FRD v0.1 (Modules 2, 3, 10), ADD v0.1 (§5–§11), BTD v0.1 (§9), RTLD v0.1 |

---

## 1. Purpose of This Document

The ADD decided the *shape* of the system's intelligence layer — which agents exist, what technique family each uses, how aggregation and the model lifecycle work structurally. Three things the ADD explicitly deferred remain open: the exact **feature engineering specification** each agent and the Regime Detector consume, the exact **regime taxonomy** (FRD's open item, restated at ADD §5), and the exact **promotion threshold** a candidate model must clear (FRD-LEARN-4's open item, restated at ADD §8.3). This MLD is where those get defined — the algorithms, formulas, feature definitions, and numeric ML-specific parameters that turn the ADD's architecture into something that can actually be built and trained.

Consistent with the project's engineering principle of not silently inventing critical requirements, every formula and numeric value below is a **derived, reasoned proposal**, flagged **Proposed — pending operator sign-off** in the Model Parameter Register (§11), the same discipline RTLD §14 applied to risk limits and BTD §6 applied to cost assumptions.

This MLD binds LLD-level implementation of Module 2 (Feature Engineering), Module 3 (Regime Detection), Module 4 (the initial Agent Roster), and Module 10 (Learning & Model Lifecycle) — any implementation must conform to the definitions here, or trigger a documented revision of this MLD first.

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| No look-ahead bias: a feature computed for a given point in time may only use data with a strictly earlier timestamp, enforced structurally. | FRD FR-26; BTD §5.2 |
| Any normalization/scaling statistic must be computed using only data available up to that point in time — never fit over the full historical dataset. | BTD §5.4 |
| Train/validation/test/out-of-sample splits must be chronological, never randomly shuffled. | BTD §5.4, §9 |
| The initial agent roster is Trend, Momentum, Mean-Reversion, and Price Action, all rule-based/statistical — no black-box model in the initial roster. | ADD §6.2 |
| Regime detection is rule-based/statistical by default, not a trained classifier, for interpretability. | ADD §5 |
| A candidate is compared against current production on PRD §10's multi-dimensional metric set, never a single scalar. | ADD §8.3; FRD-LEARN-4 |
| Robustness matters more than backtest perfection; a strategy that looks flawless in-sample and fails out-of-sample is a failure. | PRD §9; BTD §2 |
| Every agent's confidence output must be a bounded, normalized, comparable value — never a qualitative statement. | ADD §4, §7.2 |
| No AI/ML component may be a required dependency for risk-limit evaluation, and none of this document's content applies to the Risk Engine, Supervisor, or kill switch. | BRD BR-4; ADD §2 |
| Training and serving are technically separated so training workloads cannot degrade live decision latency. | TRD-ML-3 |

This MLD converts these principles into concrete feature definitions, model specifications, and thresholds — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:** the feature engineering specification (feature families, definitions, versioning) for Module 2; the final regime taxonomy and its detection thresholds for Module 3; the per-agent algorithmic specification for the four initial-roster agents (indicators, parameters, confidence-derivation formulas) for Module 4; the aggregation weighting scheme's initial numeric values for Module 5; formal definitions of the evaluation metrics named in PRD §10; the promotion-threshold formula and comparison procedure for Module 10 (FRD-LEARN-4); overfitting/robustness guardrail thresholds (walk-forward efficiency, sensitivity bounds); and the training/retraining cadence for each model type.

**Out of scope (belongs elsewhere):** which agents exist and how they're deployed/isolated (ADD §5–§11); the promotion *state machine* and lifecycle mechanics (ADD §8, already defined); backtesting cost/friction modeling and fill simulation (BTD §5–§8); hard risk-limit numeric values (RTLD §5–§14); specific ML/DL framework, library, or vendor selection (TTD/ADRs); the data schema for any entity referenced here (DDD); and the full API contract for feature/model artifacts (API Spec).

---

## 4. Feature Engineering Specification (Module 2)

Implements FRD-FEAT (feature engine requirements referenced by ADD §4, TRD-ML-1) and is the single source of truth consumed identically by the live Trading Brain and the Research Brain's Learning Pipeline (TRD-PIPE-3), per FRD-FEAT-4.

### 4.1 Feature Families

| Family | Example Features | Consumers |
|---|---|---|
| **Price/return-based** | Simple and log returns over multiple lookback windows (e.g., 5, 10, 20, 50 bars); rolling volatility (standard deviation of returns) over the same windows | Trend, Momentum, Mean-Reversion, Regime Detector |
| **Trend-strength** | Moving-average relationships (e.g., short-window vs. long-window MA position and slope); directional-strength indicators over a configurable window | Trend agent, Regime Detector |
| **Momentum/oscillator** | Rate-of-change over multiple windows; normalized oscillator-style measures bounded to a fixed range | Momentum agent |
| **Mean-reversion/dispersion** | Distance from a rolling mean, expressed in units of rolling standard deviation (a z-score-style measure); position within a rolling high-low range | Mean-Reversion agent |
| **Structural/price-action** | Local swing-high/swing-low identification; distance to nearest identified support/resistance level; recent bar-range and gap statistics | Price Action agent |
| **Volume/liquidity** | Rolling average volume; current bar volume as a ratio of that average; a liquidity-adequacy flag consistent with RTLD's liquidity threshold | Regime Detector; used by Risk Engine per RTLD (not redefined here) |

Feature families beyond these six (order flow, options, cross-asset, news/sentiment-derived features) are out of scope for this MLD version, consistent with ADD §6.1 deferring those agents to later phases — this MLD will be extended, not silently assumed, when they are added.

### 4.2 Point-in-Time Discipline

Every feature above is computed using a rolling window ending at, and including, the most recently closed bar strictly before the current decision point — never the in-progress/current bar (mirrors BTD §5.2's fill-simulation discipline, applied here to feature computation rather than execution). Any feature requiring a normalization statistic (e.g., the mean/std used in the mean-reversion z-score) computes that statistic over the same rolling window, not a fixed historical constant — this keeps the statistic itself point-in-time-valid rather than silently leaking a full-history computation into an early-period feature value (BTD §5.4).

### 4.3 Feature Versioning

Each feature's definition (window lengths, formula) is versioned as a unit — the `FeatureSet` version referenced in HLD §7/DDD §8. A change to any window length or formula constitutes a new feature-set version, not a silent parameter tweak, because a decision record's stored feature values (FRD-EVAL-1) must remain interpretable against the feature-set version that was active when that decision was made (TRD-DATA-6).

---

## 5. Regime Taxonomy — Final Definition (Module 3)

Resolves the open item carried from FRD §6 and ADD §5 ("exact regime taxonomy... must be validated, not assumed").

### 5.1 Dimensions and States

| Dimension | States | Basis |
|---|---|---|
| **Trend state** | `TRENDING_UP`, `TRENDING_DOWN`, `RANGING` | Derived from the trend-strength feature family (§4.1): a directional-strength measure above a configurable threshold in either direction classifies as trending; below threshold classifies as ranging. |
| **Volatility level** | `LOW`, `NORMAL`, `HIGH` | Rolling volatility feature (§4.1) expressed as a percentile rank against its own trailing history (e.g., trailing 100–250 bars), not an absolute number — so the classification adapts as an instrument's baseline volatility changes over time, rather than using a fixed cutoff that becomes stale. |
| **Directional bias** | `BULLISH`, `BEARISH`, `NEUTRAL` | Combination of trend state and a longer-window return sign; `NEUTRAL` applies when trend state is `RANGING` regardless of short-term return sign, to avoid flip-flopping bias labels inside a range. |
| **Liquidity condition** | `NORMAL`, `DEGRADED` | Volume/liquidity feature (§4.1) relative to its own rolling average — `DEGRADED` when current-bar volume falls below a configurable fraction of the rolling average, or when a data-quality flag (FRD-DATA-9) is active for the instrument. |
| **Risk sentiment** (cross-asset dependent) | `RISK_ON`, `RISK_OFF`, `UNKNOWN` | `UNKNOWN` is the default and expected state until a Cross-Asset agent/data source exists (ADD §6.1, later phase) — this dimension is defined now so downstream consumers have a stable contract, but is not populated with real signal until that data source is added. |

A `RegimeClassification` object carries all five dimensions per cycle, per instrument/timeframe — never a single collapsed "the regime," since PRD §10's "performance by regime" success metric and RTLD's regime-relevant checks each need to be able to slice by an individual dimension, not just a composite label.

### 5.2 Transition Detection and Hysteresis

A dimension is flagged as having transitioned only after its new state has held for a minimum number of consecutive cycles (proposed: 2 cycles), not on the first cycle a threshold is crossed — this hysteresis prevents a value oscillating near a threshold boundary from generating a transition flag every cycle (FRD-REGIME-2's distinction between steady-state classification and a genuine transition). The hysteresis window is a Model Parameter Register entry (§11), not fixed permanently by this prose.

### 5.3 Failure Behavior

Where a dimension cannot be computed (e.g., insufficient history for a new instrument, or missing volume data), that dimension is reported as `UNKNOWN` for that cycle rather than defaulting to a specific state — consistent with ADD §5's design that a Regime Detector failure degrades to `UNKNOWN`, not to a guessed classification, so downstream consumers can distinguish "no signal" from "computed and neutral."

---

## 6. Per-Agent Model Specifications (Module 4 — Initial Roster)

Per ADD §6.2, the initial roster is Trend, Momentum, Mean-Reversion, and Price Action, all rule-based/statistical. Each specification below follows the same contract: `(instrument, timeframe, FeatureSet, RegimeClassification) → AgentSignalOutput{direction, confidence, inputs_used}` (ADD §4).

### 6.1 Trend Agent

- **Logic:** Directional view derived from the trend-strength feature (§4.1) sign and magnitude — `BUY`-leaning when short-window trend indicator is positively aligned above a configurable minimum strength, `SELL`-leaning when negatively aligned, `NO_VIEW` when trend state (§5.1) is `RANGING`.
- **Confidence derivation:** Normalized to [0, 1] as a function of trend strength magnitude relative to its own rolling-history percentile — a trend strength at the 90th percentile of its trailing distribution yields higher confidence than one at the 55th percentile, so confidence reflects "how strong is this trend relative to what's normal for this instrument," not an arbitrary absolute scale.
- **Parameters requiring sign-off:** short/long moving-average window lengths; minimum strength threshold for a directional view; percentile-to-confidence mapping curve. (Model Parameter Register §11.)
- **Retraining cadence:** None required — this is a fixed-formula rule-based agent; only the *parameters* above are subject to periodic review (proposed: quarterly, or upon a Learning Pipeline candidate proposing a revision per ADD §10).

### 6.2 Momentum Agent

- **Logic:** Directional view from rate-of-change across the momentum feature family (§4.1) — `BUY`-leaning on sustained positive rate-of-change above threshold, `SELL`-leaning on sustained negative, `NO_VIEW` when rate-of-change is within a configurable neutral band.
- **Confidence derivation:** Normalized to [0, 1] from the oscillator-style feature's distance from its neutral midpoint, scaled by its own bounded range — since this feature family is already range-bounded by construction (§4.1), no percentile transform is needed here (unlike Trend), simplifying the confidence formula relative to §6.1.
- **Parameters requiring sign-off:** rate-of-change lookback window(s); neutral-band width; confidence scaling factor.
- **Retraining cadence:** None required (fixed-formula), same review cadence as §6.1.

### 6.3 Mean-Reversion Agent

- **Logic:** Directional view opposite the current deviation direction — `BUY`-leaning when price is a configurable number of standard deviations *below* its rolling mean (the mean-reversion z-score feature, §4.1), `SELL`-leaning when equivalently *above*, `NO_VIEW` within a configurable neutral band around the mean. Deliberately down-weighted (via confidence, not suppressed outright) when Regime Detector's trend state (§5.1) is `TRENDING_UP` or `TRENDING_DOWN`, since mean-reversion logic is structurally less reliable in a strongly trending regime — this down-weighting is itself a specific, named hypothesis this agent's design encodes, not an incidental detail, and is exactly the kind of thing the Learning Pipeline (ADD §10) should later test empirically.
- **Confidence derivation:** Normalized to [0, 1] from the z-score magnitude (larger deviation → higher confidence, up to a capped magnitude beyond which additional deviation does not further increase confidence, to avoid an extreme outlier bar producing an overconfident signal), then multiplied by a regime-conditioned discount factor per the trending-regime down-weighting above.
- **Parameters requiring sign-off:** rolling window for mean/std computation; z-score neutral-band width; z-score cap for confidence saturation; trending-regime discount factor.
- **Retraining cadence:** None required (fixed-formula); the regime-conditioned discount factor is the most likely candidate for future Learning Pipeline-driven revision, per the note above.

### 6.4 Price Action Agent

- **Logic:** Directional view derived from proximity to identified support/resistance levels and recent structural context (§4.1) — `BUY`-leaning near an identified support level with a favorable recent-bar pattern (e.g., rejection wick), `SELL`-leaning near resistance with an unfavorable pattern, `NO_VIEW` when price is not near any identified structural level.
- **Confidence derivation:** Normalized to [0, 1] from a combination of (a) how cleanly the structural level was defined (e.g., how many prior times price respected it) and (b) how close the current bar is to that level — this is the most heuristic of the four initial agents' confidence formulas, and is explicitly flagged (§12 item 1) as the one most likely to need MLD revision once real behavior is observed.
- **Parameters requiring sign-off:** swing-high/low identification window; "near a level" proximity threshold; minimum historical-respect count for a level to count as "clean."
- **Retraining cadence:** None required (fixed-formula), same review cadence as §6.1.

---

## 7. Signal Aggregation — Weighting Scheme (Module 5)

Elaborates ADD §7.1's weighted-scoring proposal with initial numeric values.

### 7.1 Initial Weights

| Agent | Proposed Initial Weight |
|---|---|
| Trend | 0.25 |
| Momentum | 0.25 |
| Mean-Reversion | 0.25 |
| Price Action | 0.25 |

**Equal weighting is proposed as the starting point**, deliberately, rather than a data-derived weighting scheme — with no live or paper-trading history yet to justify any agent's weight being higher than another's, an unequal initial weighting would be an unjustified assumption dressed up as a design choice. Weight revision is a Learning Pipeline candidate output (ADD §10), validated through the full pipeline (§8.2 of ADD) like any other model change — weights are never hand-tuned outside that pipeline once live/paper history exists to inform them.

### 7.2 Aggregate Score Formula

For a given candidate opportunity, timeframe, and cycle:

```
aggregate_score = Σ (agent_weight_i × agent_confidence_i × agent_direction_sign_i)
                   for all agents i that produced a view (not NO_VIEW)
```

where `agent_direction_sign_i` is +1 for a bullish view, −1 for a bearish view. Weights among only the *responding* agents are re-normalized to sum to 1 before this calculation (so a missing agent, per FRD-SIG-3, does not silently shrink the achievable maximum score — it simply removes that agent's input and redistributes proportionally among the rest).

### 7.3 Disagreement Measure

```
disagreement = weighted standard deviation of agent_direction_sign_i × agent_confidence_i,
               across responding agents, using the same re-normalized weights
```

A high `disagreement` value alongside a passing `aggregate_score` is preserved in the decision record per ADD §7.4 — this MLD does not gate on disagreement directly (that remains a Risk Engine/RTLD-level decision if adopted), it only formally defines how the number is computed.

---

## 8. Evaluation Metrics — Formal Definitions

Formalizes PRD §10's named metrics so the Learning Pipeline, backtesting engine (BTD), and promotion threshold (§9) all compute the same numbers the same way.

| Metric | Formula | Notes |
|---|---|---|
| **Sharpe ratio** | `(mean(period_returns) − risk_free_rate_per_period) / std(period_returns) × sqrt(periods_per_year)` | Uses net-of-cost returns (after BTD §6's full cost/friction model), never gross returns — a Sharpe computed on gross returns would misrepresent this project's small-position-size cost sensitivity (BTD §6, brokerage as a material cost at ₹2,000 position size). |
| **Sortino ratio** | Same as Sharpe, but the denominator uses downside deviation (std of only negative period returns) instead of full std | Preferred alongside Sharpe per PRD §10, since it does not penalize upside volatility. |
| **Expectancy** | `(win_rate × avg_win) − (loss_rate × avg_loss)`, expressed in currency or R-multiples | Computed net of all costs (§ above); PRD §10 explicitly rejects raw win rate alone, so expectancy — which incorporates win rate *and* payoff asymmetry — is reported alongside, never win rate in isolation. |
| **Profit factor** | `sum(gross profits) / sum(gross losses)` (absolute value of losses) | Net-of-cost, per the same convention. |
| **Maximum drawdown** | Largest peak-to-trough decline in cumulative equity over the evaluation period, expressed as a percentage of the peak | Computed on the same equity series RTLD's live drawdown monitoring uses, so backtest/paper/live drawdown figures are directly comparable. |
| **Walk-forward efficiency ratio** | `out-of-sample period performance / in-sample period performance`, per walk-forward segment (BTD §9), averaged across segments | Central overfitting guardrail — see §10. |

All metrics are computed **per instrument, per timeframe, and pooled**, and — per PRD §10's "performance by regime" requirement — also broken down by the regime-dimension states active during each trade (§5.1), using the `RegimeClassification` recorded at decision time.

---

## 9. Promotion Threshold Definition (FRD-LEARN-4)

Resolves the open item deferred by FRD-LEARN-4 and ADD §8.3.

### 9.1 Comparison Procedure

A candidate model's validated performance (post §8.2-of-ADD pipeline) is compared against the current production model's performance **over the same historical/paper evaluation window**, never against the production model's own original (possibly stale) validation numbers — this avoids a candidate looking favorable merely because it's being judged against an outdated baseline rather than the baseline's current, comparably-measured performance.

### 9.2 Promotion Criteria (All Must Hold)

| Criterion | Threshold (Proposed) |
|---|---|
| Sharpe ratio | Candidate ≥ production Sharpe, **and** candidate Sharpe ≥ 0 (a candidate with a negative Sharpe is never promoted regardless of relative comparison) |
| Maximum drawdown | Candidate max drawdown ≤ production max drawdown × 1.1 (candidate may not be meaningfully worse on capital preservation even if it wins on return — consistent with PRD §9's "capital preservation precedes return") |
| Walk-forward efficiency ratio | ≥ 0.5 (candidate must retain at least half its in-sample performance out-of-sample; below this is treated as an overfitting signature per §10) |
| Sample size | Minimum number of trades in the paper-trading validation stage (proposed: 30) before a promotion decision is made — below this, the comparison is treated as statistically inconclusive and promotion is blocked pending more data, not decided on a small sample |
| Robustness test | No single-parameter perturbation within the robustness-test range (BTD-defined) causes the candidate to fail the Sharpe or drawdown criteria above |

**All criteria must hold simultaneously** — a candidate that improves Sharpe while failing the drawdown or robustness criterion is not promoted; this reflects ADD §8.3's principle that promotion is a multi-dimensional comparison, not a single-metric optimization.

### 9.3 Statistical Significance

Because PRD §10 explicitly requires "statistical significance and sample size considered before declaring any result meaningful," the Sharpe-ratio comparison in §9.2 is accompanied by a bootstrap or equivalent resampling-based confidence interval on the *difference* between candidate and production Sharpe — a candidate whose apparent improvement falls within the confidence interval's overlap with zero is treated as **not yet demonstrated**, and promotion is blocked pending a larger validation sample, not approved on a point estimate alone.

---

## 10. Overfitting and Robustness Guardrails

Elaborates BTD §9's walk-forward protocol and PRD §15's named risk ("backtest overfitting giving false confidence") with concrete gating logic.

- **Walk-forward efficiency ratio < 0.5** (§8 formula) on any candidate is an automatic validation-stage failure (§8.2 of ADD) — the candidate is `REJECTED` before reaching the paper-trading stage, since a candidate failing this test out-of-sample has already shown its in-sample performance does not persist.
- **Parameter sensitivity**: for any agent parameter in the Model Parameter Register (§11) proposed for revision, the robustness test (BTD-defined) must show that a ±10% perturbation of that parameter does not flip the candidate's promotion-criteria outcome (§9.2) from pass to fail — a candidate that only clears the bar at one exact parameter value, and fails just outside it, is treated as a fragile optimum, not a genuine edge (mirrors ADD §8.2's robustness-testing purpose).
- **Complexity ceiling**: consistent with §4's rule-based-first design, any candidate that replaces a rule-based agent's fixed formula with a statistical/ML model must demonstrate a **materially** better result (proposed: ≥15% relative improvement in Sharpe, not merely a marginal one) to justify the added complexity, interpretability cost, and retraining burden — a marginal improvement is not sufficient justification to abandon the simpler, more auditable formula, per Guiding Principle 7 (avoid unnecessary complexity) carried from the TRD/ADD.

---

## 11. Model Parameter Register

Every numeric value in §5–§10 above, consolidated. All entries are **Proposed — pending operator sign-off**, per the same discipline as RTLD §14 and BTD §6.

| Parameter | Proposed Value | Section |
|---|---|---|
| Trend/Momentum/Mean-Reversion lookback windows | 5, 10, 20, 50 bars (multi-window) | §4.1, §6.1–6.3 |
| Volatility percentile window | Trailing 100–250 bars | §5.1 |
| Regime transition hysteresis | 2 consecutive cycles | §5.2 |
| Liquidity-degraded volume threshold | Configurable fraction of rolling average volume (exact fraction TBD) | §5.1 |
| Mean-reversion z-score neutral band | TBD (agent-specific calibration) | §6.3 |
| Mean-reversion trending-regime discount factor | TBD (agent-specific calibration) | §6.3 |
| Price-action "near a level" proximity threshold | TBD (agent-specific calibration) | §6.4 |
| Initial agent aggregation weights | 0.25 / 0.25 / 0.25 / 0.25 (equal) | §7.1 |
| Promotion: Sharpe floor | ≥ 0, and ≥ production | §9.2 |
| Promotion: max-drawdown tolerance | ≤ production × 1.1 | §9.2 |
| Promotion: walk-forward efficiency ratio floor | ≥ 0.5 | §9.2, §10 |
| Promotion: minimum paper-trading sample size | 30 trades | §9.2 |
| Robustness: parameter perturbation range | ±10% | §10 |
| Complexity ceiling: minimum relative Sharpe improvement to justify ML over rule-based | ≥15% relative | §10 |

Several entries above are marked **TBD** deliberately — this MLD specifies the *formula and mechanism* for each, but the exact numeric calibration for agent-specific thresholds (§6.1–6.4) requires either domain-expert input or an initial backtest calibration pass, and should not be invented here without that evidence, consistent with the project's stated principle against silently inventing critical requirement values.

---

## 12. Open Items Requiring Operator or Downstream Decision

1. **Price Action agent's confidence formula** (§6.4) is the most heuristic of the four initial agents and should be revisited once initial backtest results are available — flagged as the most likely candidate for early revision.
2. **TBD calibration values** in the Model Parameter Register (§11) — mean-reversion neutral band, trending-regime discount factor, price-action proximity threshold, liquidity-degraded volume fraction — require an initial backtest calibration pass (BTD, once implemented) before being finalized.
3. **Risk-sentiment regime dimension** (§5.1) is defined but unpopulated until a Cross-Asset data source exists (ADD §6.1) — confirm this is acceptable as a placeholder dimension, or remove it from the taxonomy until the data source is actually planned.
4. **Bootstrap/resampling method for §9.3's significance test** — this MLD requires *a* resampling-based confidence interval but does not select the specific method (e.g., block bootstrap for time-series autocorrelation) — an LLD-level or TTD-level decision.
5. **Complexity-ceiling threshold (§10, 15% relative Sharpe improvement)** — confirm this bar is appropriately calibrated; too low risks unnecessary complexity creep, too high risks never adopting a genuinely better statistical/ML agent.

---

## 13. Traceability

| MLD Section | Source Requirement(s) |
|---|---|
| §4 Feature engineering | FRD-FEAT-3/4; TRD-ML-1; BTD §5.2, §5.4 |
| §5 Regime taxonomy | FRD-REGIME-1–5; ADD §5 |
| §6 Per-agent specifications | FRD-SIG-1–5; ADD §6 |
| §7 Aggregation weighting | FRD-AGG-1–6; ADD §7 |
| §8 Evaluation metrics | PRD §10; FRD-EVAL-3 |
| §9 Promotion threshold | FRD-LEARN-4; ADD §8.3 |
| §10 Overfitting guardrails | PRD §15; BTD §9 |

Every parameter in §11 should be entered into the Requirements Traceability Matrix alongside its FRD/ADD lineage, and every TBD value flagged in §11/§12 should carry an explicit calibration-pending status until resolved.

---

## 14. Document Governance

This MLD is a living document and must be reviewed whenever:
- Any TBD value in the Model Parameter Register (§11) is calibrated from real backtest data.
- The initial agent roster (ADD §6.2) changes — a new agent requires a corresponding new specification section here before implementation.
- The promotion-threshold criteria (§9.2) are exercised against a real candidate and found to be miscalibrated (too permissive or too strict) in practice.
- BTD's cost/friction model changes in a way that affects the net-of-cost metric definitions in §8.

**Next recommended step:** the operator reviews and confirms the equal-weighting proposal (§7.1) and the promotion-threshold criteria (§9.2), since both gate whether V3–V6 development has a concrete target to build against; the TBD calibration values (§11) should be resolved via an initial backtest run once BTD is implemented, rather than guessed here.
