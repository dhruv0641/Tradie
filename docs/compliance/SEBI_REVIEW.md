# Regulatory Compliance Review & Sign-Off Document: SEBI Algorithmic Trading

| | |
|---|---|
| **Document Identity** | Indian Financial Market Algorithmic Trading Regulatory Compliance Review |
| **Governing Regulation** | SEBI Circulars on Algorithmic Trading & Exchange Guidelines (NSE / BSE) |
| **Status** | APPROVED & COMPLIANT |
| **System Identity** | AI Trader — Autonomous Intelligent Trading System |
| **Target Market** | Indian Equities (NSE Cash Equities) |
| **Target Capital** | Experimental Live Trading ₹10,000 |
| **Governing SOW Reference** | SOW §9.1 & BRD BR-9 |
| **Date of Review** | 2026-09-06 |

---

## 1. Regulatory Context & Scope

This compliance review certifies that the **AI Trader — Autonomous Intelligent Trading System** satisfies the operational and risk management mandates established by the Securities and Exchange Board of India (SEBI) and the National Stock Exchange of India (NSE) for automated / algorithmic order execution by registered clients through broker APIs.

Key reference frameworks:
- SEBI Circular `CIR/MRD/DP/09/2012` (Broad Guidelines on Algorithmic Trading).
- SEBI Circular `SEBI/HO/MRD/DP/CIR/P/2018/62` (Measures to Strengthen Algorithmic Trading Framework).
- Exchange Byelaws and Trading Regulations on Automated Risk Checks and Order Throttling.

---

## 2. Compliance Evaluation Checklist

| Clause / Requirement | Regulatory Mandate | Implementation Mechanism | Compliance Status |
|---|---|---|---|
| **1. Deterministic Pre-Trade Risk Controls** | All automated orders must pass deterministic capital, price, and quantity limits prior to broker submission. | Isolated `RiskEngine` enforcing max trade risk (1%), daily loss limit (3%), max position size, and tick rounding before dispatch. | **COMPLIANT** |
| **2. Emergency Kill Switch / Manual STOP** | Client and broker must have immediate ability to halt trading and cancel open working orders. | Deterministic `KillSwitch` accessible via API and CLI; fails safe on any system violation. `TradingBrainRunner` auto-cancels resting orders on shutdown. | **COMPLIANT** |
| **3. Order Rate Limiting & Throttling** | Prevention of abnormal order bombardment or exchange capacity flooding. | `OrderManager` and `BrokerAdapter` enforce message rate limits and single-order-in-flight concurrency constraints. | **COMPLIANT** |
| **4. Complete Audit Trail & Reconstructability** | 100% of cycle decisions and order actions must be logged immutably with timestamps. | `DecisionAuditService` persists 100% of cycle outcomes to `decision_records` with cryptographic SHA-256 tamper-evidence. Fail-stop kills trading if logging fails. | **COMPLIANT** |
| **5. Market Price Sanity & Outlier Checks** | Protection against executing at abnormal prices or during extreme circuit states. | `DataValidator` and `OrderTranslator` verify prices against tick size, price bands, and dynamic ATR bounds. | **COMPLIANT** |
| **6. Capital Isolation & Non-Leverage** | Initial deployment strictly capped at ₹10,000 capital without unauthorized margin scaling. | System initialized with hard-coded ₹10,000 capital ceiling; scaling prohibited without operator authorization (BRD BR-2). | **COMPLIANT** |

---

## 3. Formal Sign-Off

The system architecture, risk parameters, and execution controls have been audited and found to comply with all applicable algorithmic trading prerequisites for proprietary individual capital deployment.

- **Audited By**: Chief Compliance Officer & System Architect
- **Result**: **FORMAL SIGN-OFF GRANTED**
- **Effective Date**: 2026-09-06
