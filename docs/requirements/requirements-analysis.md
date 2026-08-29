# Requirements Analysis & Scope Baseline

## 1. Requirement Document Suite Summary

The AI Trader requirements baseline is defined across six parent specifications:
- [PRD (Product Requirements Document)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/prd.md): Defines product vision, non-goals, 31 functional requirements summary, delivery roadmap (V0–V8), and success metrics (rejecting raw win rate in favor of risk-adjusted expectancy).
- [BRD (Business Requirements Document)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/brd.md): Defines business justification, the 9 foundational business rules (BR-1 through BR-9), capital protection precedence, and operator governance.
- [SOW (Statement of Work)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/sow.md): Details work packages, deliverables, and acceptance criteria across phases V0 to V8, with strict preconditions for V5 live capital.
- [FRD (Functional Requirements Document)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/frd.md): Detailed decomposition into 12 functional modules, specifying inputs, outputs, and cross-cutting functional rules (`FRD-X-1` through `FRD-X-5`).
- [NFRD (Non-Functional Requirements Document)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/nfrd.md): Quality attributes across 13 categories, establishing structural non-negotiables and registering quantitative placeholders.
- [TRD (Technical Requirements Document)](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/trd.md): Technical requirements bridging functional rules to system architecture and technology selection.

---

## 2. Core Functional Modules Mapping

```
Module 1: Data Ingestion & Validation (FRD-DATA-1–9)
Module 2: Feature Engineering (FRD-FEAT-1–5)
Module 3: Market Regime Detection (FRD-REGIME-1–5)
Module 4: Signal Generation (FRD-SIG-1–5)
Module 5: Signal Aggregation & Scoring (FRD-AGG-1–6)
Module 6: Risk Engine (FRD-RISK-1–14)
Module 7: Supervisor / Decision Gate (FRD-SUP-1–6)
Module 8: Execution Engine (FRD-EXEC-1–10)
Module 9: Trade Evaluation & Explainability (FRD-EVAL-1–6)
Module 10: Learning & Model Lifecycle (FRD-LEARN-1–9)
Module 11: Dashboard & Human Control (FRD-DASH-1–8)
Module 12: Capital & Growth Management (FRD-CAP-1–6)
```

---

## 3. Scope Boundaries

### In-Scope (Phased Delivery V0–V8)
- Indian stock market data ingestion (NSE equities, NIFTY instruments).
- Technical and structural feature engineering.
- Rule-based and statistical market regime classification.
- Multi-agent signal generation, dynamic timeframe evaluation, and trade scoring.
- Deterministic risk checks: Max trade risk (1%), max daily loss (3%), hard drawdown halt (8%), kill switch (10%), portfolio exposure caps (50%), position size caps (20%), simultaneous position caps (3), trade frequency caps (5/day).
- Backtesting with full Indian market statutory cost simulation (brokerage, STT, exchange turnover, GST, stamp duty, slippage).
- Paper trading with real-time simulated execution.
- Live broker execution via abstracted adapters for approved ₹10,000 capital.
- Post-trade variance driver analysis and controlled candidate model promotion/rollback.

### Out-of-Scope
- Trading non-Indian financial markets.
- High-frequency, sub-millisecond, co-located algorithmic execution.
- Unattended live trading without manual operator emergency stop capabilities.
- Managing third-party or multi-user capital.
- Delegating risk limits or position sizing to LLMs, neural networks, or RL policies.
