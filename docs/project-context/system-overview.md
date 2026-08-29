# System Overview — AI Trader

## 1. Executive Summary
**AI Trader** is an autonomous, intelligent trading system designed for Indian financial markets (starting with NSE cash equities and extensible to NIFTY/BankNifty derivatives).

The system integrates multi-agent market analysis, dynamic market regime classification, quantitative position sizing, and automated broker execution, operating strictly inside **deterministic, non-negotiable risk boundaries**. The architecture strictly separates offline strategy research and model training (**Research Brain**) from live market evaluation and execution (**Trading Brain**).

---

## 2. Core Operational Flow

The Trading Brain executes an evaluation cycle across active instruments as a unidirectional, fail-fast pipeline:

```
1. Market Data Ingestion & Point-in-Time Validation
     ↓ (Quarantined data suppressed → forced NO TRADE)
2. Feature Engineering (Technical, Trend, Momentum, Volatility, Liquidity)
     ↓
3. Market Regime Detection (Trend State, Volatility Level, Directional Bias)
     ↓
4. Multi-Agent Signal Generation (Trend, Momentum, Mean-Reversion, Price Action)
     ↓
5. Signal Aggregation & Dynamic Timeframe Selection (Trade Quality Score, EV)
     ↓ (EV ≤ 0 or Score < Threshold → NO TRADE)
6. DETERMINISTIC RISK ENGINE EVALUATION (Checklist: Kill Switch, Daily Loss, Drawdown, Sizing, Exposure)
     ↓ (Any single limit breach → NO TRADE / Safe State)
7. SUPERVISOR DECISION GATE (BUY / SELL / HOLD / NO TRADE)
     ↓ (Synchronous DecisionRecord write)
8. Execution Engine & Broker Adapter (Idempotent Limit Order Submission)
     ↓
9. Post-Trade Evaluation & Continuous Learning (Offline Research Brain)
```

---

## 3. Key Differentiators & Philosophy
- **NO TRADE is a First-Class Outcome**: Avoiding bad trades in unfavorable market regimes is an explicit success metric.
- **Deterministic Risk Cage**: No AI, LLM, or probabilistic model can alter, loosen, or override hard risk limits.
- **Evidence-Based Promotion**: Models must pass 5 sequential validation gates (Backtest $\to$ Out-of-Sample $\to$ Walk-Forward $\to$ Stress $\to$ Robustness $\to$ Paper) before live deployment.
- **100% Decision Auditability**: Every decision (including NO TRADE) produces an immutable, fully reconstructable `DecisionRecord`.
