# ADR-0004: Rule-Based / Statistical Initial 4-Agent Trading Roster

## Context & Problem Statement
The Master Context lists up to 14 candidate trading agents. Building, validating, and training all 14 agents upfront creates immense complexity, introduces unneeded data vendor dependencies (e.g. news feeds, sentiment, depth order-flow), and increases overfitting risk before the core decision pipeline is proven. We must select the initial trading agent roster for Phase 3 (V3) per FRD-SIG-5 and ADD §6.2.

## Decision
Initialize the Phase 3 Multi-Agent Decision System with an initial roster of **4 rule-based and statistical trading agents**:

1. **Trend Agent**: Moving-average relationships, directional strength indicators, and percentile-scaled confidence (MLD §6.1).
2. **Momentum Agent**: Multi-window rate of change, bounded oscillator metrics (MLD §6.2).
3. **Mean-Reversion Agent**: Z-score deviations from rolling mean, regime-discounted in strong trends (MLD §6.3).
4. **Price Action Agent**: Local swing-high/low support/resistance proximity and rejection structures (MLD §6.4).

### Key Architectural Choices:
- All 4 agents use **deterministic/statistical formulas** over OHLCV price series—zero black-box ML or LLMs in the initial live loop.
- All 4 agents output normalized confidences bounded in $[0, 1]$ and adhere to the common `AgentSignalOutput` contract.
- The Aggregator uses equal weighting ($0.25$ each) as the baseline.
- Future agents (Pattern ML, Order Flow, Options, News NLP, Sentiment) are deferred to later phases and must meet the **Complexity Ceiling** ($\ge 15\%$ relative Sharpe improvement, MLD §10).

## Consequences
### Positive
- Requires only basic OHLCV market data available in Phase 0.
- Enables end-to-end testing of the full multi-agent decision and risk pipeline (V3) without complex ML training dependencies.
- Completely explainable, reproducible, and transparent signals.

### Negative / Risks
- Strategies rely on classical price-action and statistical phenomena, which may require regime-specific filtering to avoid choppy periods (handled by the Market Regime Detector).

## Status
Accepted (Derived from ADD §6.2, MLD §6, §10, HLD §16).
