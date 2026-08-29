# Backtesting Design Document (BTD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Backtesting Design Document (BTD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from PRD v0.1, FRD v0.1, NFRD v0.1, SOW v0.1, TRD v0.1, RTLD v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, FRD v0.1, NFRD v0.1, SOW v0.1, RTLD v0.1 |

---

## 1. Purpose of This Document

The PRD (§7.7, FR-25–FR-27) and SOW (§6.2, V1) require a backtesting engine with "realistic cost/friction modeling," bias guardrails, and multiple testing methodologies, but explicitly defer the mechanics to a dedicated design document (PRD §14). This BTD is that document: it specifies **how** the backtesting engine simulates trading reality, **what** costs and frictions it models, **how** it guards against the specific biases the program has already flagged as risks (PRD §15: "backtest overfitting giving false confidence"), and **how** its output metrics and evaluation protocols (historical, out-of-sample, walk-forward, stress, Monte Carlo, regime-specific — FR-27) are defined and run.

This BTD is a prerequisite for V1 (SOW §6.2) and is the technical foundation every later phase's model promotion pipeline (FRD-LEARN-3) depends on — a weak backtesting engine would quietly undermine every validation gate built on top of it (V6–V8). It also underpins the Risk & Trading Logic Design's numeric limits (RTLD §5–§12), which assume the cost/friction modeling here is realistic enough that those limits mean what they claim to mean in live conditions.

Consistent with the project's engineering principle of not silently inventing critical requirements, every cost assumption and threshold below is a **derived, reasoned proposal**, flagged for operator sign-off in the Numeric Parameter Register (§13) — particularly because several depend on a broker that has not yet been selected (PRD §6.3).

---

## 2. Governing Principles (Carried Forward, Not Reopened)

| Principle | Source |
|---|---|
| Robustness matters more than backtest perfection — a strategy that looks flawless in-sample and fails out-of-sample is treated as a failure, not a success to be explained away. | PRD §9 |
| Backtest overfitting giving false confidence is a named, high-impact program risk. | PRD §15 |
| The engine must guard against look-ahead bias, survivorship bias, data leakage, overfitting, and unrealistic fills. | PRD FR-26 |
| Costs modeled must include brokerage, exchange fees, taxes, slippage, spread, liquidity, partial fills, latency, and market impact. | PRD FR-25 |
| Every candidate model must pass backtest → out-of-sample → walk-forward → stress → robustness → paper trading, in that order, before production consideration. | FRD-LEARN-3 |
| Results must be reproducible and documented with methodology, not just output numbers. | SOW §6.2 acceptance criteria |
| The backtesting engine itself must be tested against known-answer scenarios to prove it doesn't introduce look-ahead/survivorship bias. | NFRD NFR-TEST-4 |
| Backtest cost/friction assumptions must not diverge from the live/paper code path in a way that produces inconsistent behavior. | TRD-PIPE-3 |
| A backtest run must never be able to submit a live or paper order — environment separation is structural, not conventional. | TRD-DEPLOY-1 |

This BTD converts these principles into concrete simulation mechanics, protocols, and numbers — it does not revisit whether they hold.

---

## 3. Scope of This Document

**In scope:**
- Cost/friction model for Indian equity (NSE) trading: brokerage, statutory taxes/charges, slippage, spread, market impact, partial fills, latency.
- Fill-simulation logic (what price/quantity a simulated order actually executes at).
- Bias-prevention mechanics: look-ahead, survivorship, data leakage.
- The five FR-27 testing protocols: historical, out-of-sample, walk-forward, stress, Monte Carlo — plus regime-specific testing.
- Overfitting guardrails and the walk-forward efficiency check gating promotion.
- Reproducibility and versioning requirements for backtest runs.
- Metrics/reporting requirements, aligned to PRD §10 Success Metrics.
- The known-answer validation suite for the engine itself.

**Out of scope (belongs elsewhere):**
- Strategy/signal logic itself (what the agents generate) — HLD/LLD, Module 4/5.
- Hard risk-limit numeric values — already defined in RTLD; this BTD assumes those limits are simulated faithfully but does not redefine them.
- Paper trading (real-time simulated execution) and live execution mechanics — Execution Design; this BTD covers only the offline/historical-replay environment (TRD-DEPLOY-1's "research/backtesting" mode).
- Model training/ML pipeline internals (feature engineering, model architecture) — ML Design (MLD).
- Final broker fee schedule — depends on broker selection (open item, PRD §6.3); this BTD proposes a placeholder schedule pending that decision.

---

## 4. Backtesting Engine Objectives

The engine exists to answer one question honestly: **"If this strategy/model had traded this way over this historical period, accounting for every real-world cost and constraint, what would actually have happened?"** — not "what does the equity curve look like under favorable assumptions." Three design objectives follow directly:

1. **Conservatism over optimism** — where a cost or friction assumption is uncertain, the engine should default to the assumption that makes performance look *worse*, not better (mirrors PRD §9's "robustness > backtest perfection").
2. **Parity with live/paper code paths** — the same signal-generation, aggregation, risk-engine, and position-sizing logic used live must run inside the backtest, not a simplified stand-in, so a backtest result is evidence about the real system, not a separate approximation of it (TRD-PIPE-3).
3. **Falsifiability** — every run must be capable of failing clearly (e.g., known-answer tests, out-of-sample degradation) rather than being structured in a way that always produces a flattering result.

---

## 5. Data Requirements and Bias Controls

### 5.1 Historical Data Requirements
- OHLCV at the timeframes the strategy under test will trade (per PRD FR-1); depth/order-book history only where an agent's logic depends on it.
- Corporate-action-adjusted price series (splits, bonuses, dividends) with the adjustment method documented per dataset, since silently mixing adjusted and unadjusted series is a data-leakage risk in itself.
- An **as-of-date index universe** for any strategy that selects instruments from a list (e.g., "top 50 NSE stocks by liquidity") — see §5.3.

### 5.2 Look-Ahead Bias Prevention (FR-26)
- Every feature/signal computed for a given bar may only use data with a timestamp **strictly earlier than** that bar's decision point — enforced structurally (e.g., a point-in-time data access layer that physically cannot return future rows), not by convention or reviewer discipline.
- Fundamental/event data (earnings, corporate announcements) must be timestamped to **actual public release time**, not the date the underlying event pertains to — a common, subtle look-ahead source (e.g., using a quarter's revenue figure on the quarter's last day rather than the date it was actually reported).
- Fills are simulated against the **next available bar after the decision**, never the same bar the decision was made on (a decision made on bar close cannot fill at that same bar's close) — see §7.

### 5.3 Survivorship Bias Prevention (FR-26)
- The instrument universe for any given historical date must be reconstructed **as it existed on that date** (including since-delisted, merged, or renamed companies), not filtered down to "instruments that still exist today." Using today's NIFTY 50 constituent list to backtest five years ago is treated as a bias defect, not an acceptable simplification.
- Where a fully accurate historical constituent list is unavailable for the initial data vendor, this must be explicitly logged as a **known limitation** on every affected backtest report (§12), not silently ignored.

### 5.4 Data Leakage Prevention (FR-26)
- Any statistic used for feature normalization, scaling, or model training (e.g., mean/std of a rolling window, a percentile rank) must be computed using **only data available up to that point in time** — never fit once over the full historical dataset and then applied backward.
- Train/validation/test/out-of-sample splits (§9) must be **chronological**, never randomly shuffled, since random shuffling of time-series data leaks future information into training via autocorrelation.
- Per NFR-DATA-3: all historical data used for backtesting/training undergoes a documented integrity review (automated checks plus a manual spot-check log) for known bias sources before use.

---

## 6. Cost and Friction Model (FR-25)

Every cost component below is applied to every simulated fill. Because the broker is not yet selected (PRD §6.3), the exact brokerage figures are **placeholders based on typical Indian discount-broker/exchange-regulatory schedules**, flagged for confirmation once a broker is chosen — but the *categories* below (brokerage, STT, exchange charges, stamp duty, GST, DP charges where relevant) are structural and will not change regardless of which broker is selected, since most are statutory.

| Cost Component | Applies To | Proposed Modeling Approach |
|---|---|---|
| **Brokerage** | Every executed order (entry and exit) | Modeled as `min(flat_fee, pct_of_turnover)` per order, consistent with common Indian discount-broker pricing — proposed default ₹20 flat or 0.03% of turnover, whichever is lower, per executed order. At this project's ₹10,000–₹2,000-per-trade scale, this is a **material** cost (₹20 on a ₹2,000 position is 1% per side) and must never be waived or approximated as zero. |
| **Securities Transaction Tax (STT)** | Equity delivery: both legs; equity intraday: sell leg only | Proposed default: 0.1% (delivery, both sides), 0.025% (intraday, sell side) — statutory rates change periodically and must be reconciled against the current schedule at implementation time, not hardcoded from this document indefinitely. |
| **Exchange transaction charges** | Every executed order | Proposed default: ~0.00297% of turnover (NSE) — small but non-zero; excluding it entirely would be an "unrealistic fill" per FR-26. |
| **SEBI turnover fee** | Every executed order | Proposed default: ~0.0001% of turnover. |
| **Stamp duty** | Buy leg only | Proposed default: 0.015% (delivery) / 0.003% (intraday) of turnover, buyer-side only, per current Indian stamp-duty rules on securities. |
| **GST** | On brokerage + exchange transaction charges | Proposed default: 18%. |
| **Spread cost** | Every fill | Modeled as half the quoted (or historically estimated) bid-ask spread applied against the trader on entry and again on exit — i.e., buy fills slightly above mid, sell fills slightly below mid. Where tick-level bid/ask history is unavailable, a proxy (e.g., a fraction of the bar's high-low range) must be used and explicitly documented as a proxy, not presented as measured spread. |
| **Slippage** | Every fill | Modeled as an additional adverse price movement beyond spread, proposed default **5–10 basis points (0.05%–0.10%) of trade value** for liquid large/mid-cap NSE instruments at this position size, scaled up for lower-liquidity instruments per §6.1. This is a placeholder pending calibration against real paper-trading fills (V4) — backtest slippage assumptions must be revisited once real execution data exists, not treated as permanently fixed. |
| **Market impact** | Every fill | At this project's small position sizes (RTLD §9: max ₹2,000/position) on liquid NSE instruments, market impact beyond spread/slippage is expected to be negligible and is proposed as **not separately modeled** initially — but the engine must expose a configurable market-impact function so this can be added without a redesign if larger position sizes are ever approved (RTLD §15 capital scaling). |
| **Partial fills** | Any order sized close to available liquidity | The engine must be able to simulate a fill smaller than the requested quantity when historical volume/depth data indicates insufficient liquidity at the decision point, consistent with FR-25; an unfilled remainder is not silently assumed to fill later unless the strategy logic explicitly re-submits. |
| **Latency** | Every order | The signal-to-fill delay is modeled explicitly (§7) rather than assuming instantaneous execution at the signal price — this is itself a friction cost, not just a technical nuance. |

### 6.1 Liquidity-Scaled Slippage
Slippage should scale with the ratio of order size to available volume at the decision point (consistent with RTLD §11's liquidity threshold), rather than being a single flat number across all instruments. Proposed tiers (placeholder, pending calibration):

| Order size as % of avg. bar volume | Slippage adjustment |
|---|---|
| < 1% | Base slippage (5–10 bps) |
| 1–5% | Base slippage × 2 |
| > 5% | Base slippage × 4, or reject the fill as unrealistic (mirrors RTLD's liquidity block) |

---

## 7. Fill Simulation Logic

To avoid the same-bar look-ahead risk (§5.2), fills follow a fixed, documented rule:

1. A decision (BUY/SELL, per RTLD §13) generated using data available **through bar T** is assumed submittable only after bar T closes.
2. The simulated fill occurs at **bar T+1's open**, adjusted by spread and slippage (§6), not at bar T's close or at a theoretically ideal price within bar T+1.
3. If bar T+1's open gaps beyond a configurable threshold from the last observed price (e.g., a large overnight gap), the fill is still simulated at that gapped price — gaps are real risk, not something the engine should smooth over.
4. Stop-loss and target exits are checked against bar T+1 onward using the bar's high/low range, with a documented, consistent tie-breaking rule when a single bar's range would have hit both the stop and the target (proposed default: assume the worse outcome for the strategy — stop hit first — unless intraday tick data is available to determine actual sequence).
5. For any timeframe faster than the bar resolution available in historical data, the engine must refuse to simulate at a precision it cannot honestly support, rather than interpolating a fill inside a bar it has no visibility into.

This bar-T+1-open convention is a deliberate conservatism choice (§4 objective 1) — it will generally understate performance versus a same-bar-fill assumption, which is the correct direction to be wrong in.

---

## 8. Testing Protocols (FR-27)

Per FRD-LEARN-3, these run in a fixed order; a candidate that fails one does not proceed to the next.

### 8.1 Historical (In-Sample) Backtest
Full strategy logic run across the available historical dataset, chronologically, using the fill/cost model above. Establishes a baseline but is **never** used alone to justify promotion (PRD §9 — "robustness > backtest perfection").

### 8.2 Out-of-Sample Test
- Chronological split, proposed default **70% in-sample / 30% out-of-sample**, with the split point fixed **before** any parameter tuning begins.
- Parameters must be locked at the end of in-sample tuning; any subsequent adjustment based on out-of-sample results invalidates that out-of-sample test and requires a fresh, unseen out-of-sample period — re-running against the same held-out data after tuning is data leakage in substance, even though it isn't a look-ahead bug in the code.

### 8.3 Walk-Forward Test
- Rolling-window protocol, proposed default: **train on a 6-month window, test on the following 1-month window, then roll forward by 1 month**, repeated across the full dataset.
- Out-of-sample results across all folds are aggregated into a single walk-forward performance record — a strategy that performs well in some folds and poorly in others is reported as such, not averaged into a misleadingly smooth headline number.
- **Walk-Forward Efficiency Ratio** = (aggregate out-of-sample performance) / (aggregate in-sample performance). Proposed gating threshold: **≥ 0.5** to proceed to stress testing — a ratio well below 1.0 is expected and acceptable; a ratio near or below 0 indicates the in-sample result was primarily overfitting.

### 8.4 Stress Testing
- The strategy is run specifically across known historical stress periods relevant to Indian equity markets (e.g., sharp broad-market drawdowns, high-volatility regimes) — exact period list to be maintained as a living reference set, not fixed permanently in this document.
- Synthetic stress scenarios are also applied: simulated gap-down shocks, volatility spikes, and a simulated broker/data-feed outage during an open position, to test how the strategy (and the RTLD risk controls wrapping it) behave under conditions historical data alone may not fully represent.

### 8.5 Monte Carlo Testing
- The realized trade sequence (not the price series) is resampled with replacement (bootstrap) to generate a distribution of possible equity curves, proposed default **≥1,000 resampled paths**.
- Reported outputs: distribution of max drawdown, distribution of final equity, and an estimated probability of breaching the RTLD hard-drawdown limits (RTLD §8) under the resampled trade-order variation alone — this directly tests sequence-risk, not just average performance.

### 8.6 Regime-Specific Testing
- Results are additionally partitioned by the regime classification the strategy would have detected at each point (Module 3, per FRD-REGIME-1) and reported per regime bucket (trending/ranging, high/low volatility, bullish/bearish).
- A strategy that only performs acceptably in one regime is not disqualified outright, but this must be stated explicitly in the report (§12) — it directly informs the "Consistency" success metric in PRD §10 and the "positive expectancy across at least 2 distinct market regimes" capital-scaling criterion in RTLD §15.

---

## 9. Overfitting Guardrails

Beyond the walk-forward efficiency check (§8.3), the engine and process enforce:

- **Parameter-count discipline** — the number of free/tunable parameters in a strategy must be small relative to the number of independent trades it produces in-sample (proposed heuristic: at least ~20 in-sample trades per free parameter); strategies with many parameters and few trades are flagged as high overfitting risk regardless of their in-sample metrics.
- **Multiple-testing correction** — where many parameter combinations or many candidate strategies are tested against the same historical data (a parameter sweep or strategy search), the best-performing result's significance must be discounted for the number of trials (e.g., a deflated/adjusted Sharpe ratio), not reported at face value — testing 200 variants and reporting only the best one's raw Sharpe ratio is treated as a methodology defect.
- **No re-tuning after out-of-sample exposure** (§8.2) — enforced as a process rule, logged as part of the run's audit trail (§11), so a violation is detectable after the fact even if not preventable in real time.
- **Complexity vs. simplicity preference** — where two candidate strategies show statistically indistinguishable out-of-sample/walk-forward performance, the simpler one (fewer parameters, fewer conditional branches) is preferred, consistent with PRD §9's robustness-over-perfection principle.

---

## 10. Reproducibility Requirements

Every backtest run must be fully reconstructable after the fact, mirroring BR-7's full-auditability requirement for live decisions:

| Element | Requirement |
|---|---|
| **Data version** | Every run records a content hash/version identifier of the exact historical dataset used, including the point-in-time universe (§5.3). |
| **Code/strategy version** | Every run records the exact strategy/model version and configuration (parameters, cost-model version from §13) used. |
| **Determinism** | Given identical data version, code version, and configuration, a re-run must produce byte-identical results — any source of nondeterminism (e.g., unseeded randomness in Monte Carlo resampling) must use a recorded seed. |
| **Report linkage** | Every reported metric must be traceable back to the specific run (data + code + config triple) that produced it — a number without this linkage is not usable for a promotion decision (feeds FRD-LEARN-3/FR-23). |

---

## 11. Engine Validation (Known-Answer Testing)

Per NFR-TEST-4/TRD-CI-3, the backtesting engine itself is tested before it is trusted with real strategies:

- A **synthetic dataset with a known, hand-computed optimal outcome** (e.g., a constructed price series where the correct trade sequence and its exact resulting P&L, after costs, is known in advance) is run through the engine, and its output must match the known answer within a defined tolerance.
- Dedicated regression tests specifically probe for look-ahead bias (e.g., a synthetic series where using future data would produce a materially different, detectably "too good" result) and survivorship bias (e.g., a synthetic universe including a delisted instrument).
- This known-answer suite runs as part of the standard automated test suite (TRD-CI-3), not as a one-off manual validation, and must be re-run whenever the fill/cost model (§6–§7) changes.

---

## 12. Metrics and Reporting

Every backtest/out-of-sample/walk-forward/stress/Monte Carlo run produces a report — never just a headline number — consistent with SOW §6.2's acceptance criteria ("documented with methodology, not just output numbers"):

- **Metrics**, aligned to PRD §10: Sharpe ratio, Sortino ratio, expectancy, profit factor, maximum drawdown, win/loss consistency, NO TRADE frequency and (where evaluable) its correctness, regime-partitioned performance (§8.6).
- **Sample-size caveats stated explicitly** wherever a metric is computed from a small number of trades — a Sharpe ratio from 8 trades is reported with that caveat attached, not presented with the same confidence as one from 200 trades.
- **Known limitations disclosed** on every report — e.g., survivorship-bias gaps in the instrument universe (§5.3), slippage-model uncertainty (§6), or any proxy used in place of unavailable data (e.g., spread proxy).
- **Cost breakdown disclosed separately** from gross P&L — gross return, total cost drag (brokerage + taxes + spread + slippage), and net return are all reported, so a strategy's apparent edge can be checked against how much of it costs consume.

---

## 13. Numeric Parameter Register

All values below are **proposed defaults derived in this BTD** and must be explicitly confirmed, adjusted, or rejected by the operator — several also depend on the broker selection (PRD §6.3), which is still open.

| ID | Parameter | Proposed Value | Section | Status |
|---|---|---|---|---|
| BTD-1 | Brokerage per executed order | min(₹20 flat, 0.03% of turnover) | §6 | ☐ Pending — depends on broker selection |
| BTD-2 | STT (delivery, both legs) | 0.1% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-3 | STT (intraday, sell leg) | 0.025% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-4 | Exchange transaction charges | ~0.00297% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-5 | SEBI turnover fee | ~0.0001% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-6 | Stamp duty (delivery / intraday, buy leg) | 0.015% / 0.003% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-7 | GST on brokerage + exchange charges | 18% | §6 | ☐ Pending — statutory, confirm current rate |
| BTD-8 | Base slippage (liquid instruments) | 5–10 bps of trade value | §6 | ☐ Pending — placeholder until calibrated against V4 paper-trading data |
| BTD-9 | Liquidity-scaled slippage tiers | 1×/2×/4× base at <1% / 1–5% / >5% of bar volume | §6.1 | ☐ Pending operator sign-off |
| BTD-10 | In-sample / out-of-sample split | 70% / 30%, chronological | §8.2 | ☐ Pending operator sign-off |
| BTD-11 | Walk-forward window | Train 6 months / test 1 month, roll monthly | §8.3 | ☐ Pending operator sign-off |
| BTD-12 | Walk-forward efficiency ratio gate | ≥ 0.5 | §8.3 | ☐ Pending operator sign-off |
| BTD-13 | Monte Carlo resample count | ≥ 1,000 paths | §8.5 | ☐ Pending operator sign-off |
| BTD-14 | Parameter-to-trade ratio heuristic | ≥ 20 in-sample trades per free parameter | §9 | ☐ Pending operator sign-off |
| BTD-15 | Backtest cycle time target | < 24 hours per candidate | §14 (= NFR-PERF-4) | ☐ Pending — also depends on compute-resource decision |

All BTD-* values must be externalized as versioned configuration (consistent with RTLD's NFR-MAINT-3 treatment), and every backtest report (§12) must record which version of this register was in effect for that run (§10).

---

## 14. Performance and Compute Considerations

Per NFR-PERF-4, a full out-of-sample + walk-forward + stress-test cycle for one candidate should complete within a practical research-iteration time — proposed target **under 24 hours** on the operator's available compute (BTD-15), acknowledged as a placeholder pending a compute-resource decision (SOW §12 item 5 / BRD §11 item 5: whether the Research Brain gets its own budget). This BTD does not select infrastructure — that is a TTD/compute-sizing decision (TRD-COMPUTE-3) — but flags that the testing protocols in §8, run in full (especially Monte Carlo at ≥1,000 paths and walk-forward across many folds), are the primary driver of that compute requirement, so compute sizing should be validated against §8's actual protocol definitions, not against a simplified estimate.

---

## 15. Open Items Requiring Operator or Downstream Decision

1. **Confirm or adjust every "Pending" row in §13** — this BTD proposes defaults; none should be silently accepted.
2. **Broker selection** (PRD §6.3) — directly resolves BTD-1's brokerage model and may affect available historical data quality/cost.
3. **Slippage calibration** (BTD-8/9) — genuinely a placeholder until V4 paper-trading data exists to calibrate against; the backtest engine's promotion-gating role (FRD-LEARN-3) before V4 must rely on this placeholder, with that limitation disclosed on every affected report (§12).
4. **Historical data vendor selection** — affects the completeness of the point-in-time universe (§5.3) and whether survivorship-bias gaps must be disclosed as a known limitation or can be fully closed.
5. **Stress-period reference set** (§8.4) — needs to be defined and maintained; not fixed in this document.
6. **Compute-resource/budget decision** (§14) — carried from BRD §11 item 5; determines whether the 24-hour cycle-time target (BTD-15) is realistic as proposed.

---

## 16. Traceability

| BTD Section | Source Requirement(s) |
|---|---|
| §5 Data requirements / bias controls | PRD FR-26; NFRD NFR-DATA-3 |
| §6 Cost/friction model | PRD FR-25 |
| §7 Fill simulation | PRD FR-25/FR-26; TRD-PIPE-3 |
| §8 Testing protocols | PRD FR-27; FRD-LEARN-3 |
| §9 Overfitting guardrails | PRD §9, §15 (named program risk) |
| §10 Reproducibility | BRD BR-7 (auditability, applied to backtesting) |
| §11 Engine validation | NFRD NFR-TEST-4; TRD-CI-3 |
| §12 Metrics/reporting | PRD §10; SOW §6.2 acceptance criteria |
| §13 Parameter register | PRD FR-25 (cost categories); statutory Indian market charges |
| §14 Compute considerations | NFRD NFR-PERF-4; TRD-COMPUTE-2/3 |
| §15 Open items | PRD §6.3; BRD §11 item 5; SOW §12 item 5 |

Every model promotion decision (FRD-LEARN-3, FR-23) that cites backtest/out-of-sample/walk-forward/stress/Monte Carlo results must cite the specific run identifier (§10) and BTD parameter-register version (§13) that produced them, so an audit can distinguish "this strategy was validated under the current cost/bias assumptions" from "this strategy was validated under assumptions later found to be wrong."

---

## 17. Document Governance

This BTD is a living document and must be reviewed whenever:
- Any value in the Numeric Parameter Register (§13) is proposed to change, especially once a broker is selected or real slippage data (V4) becomes available.
- The historical data vendor changes, since §5 bias controls are only as good as the underlying data's point-in-time accuracy.
- A known-answer test (§11) fails after a change to the fill/cost model.
- The RTLD (risk limits) changes in a way that affects what "realistic" position sizing/liquidity constraints mean in the cost model (§6.1).

**Next recommended step:** the operator reviews and signs off on §13, in parallel with resolving broker selection (PRD §6.3) and the compute-budget question (BRD §11 item 5); the known-answer validation suite (§11) should be built and passing before any strategy-specific backtest result (V1, SOW §6.2) is treated as meaningful.