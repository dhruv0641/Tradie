# Contradiction, Ambiguity & Open Items Register

## AI Trader — Baseline v1.0

This register consolidates all identified ambiguities, document tensions, and open decisions across the 16 authoritative specifications.

---

## 1. Document Contradictions & Tensions

| ID | Conflict / Tension Description | Source Documents | Architectural Resolution / Recommendation | Status |
|---|---|---|---|---|
| **CONTR-01** | **Missing Data Design Document (DDD)**: HLD, LLD, TTD, ADD, and MLD heavily reference `DDD §5` entities (`DecisionRecord`, `TradeEvaluation`, `ModelVersion`, `ValidationRunRecord`), but `docs/ddd.md` was completely empty (0 bytes). | HLD, LLD, TTD vs. `docs/ddd.md` | **Resolved**: Author full [docs/ddd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/ddd.md) with canonical entity models and TimescaleDB/Parquet DDL. | Fixed |
| **CONTR-02** | **Brokerage Drag on ₹10k Capital vs. Per-Trade Risk**: Fixed ₹20 brokerage per order on a ₹2,000 max position equals 1% per side (2% round-trip), which exceeds the 1% total per-trade risk budget (RTLD §5). | PRD §9, RTLD §5 vs. BTD §6 (BTD-1) | Quant (Agent 03) and Backtesting (Agent 05) must mandate percentage-based discount brokerage pricing (e.g. 0.03% or ₹20 whichever lower) or focus on swing/multi-day holding horizons to overcome friction. | Open for Review |
| **CONTR-03** | **Confidence Threshold Dual Evaluation**: RTLD §13.1 step 4 specifies confidence gating upstream, and step 7 specifies it again inside the Risk Engine checklist (RTLD-16). | RTLD §13.1 vs. LLD §15 item 4 | Clarify in LLD: Aggregator filters out sub-threshold candidates first; Risk Engine serves as the fail-fast deterministic backstop ensuring no low-confidence trade bypasses the gate. | Resolved in LLD |
| **CONTR-04** | **Kill Switch Action (Pause vs. Liquidate)**: PRD FR-16 / FRD-EXEC-8 mention emergency liquidation, while RTLD §16 specifies that Kill Switch defaults to "stop digging" (blocking new entries) rather than force-liquidating open positions. | PRD FR-16 vs. RTLD §16, EDD §11 | Resolved in EDD §11: Kill Switch blocks all new orders immediately; Emergency Liquidation is a separate, explicit operator command, protecting against unnecessary market-impact loss during liquidity events. | Resolved |
| **CONTR-05** | **Consecutive Loss Scope (Session vs. Rolling)**: RTLD §10 defines consecutive-loss triggers (3 losses $\to -50\%$ size, 5 losses $\to$ session pause), but leaves open whether streaks reset at session boundaries. | RTLD §10, §18 item 8 | Proposed: Session pause resets at session boundary; Tier-1 size reduction persists across sessions on a rolling basis until the next winning trade. | Pending Sign-off |

---

## 2. Master Open Items Requiring Operator Input

| Item ID | Topic | Description | Impacted Documents / Modules | Proposed Recommendation |
|---|---|---|---|---|
| **OPEN-01** | **Broker Selection** | Specific Indian retail broker API (Zerodha Kite, Upstox, Angel One, Fyers, Shoonya). | EDD §5, TRD-EXEC-6, BTD §13 | Provide `BrokerAdapter` interface supporting Kite Connect and simulated paper trading first. |
| **OPEN-02** | **Market Data Vendor** | Specific real-time streaming and historical data vendor. | DDD, TRD-PIPE-5, SOW V0 | Support Yahoo Finance / NSE free feeds for Phase 0 research, upgrading to official broker tick stream for Phase 4. |
| **OPEN-03** | **Model Promotion Sign-off** | Automated promotion within gates vs. mandatory human approval per promotion event. | BRD §11 item 6, ADD §13 item 4, SLD §8 | Mandate human operator sign-off (`human_signoff_ref`) for all live capital promotions in early phases (V5–V7). |
| **OPEN-04** | **Hosting Infrastructure** | Self-hosted local machine vs. Cloud VM vs. Hybrid. | TTD §16, TRD-COMPUTE-5 | Self-hosted Docker + PostgreSQL for V0–V4; migrate Trading Brain to Cloud VM for V5+ live trading. |
| **OPEN-05** | **Profit Withdrawal Policy** | Full reinvestment vs. periodic profit withdrawal rules. | BRD §11 item 4, RTLD §15 | Retain fixed ₹10,000 base capital in early live phase (V5); withdraw profits exceeding capital buffer monthly. |
| **OPEN-06** | **Quantitative NFR Sign-Off** | Formal confirmation of NFRD §14 parameter register (uptime, latencies, thresholds). | NFRD §14, RTLD §14, BTD §13 | Review and baseline proposed parameters during Phase 0 sign-off. |
