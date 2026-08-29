# Master Document Index & Registry

| # | Document | File Path | Status | Version | Owner Agent | Parent Document |
|---|---|---|---|---|---|---|
| 1 | **PRD** — Product Requirements Document | [docs/prd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/prd.md) | Active | v0.1 draft | Agent 01 (Requirements) | System Owner / Operator |
| 2 | **BRD** — Business Requirements Document | [docs/brd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/brd.md) | Active | v0.1 draft | Agent 01 (Requirements) | PRD v0.1 |
| 3 | **SOW** — Statement of Work | [docs/sow.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/sow.md) | Active | v0.1 draft | Agent 01 (Requirements) | PRD v0.1, BRD v0.1 |
| 4 | **FRD** — Functional Requirements Document | [docs/frd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/frd.md) | Active | v0.1 draft | Agent 01 (Requirements) | PRD, BRD, SOW |
| 5 | **NFRD** — Non-Functional Requirements Document | [docs/nfrd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/nfrd.md) | Active | v0.1 draft | Agent 01 (Requirements) | PRD, BRD, SOW, FRD |
| 6 | **TRD** — Technical Requirements Document | [docs/trd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/trd.md) | Active | v0.1 draft | Agent 01 (Requirements) | FRD, NFRD |
| 7 | **RTLD** — Risk & Trading Logic Design | [docs/rtld.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/rtld.md) | Active | v0.1 draft | Agent 03 (Quant) / Agent 09 (Risk) | BRD, PRD, FRD, NFRD |
| 8 | **BTD** — Backtesting Design Document | [docs/btd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/btd.md) | Active | v0.1 draft | Agent 05 (Backtesting) | PRD, FRD, NFRD, RTLD |
| 9 | **DDD** — Data Design Document | [docs/ddd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/ddd.md) | Drafted | v0.1 draft (remediated) | Agent 04 (Data Engineering) | FRD, TRD, HLD, TTD |
| 10 | **HLD** — High-Level Design | [docs/hld.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/hld.md) | Active | v0.1 draft | Agent 02 (Architecture) | TRD, RTLD, BTD, DDD |
| 11 | **ADD** — AI / Agent Architecture & Design | [docs/add.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/add.md) | Active | v0.1 draft | Agent 06 (AI Architecture) | FRD, TRD, HLD |
| 12 | **MLD** — Machine Learning Design Document | [docs/mld.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/mld.md) | Active | v0.1 draft | Agent 07 (ML Engineering) | FRD, ADD, BTD, RTLD |
| 13 | **SLD** — Self-Learning Design Document | [docs/sld.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/sld.md) | Active | v0.1 draft | Agent 08 (Self-Learning) | FRD, SOW, ADD, MLD |
| 14 | **EDD** — Execution Design Document | [docs/edd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/edd.md) | Active | v0.1 draft | Agent 10 (Execution) | FRD, TRD, HLD, RTLD |
| 15 | **TTD** — Technology / Technical Design Document | [docs/ttd.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/ttd.md) | Active | v0.1 draft | Agent 11 (Technology) | TRD, HLD |
| 16 | **LLD** — Low-Level Design (Volume 1) | [docs/lld.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/docs/lld.md) | Active | v0.1 draft (Vol 1) | Agent 12 (Low-Level) | RTLD, HLD, TTD, ADD |

### Document Governance Notes:
- **`docs/ddd.md`**: Remediated with full schemas, DDL, validation rules, and entity models for `DecisionRecord`, `TradeEvaluation`, `Position`, `OrderSubmission`, `ModelVersion`, `ValidationRunRecord`, and `PromotionEvent`.
- **`docs/lld.md`**: Volume 1 covers the safety-critical path (Risk Engine, Supervisor, Kill Switch), Execution Engine reconciliation/idempotency, and Aggregator scoring. Volumes 2–6 are deferred per `lld.md` §16.
