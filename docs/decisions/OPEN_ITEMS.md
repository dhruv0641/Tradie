# Central Open Items Register

## AI Trader — Master Development Log

This register centrally tracks all recurring open items across the 16 authoritative project documents. Work depending on these items must clearly state the dependency, implement against documented "Proposed" defaults where permitted, and never resolve an item in one document while leaving a stale assumption in another.

---

## 1. Open Items Matrix

| # | Item Description | Citing Sections Across All 16 Documents | Blocked / Impacted Work | Documented Proposed Default | Current Status |
|---|---|---|---|---|---|
| **1** | **Broker Selection** | `prd.md` §6.3, §14<br>`brd.md` §11 item 2<br>`sow.md` §12 item 2<br>`trd.md` TRD-EXEC-6<br>`hld.md` §17 item 3<br>`ttd.md` §17<br>`rtld.md` §18 item 2<br>`edd.md` §5, §13<br>`lld.md` §15 item 1 | • Liquidity threshold (RTLD-18)<br>• Instrument type finalization (TRD-EXEC-5)<br>• BTD cost/friction parameters (BTD-1)<br>• Concrete `BrokerAdapter` implementation | Retail Indian Broker API (Zerodha Kite Connect, Upstox, Angel One, Fyers, Shoonya). Abstracted behind `BrokerAdapter` protocol with mock/paper adapter for V0–V4. | Open (Blocks live V5 integration) |
| **2** | **Data Vendor(s) & Entitlements** | `prd.md` §6.3<br>`trd.md` TRD-PIPE-5<br>`hld.md` §17 item 3<br>`ttd.md` §17<br>`ddd.md` §4, §7<br>`lld.md` §15 item 2, §16 | • Concrete `DataSourceAdapter` implementation<br>• LLD Volume 2 (Data Pipeline / Feature Engine)<br>• Real-time streaming latency & staleness thresholds (RTLD-19) | Free / local feeds (Yahoo Finance, NSE public API, local Parquet) for Phase 0–V3 research; official broker tick stream for V4+ paper/live. | Open (Phased resolution active) |
| **3** | **Compute Hosting Model** | `trd.md` TRD-COMPUTE-5<br>`hld.md` §17 item 2<br>`ttd.md` §16 | • DevOps Agent deployment topology<br>• Process supervision configuration (`systemd` vs. cloud container service) | Self-hosted local Docker + PostgreSQL for V0–V4; migrate Trading Brain to dedicated Cloud VM (AWS/GCP/DigitalOcean) for V5+ live trading. | Open (Phased recommendation accepted) |
| **4** | **Infrastructure & Compute Budget** | `brd.md` §11 item 5<br>`sow.md` §12 item 5 | • Research Brain model training capacity<br>• Historical data storage sizing | Minimal local compute during research (V0–V3) to preserve initial capital. | Open for Operator confirmation |
| **5** | **DDD (Data Design Document) Drafting** | `rtld.md` §18<br>`hld.md` §17 item 4<br>`add.md` §13<br>`mld.md` §12<br>`lld.md` §4, §15 item 6 | • Formal database schema migrations<br>• Data Engineering (Agent 04)<br>• Low-Level Engineering (Agent 12, LLD Volumes 2–6) | Drafted in `docs/ddd.md` as DDD v0.1. Defines `DecisionRecord`, `TradeEvaluation`, `Position`, `OrderSubmission`, `ModelVersion`, `ValidationRunRecord`, and TimescaleDB DDL. | Remediated (DDD v0.1 drafted, pending operator confirmation) |
| **6** | **Human Sign-off on Model Promotion** | `brd.md` §11 item 6<br>`sow.md` §12<br>`hld.md` §12<br>`add.md` §8.4, §13 item 4<br>`rtld.md` §18 item 6<br>`sld.md` §8 | • Learning pipeline promotion automation vs. manual approval gate (`human_signoff_ref`) | Mandatory human operator approval for all model promotions to live trading in early phases (V5–V7). Automated promotion permitted in sandboxed paper trading. | Open for Operator confirmation |
| **7** | **Confidence Threshold & Gating Overlap** | `rtld.md` §13.1 step 4, §14 (RTLD-16)<br>`lld.md` §8.2, §15 item 4 | • Aggregator `min_quality_threshold` vs. Risk Engine `min_confidence_threshold` | Aggregator filters sub-quality candidates first; Risk Engine acts as fail-fast deterministic safety checklist backstop. | Resolved in LLD v0.1 |
| **8** | **Profit Withdrawal vs. Reinvestment Policy** | `brd.md` §11 item 4<br>`rtld.md` §15 | • Capital Manager profit retention & withdrawal logic | Fixed base capital of ₹10,000 in V5; profits above risk buffer distributed or retained per documented operator instruction. | Open for Operator policy decision |

---

## 2. Open Item Governance Rules
1. If an engineering or quantitative task depends on an open item above:
   - Clearly state the dependency in the agent output handoff.
   - Do NOT guess or silently harden an arbitrary choice into code.
   - Implement against the documented "Proposed Default" behind a clean abstraction/interface (`BrokerAdapter`, `DataSourceAdapter`).
2. When an open item is formally resolved by the System Owner/Operator:
   - Record an ADR under `docs/decisions/`.
   - Update this table and propagate the resolution across every citing document listed in Column 3.
