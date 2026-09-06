# Functional Requirements Document (FRD)
## AI Trader — Autonomous Intelligent Trading System

| | |
|---|---|
| **Document Type** | Functional Requirements Document (FRD) |
| **Project** | AI Trader — Autonomous Intelligent Trading System |
| **Status** | Draft v0.1 — for review |
| **Owner** | System Owner / Operator (the user) |
| **Prepared by** | Claude (Anthropic), derived from Master Project Context v1, PRD v0.1, BRD v0.1, and SOW v0.1 |
| **Date** | 2026-08-29 |
| **Parent Documents** | AI Trader PRD v0.1, AI Trader BRD v0.1, AI Trader SOW v0.1 |

---

## 1. Purpose of This Document

The PRD states *what the product must achieve* at a summary level; the BRD states *why*, under what business rules; the SOW states *how delivery is phased*. This FRD decomposes the PRD's functional requirements (§7) into detailed, testable functional specifications, organized by system module, with inputs, outputs, behavior, and acceptance conditions for each.

This FRD is implementation-agnostic: it does not prescribe specific technologies, frameworks, or algorithms (that belongs in the HLD/TTD/LLD/MLD/ADD). It specifies **what each module must do**, not how it is built.

Each requirement carries an ID (`FRD-<Module>-<Number>`) for traceability into the Requirements Traceability Matrix, test cases, and code.

---

## 2. Scope of This FRD

This FRD covers the functional behavior of every module implied by the PRD's decision architecture (PRD §7) and Master Context §10–§11, organized into ten functional modules:

1. Data Ingestion & Validation
2. Feature Engineering
3. Market Regime Detection
4. Signal Generation (Multi-Agent)
5. Signal Aggregation & Trade Quality Scoring
6. Risk Engine
7. Supervisor / Decision Gate
8. Execution Engine
9. Trade Evaluation & Explainability
10. Learning & Model Lifecycle Management

Plus two cross-cutting functional areas:

11. Dashboard & Human Control
12. Capital & Growth Management

Per SOW §6, not every module is built in every phase — this FRD specifies full target functional behavior; the phase in which each requirement becomes applicable is noted where relevant, and modules should be read alongside the SOW's phase gating.

---

## 3. Functional Requirement Notation

Each requirement below uses:

- **ID** — unique identifier.
- **Requirement** — the functional behavior required.
- **Trigger/Input** — what causes this behavior or what data it consumes.
- **Output** — what the module produces.
- **Applicable Phase(s)** — earliest SOW phase(s) where this applies (per SOW §6).
- **Notes** — constraints, edge cases, or open items.

---

## 4. Module 1 — Data Ingestion & Validation

| ID | Requirement |
|---|---|
| FRD-DATA-1 | The system shall ingest market data including OHLCV, tick data, market depth/order book, bid/ask spread, and liquidity indicators for configured instruments. |
| FRD-DATA-2 | The system shall ingest derivatives data (options chain, implied volatility, open interest, futures, futures basis, options positioning) for configured instruments where applicable. |
| FRD-DATA-3 | The system shall ingest fundamental/event data (earnings, corporate announcements, economic events, macroeconomic data). |
| FRD-DATA-4 | The system shall ingest alternative data (financial news, sentiment, institutional activity, cross-asset/global market data) where a corresponding agent (Module 4) consumes it. |
| FRD-DATA-5 | The system shall attach temporal context (time of day, day of week, market session, expiry period, event window) to ingested data. |
| FRD-DATA-6 | The system shall validate incoming data for staleness, gaps, and anomalous values before it is used by any downstream module. |
| FRD-DATA-7 | The system shall flag and quarantine data that fails validation, and shall prevent quarantined data from silently influencing decisions. |
| FRD-DATA-8 | The system shall support adding or removing a data source without requiring changes to downstream modules' interfaces (modularity, per PRD §6.1/NFR Modularity). |
| FRD-DATA-9 | On detection of stale or missing critical data for an instrument, the system shall be capable of suppressing new decisions for that instrument until data quality is restored (feeds Module 6 Risk Engine, FRD-RISK-9). |

**Applicable Phase(s):** FRD-DATA-1, 5, 6, 7, 8 — V0. FRD-DATA-2, 3, 4 — as corresponding agents are introduced (V2–V3 onward). FRD-DATA-9 — V3 onward (requires Risk Engine).

**Open item:** Exact data vendor(s) and their entitlements are not yet selected (carried from PRD §6.3/§14) — this affects which of FRD-DATA-1–4 are achievable at each phase.

---

## 5. Module 2 — Feature Engineering

| ID | Requirement |
|---|---|
| FRD-FEAT-1 | The system shall compute technical features (technical indicators, momentum, volatility, trend, support/resistance, market structure, price patterns) from validated market data. |
| FRD-FEAT-2 | The system shall compute derivatives-derived features (e.g., implied volatility surface characteristics, open interest changes) where derivatives data is available. |
| FRD-FEAT-3 | The system shall version every feature set so that a given historical decision can be reproduced using the exact feature definitions in effect at that time. |
| FRD-FEAT-4 | The system shall make computed features available to both the Trading Brain (live features) and Research Brain (historical/offline features) without duplicating feature-computation logic (single source of truth). |
| FRD-FEAT-5 | The system shall log which features were available and used as input to each decision (feeds Module 9 Explainability). |

**Applicable Phase(s):** V1 (backtesting features) through V2 (ML features) onward.

---

## 6. Module 3 — Market Regime Detection

| ID | Requirement |
|---|---|
| FRD-REGIME-1 | The system shall classify the current market regime along dimensions including: trending vs. ranging, high- vs. low-volatility, bullish vs. bearish, risk-on vs. risk-off, and liquidity conditions. |
| FRD-REGIME-2 | The system shall detect regime transitions and flag when a transition has occurred, distinct from steady-state regime classification. |
| FRD-REGIME-3 | The system shall make the current regime classification available to all Module 4 signal-generation agents and to Module 6 Risk Engine. |
| FRD-REGIME-4 | The system shall log the regime classification associated with every decision (feeds Module 9 Explainability, PRD §7.5). |
| FRD-REGIME-5 | The system shall support evaluating strategy/model performance broken down by detected regime (feeds Module 10 Learning and PRD §10 Success Metrics "performance by market regime"). |

**Applicable Phase(s):** V3 onward.

**Open item:** the exact regime taxonomy (number/definition of regimes) must be validated during HLD/MLD, not assumed — this FRD specifies the functional categories from the Master Context, not a final regime schema.

---

## 7. Module 4 — Signal Generation (Multi-Agent)

| ID | Requirement |
|---|---|
| FRD-SIG-1 | The system shall support a modular set of specialized signal-generating agents (candidates per Master Context §10: Signal, Trend, Momentum, Mean-Reversion, Pattern, Price Action, Order Flow, Order Book, Options, Volatility, News, Sentiment, Cross-Asset, Event), where each agent can be enabled/disabled independently. |
| FRD-SIG-2 | Each enabled agent shall produce a structured output for a given instrument/timeframe consisting of, at minimum: a directional view (or explicit "no view"), a confidence level, and the features/inputs it used. |
| FRD-SIG-3 | An agent's failure or unavailability shall not crash the system; the Signal Aggregation module (Module 5) shall treat a failed agent as "no view" rather than blocking the decision pipeline, unless the missing agent is designated mandatory (open item — mandatory-agent list to be defined in HLD). |
| FRD-SIG-4 | The system shall log each agent's output (or absence of output) for every evaluation cycle (feeds Module 9 Explainability, PRD §7.5 "which signals contributed / disagreed"). |
| FRD-SIG-5 | The initial agent roster to be implemented shall be determined during HLD (per SOW §6.4 V3), not assumed to be the full candidate list; this FRD specifies the functional contract each agent must satisfy if implemented, not which agents are built first. |

**Applicable Phase(s):** V3 onward (initial roster); additional agents may be added incrementally in later phases per FRD-DATA-8/modularity.

---

## 8. Module 5 — Signal Aggregation & Trade Quality Scoring

| ID | Requirement |
|---|---|
| FRD-AGG-1 | The system shall aggregate outputs from all active Module 4 agents into a single expected-value assessment for a candidate opportunity. |
| FRD-AGG-2 | The system shall compute a trade quality score reflecting the strength and agreement (or disagreement) of contributing signals. |
| FRD-AGG-3 | The system shall evaluate, for each candidate opportunity, multiple candidate timeframes and select the timeframe assessed as most appropriate for the current regime/opportunity (Dynamic Timeframe Intelligence, PRD §7.2 FR-6). |
| FRD-AGG-4 | Where no candidate opportunity meets the minimum trade quality threshold, the system shall produce a NO TRADE recommendation rather than forcing a selection among low-quality candidates (PRD FR-8; BRD BR-3). |
| FRD-AGG-5 | The system shall log the aggregation methodology output (contributing agents, weights/scores, disagreement) for every cycle, whether or not it results in a trade recommendation. |
| FRD-AGG-6 | The minimum trade quality threshold referenced in FRD-AGG-4 shall be a configurable, auditable parameter — not a hardcoded or opaque value. |

**Applicable Phase(s):** V3 onward.

---

## 9. Module 6 — Risk Engine

This module implements PRD §7.3 and is the primary mechanism enforcing BRD BR-1 and BR-4 (capital-preservation precedence; deterministic safety independent of AI judgment).

| ID | Requirement |
|---|---|
| FRD-RISK-1 | The system shall calculate expected risk and expected reward for every candidate trade before it can be approved. |
| FRD-RISK-2 | The system shall determine position size using a deterministic, auditable, configurable sizing rule (e.g., fixed-fractional, volatility-adjusted — exact method to be defined in Risk & Trading Logic Design). |
| FRD-RISK-3 | The system shall enforce a maximum risk per trade, independent of any agent's confidence score. |
| FRD-RISK-4 | The system shall enforce a maximum daily loss limit; upon breach, the system shall block all new trade entries for the remainder of the trading day/session. |
| FRD-RISK-5 | The system shall enforce a maximum drawdown limit; upon breach, the system shall halt trading and require explicit operator action to resume (not automatic resumption). |
| FRD-RISK-6 | The system shall enforce a maximum portfolio exposure limit and a maximum position size limit. |
| FRD-RISK-7 | The system shall enforce a maximum number of simultaneous open positions and a maximum number of trades within a defined period. |
| FRD-RISK-8 | The system shall implement consecutive-loss protection that reduces size or pauses trading after a configurable number of consecutive losing trades. |
| FRD-RISK-9 | The system shall reduce risk exposure or block trading in response to: abnormal volatility, insufficient liquidity, stale/missing data (per FRD-DATA-9), or detected broker/API failure. |
| FRD-RISK-10 | The system shall enforce a minimum model-confidence threshold below which a candidate trade cannot be approved regardless of trade quality score. |
| FRD-RISK-11 | All limits in FRD-RISK-3 through FRD-RISK-10 shall be implemented as deterministic logic that does not depend on, and cannot be overridden by, any AI/LLM/probabilistic component (BRD BR-4). |
| FRD-RISK-12 | The system shall support an emergency kill switch that immediately blocks all new order submission when activated, independent of any other module's state. |
| FRD-RISK-13 | The system shall log every risk-limit evaluation (pass or block) with the specific limit(s) evaluated and the outcome (feeds Module 9 Explainability). |
| FRD-RISK-14 | Numeric values for all limits in this module (max trade risk, max daily loss, max drawdown, etc.) are **not specified in this FRD** and must be formally defined in the Risk & Trading Logic Design document, consistent with PRD §9 (the ₹1,000 figure is a tolerance ceiling, not a limit value). |

**Applicable Phase(s):** V3 (simulated risk engine) through V5 (live enforcement) and beyond.

---

## 10. Module 7 — Supervisor / Decision Gate

| ID | Requirement |
|---|---|
| FRD-SUP-1 | The system shall require every candidate action (from Module 5) to pass through the Supervisor gate before reaching the Execution Engine (Module 8). |
| FRD-SUP-2 | The Supervisor shall consult the Risk Engine (Module 6) and shall not approve any action that the Risk Engine has blocked. |
| FRD-SUP-3 | The Supervisor shall produce exactly one of four outcomes per evaluation cycle per instrument: BUY, SELL, HOLD, or NO TRADE. |
| FRD-SUP-4 | The Supervisor shall record the full decision chain (regime → signals → aggregation → risk evaluation → final decision) as a single auditable unit (a "decision record"). |
| FRD-SUP-5 | If the kill switch (FRD-RISK-12) or emergency STOP (Module 11) is active, the Supervisor shall be constrained to output HOLD or NO TRADE / exit-only actions regardless of upstream recommendations. |
| FRD-SUP-6 | The Supervisor's approval logic shall itself be auditable and shall not silently override or ignore a Risk Engine block. |

**Applicable Phase(s):** V3 onward.

---

## 11. Module 8 — Execution Engine

| ID | Requirement |
|---|---|
| FRD-EXEC-1 | The system shall authenticate with the configured broker and maintain a monitored connection state. |
| FRD-EXEC-2 | The system shall place, modify, and cancel orders corresponding to Supervisor-approved decisions. |
| FRD-EXEC-3 | The system shall track order status (submitted, filled, partially filled, rejected, cancelled) and reconcile it against the system's internal position/portfolio state. |
| FRD-EXEC-4 | The system shall track position and portfolio state (open positions, average entry, unrealized P&L, realized P&L). |
| FRD-EXEC-5 | The system shall detect and prevent duplicate order submission for the same decision (e.g., on retry after a timeout). |
| FRD-EXEC-6 | The system shall detect broker/API disconnection or failure and shall not silently continue as if orders succeeded; it shall escalate to the Risk Engine (FRD-RISK-9) and, where configured, to human notification. |
| FRD-EXEC-7 | The system shall support reconnection logic that reconciles state (open orders, positions) after a disconnection before resuming normal operation. |
| FRD-EXEC-8 | The system shall support emergency liquidation of open positions on operator command or kill-switch activation, where market conditions allow. |
| FRD-EXEC-9 | The Execution Engine shall prioritize correctness and safety (accurate state, no duplicate/erroneous orders) over speed, unless a specific validated strategy has a documented low-latency requirement (PRD §7.4 FR-17). |
| FRD-EXEC-10 | The system shall log every order lifecycle event (submission, modification, cancellation, fill, rejection) with timestamps, for audit and evaluation purposes. |

**Applicable Phase(s):** FRD-EXEC-1–7, 9, 10 apply from V4 (simulated) with live semantics from V5. FRD-EXEC-8 applies from V5.

---

## 12. Module 9 — Trade Evaluation & Explainability

This module implements PRD §7.5 and enforces BRD BR-7 (full auditability).

| ID | Requirement |
|---|---|
| FRD-EVAL-1 | The system shall produce a decision record for every Supervisor output (including NO TRADE) capturing: inputs used, computed features, regime classification, individual agent outputs, aggregation result, risk evaluation result, and final decision. |
| FRD-EVAL-2 | The system shall distinguish, within each decision record, between (a) actual model inputs/outputs, (b) calculated/derived features, and (c) any post-hoc natural-language explanation, so that (c) is never presented as if it were (a) or (b). |
| FRD-EVAL-3 | For every completed trade, the system shall compare expected outcome (at entry) against actual outcome (at exit) and classify variance drivers among: bad signal, bad timing, bad position sizing, bad execution, unexpected event, regime change, data problem, or model problem. |
| FRD-EVAL-4 | The system shall support operator queries such as "why was this decision made," "what regime was detected," "which signals agreed/disagreed," "what was the confidence," and "what risk constraints were evaluated," returning answers grounded in the decision record (FRD-EVAL-1), not fabricated. |
| FRD-EVAL-5 | The system shall retain decision records and trade evaluations for the full operating history of the system (retention period/storage approach to be defined in DDD). |
| FRD-EVAL-6 | The system shall never generate an explanation for a decision that cannot be traced to an actual decision record; if no record exists, the system shall state that explicitly rather than reconstructing a plausible-sounding rationale. |

**Applicable Phase(s):** V3 onward (decision-record structure); V5 onward for live-trade evaluation.

---

## 13. Module 10 — Learning & Model Lifecycle Management

This module implements PRD §7.6/§7.7 and enforces BRD BR-6 (no unvalidated model touches live capital).

| ID | Requirement |
|---|---|
| FRD-LEARN-1 | The system shall maintain a Research Brain environment logically and operationally separated from the live Trading Brain, such that the Research Brain cannot submit live orders or alter live risk parameters directly. |
| FRD-LEARN-2 | The system shall support generation of candidate models/strategies informed by Module 9 trade evaluations (successful patterns and failure causes). |
| FRD-LEARN-3 | The system shall run each candidate through, in order: backtesting, out-of-sample testing, walk-forward testing, stress testing, robustness testing, and paper trading, before it may be considered for production. |
| FRD-LEARN-4 | The system shall compare a candidate's validated performance against the current production model using the metrics defined in PRD §10, and shall require the candidate to meet or exceed a defined promotion threshold (threshold to be defined in MLD). |
| FRD-LEARN-5 | The system shall require a defined risk review step before any candidate may be promoted to production (per PRD §18 Model Promotion Pipeline); where human sign-off is required per operator decision (open item, BRD §11 item 6), promotion shall be blocked pending that sign-off. |
| FRD-LEARN-6 | The system shall version every promoted model and retain prior production versions to enable rollback. |
| FRD-LEARN-7 | The system shall monitor a deployed model's live/paper performance against its expected (validated) performance and shall automatically trigger rollback to the prior production version if degradation exceeds a defined threshold. |
| FRD-LEARN-8 | The system shall log every promotion, rejection, and rollback event with the evidence/metrics that drove the decision. |
| FRD-LEARN-9 | Where reinforcement learning is used, its reward function shall incorporate return, risk, drawdown, volatility, transaction costs, slippage, and consistency — not raw profit alone — and RL training/evaluation shall occur only within the Research Brain environment (never against unrestricted live capital), per PRD §7.6 FR-24. |

**Applicable Phase(s):** V6 (evaluation pipeline, Research Brain isolation) through V7 (full promotion pipeline, rollback).

---

## 14. Module 11 — Dashboard & Human Control

| ID | Requirement |
|---|---|
| FRD-DASH-1 | The system shall display current account state: capital, available balance, invested capital, P&L, and drawdown. |
| FRD-DASH-2 | The system shall display current trading state: open positions, open orders, completed trades, entry/exit details, current strategy, and current timeframe. |
| FRD-DASH-3 | The system shall display current AI state: detected regime, active agents, current signals, confidence, current decision, decision reasoning, and active model version. |
| FRD-DASH-4 | The system shall display current risk state: current exposure, trade risk, daily risk used, drawdown, overall risk status, and kill-switch status. |
| FRD-DASH-5 | The system shall display learning state: recent model experiments, candidate model performance, current production model, learning-pipeline progress, and rejected/rolled-back models. |
| FRD-DASH-6 | The system shall display system health: broker connection status, data connection status, API status, model status, database status, and overall system health. |
| FRD-DASH-7 | The system shall provide a prominent, always-accessible manual emergency STOP control that, when activated, immediately invokes the kill switch (FRD-RISK-12) and is not dependent on any AI component's cooperation or availability (BRD BR-5). |
| FRD-DASH-8 | The manual STOP shall provide the operator a choice, where market conditions allow, between "halt new entries only" and "halt and liquidate open positions" (exact UX to be defined in UI/UX Spec). |

**Applicable Phase(s):** Basic dashboard from V4/V5; full dashboard (all six views + STOP) required no later than V5 live deployment (STOP/kill-switch UI cannot be deferred past V5, per BRD BR-5).

---

## 15. Module 12 — Capital & Growth Management

This module implements PRD §7.8 and enforces BRD BR-2 (no silent capital scaling).

| ID | Requirement |
|---|---|
| FRD-CAP-1 | The system shall track allocated live trading capital as an explicit, configurable value, separate from any notional/simulated capital used in backtesting or paper trading. |
| FRD-CAP-2 | The system shall not increase allocated live trading capital automatically based on trading profit; any increase shall require the predefined criteria (sample size, consistency, drawdown, risk-adjusted return, robustness, live/paper performance, model stability, execution quality, operational reliability) to be evaluated and satisfied. |
| FRD-CAP-3 | The system shall support explicit operator-approved actions to increase capital, decrease capital, pause/stop trading, and withdraw profits. |
| FRD-CAP-4 | The system shall log every capital-allocation change with the criteria evaluated and the evidence supporting the change. |
| FRD-CAP-5 | The system shall evaluate and report against capital-scaling criteria on a defined cadence (cadence to be agreed with operator — open item), rather than only on ad hoc request. |
| FRD-CAP-6 | The specific numeric thresholds for each capital-scaling criterion (e.g., minimum sample size, maximum acceptable drawdown for scaling) are **not specified in this FRD** and must be defined jointly by the operator and the Risk & Trading Logic Design document. |

**Applicable Phase(s):** V5 (initial capital tracking) through V8 (full scaling mechanics per SOW §6.9).

---

## 16. Cross-Module Functional Rules

These rules apply across all modules above and resolve potential conflicts between them:

| ID | Rule |
|---|---|
| FRD-X-1 | Where any module's output would conflict with a Risk Engine (Module 6) constraint, the Risk Engine's constraint prevails (implements BRD BR-1). |
| FRD-X-2 | No module other than the Supervisor (Module 7) may submit an order to the Execution Engine (Module 8). |
| FRD-X-3 | No module may bypass Module 9 decision-record logging, including during degraded/fallback operation — if logging itself fails, the system shall treat this as a data-quality/system failure requiring FRD-RISK-9 handling, not proceed silently. |
| FRD-X-4 | The Research Brain (Module 10) shall have no functional pathway to Module 8 Execution Engine or to Module 12 capital allocation, by design (implements BRD BR-6). |
| FRD-X-5 | The manual STOP (Module 11) and kill switch (Module 6) shall take precedence over every other module's output, including in-flight Supervisor decisions. |

---

## 17. Non-Functional Cross-References

Detailed non-functional requirements (performance, latency, availability, security) are out of scope for this FRD and are covered in the NFRD, consistent with PRD §8. Where a functional requirement above implies a non-functional constraint (e.g., FRD-EXEC-9 "prioritize correctness over speed"), the NFRD must define the measurable target.

---

## 18. Open Items Carried Into This FRD

The following are inherited from the PRD/BRD/SOW and directly affect the completeness of specific modules above; they are not resolved by this FRD:

1. Final data vendor/broker selection (affects Module 1, Module 8).
2. Initial agent roster for Module 4 (affects FRD-SIG-5) — to be validated in HLD.
3. Mandatory vs. optional agents (affects FRD-SIG-3) — to be defined in HLD.
4. Numeric risk-limit values (Module 6, FRD-RISK-14) — to be defined in Risk & Trading Logic Design.
5. Capital-scaling numeric thresholds (Module 12, FRD-CAP-6) — to be defined jointly with operator.
6. Required level of human sign-off in model promotion (Module 10, FRD-LEARN-5) — operator decision pending.
7. Retention period/storage approach for decision records (FRD-EVAL-5) — to be defined in DDD.

---

## 19. Traceability

| FRD Module | PRD Reference | BRD Reference | SOW Reference |
|---|---|---|---|
| Module 1 Data | PRD §7.1, §9 | — | SOW §6.1 (V0) |
| Module 2 Feature Eng. | PRD §7.1 | — | SOW §6.2–6.3 (V1–V2) |
| Module 3 Regime | PRD §7.1 | — | SOW §6.4 (V3) |
| Module 4 Signals | PRD §7.2 | — | SOW §6.4 (V3) |
| Module 5 Aggregation | PRD §7.2 | BRD BR-3 | SOW §6.4 (V3) |
| Module 6 Risk Engine | PRD §7.3 | BRD BR-1, BR-4 | SOW §6.6 (V5) |
| Module 7 Supervisor | PRD §7.3 | BRD BR-4 | SOW §6.4/§6.6 |
| Module 8 Execution | PRD §7.4 | — | SOW §6.5–6.6 (V4–V5) |
| Module 9 Evaluation | PRD §7.5 | BRD BR-7 | SOW §6.5–6.6 |
| Module 10 Learning | PRD §7.6–7.7 | BRD BR-6 | SOW §6.7–6.8 (V6–V7) |
| Module 11 Dashboard | PRD §7.9 | BRD BR-5 | SOW §6.9 (V8, matured) |
| Module 12 Capital | PRD §7.8 | BRD BR-2 | SOW §6.9 (V8) |

Every requirement ID in this FRD should be entered into the Requirements Traceability Matrix (PRD §14, Master Context §27), mapped forward to its eventual HLD component, code module, and test case.

---

## 20. Document Governance

This FRD must remain consistent with the PRD, BRD, and SOW. Any new functional requirement discovered during HLD/LLD must be added here first (with a new FRD-ID) and then reflected downstream — not implemented ad hoc without a corresponding requirement.

**Next recommended step:** produce the NFRD (quantifying performance, availability, and security targets referenced but not defined here), and begin HLD, starting with Module 3–7 (the core decision architecture), since these carry the most technical risk per SOW §6.4.
