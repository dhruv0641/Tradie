# Multi-Agent Dependency & Collaboration Map

## 1. Development Agent Hierarchy & Coordination Structure

```
                             ┌──────────────────────────────────────────────┐
                             │ Agent 00: Orchestrator / Chief Architect     │
                             │ (Global Coordination, PR Sign-Off, ADRs)     │
                             └──────────────────────┬───────────────────────┘
                                                    │
        ┌───────────────────────────────────────────┼───────────────────────────────────────────┐
        │                                           │                                           │
        ▼                                           ▼                                           ▼
┌──────────────────┐                       ┌──────────────────┐                        ┌──────────────────┐
│  REQUIREMENTS &  │                       │   TRADING &      │                        │  ENGINEERING &   │
│   ARCHITECTURE   │                       │  QUANT DOMAIN    │                        │  INFRASTRUCTURE  │
│                  │                       │                  │                        │                  │
│ Agent 01: Reqs   │                       │ Agent 03: Quant  │                        │ Agent 11: Tech   │
│ Agent 02: Arch   │                       │ Agent 04: Data   │                        │ Agent 12: LLD    │
│                  │                       │ Agent 05: Backtest│                       │ Agent 13: Security│
│                  │                       │ Agent 06: AI-Arch│                        │ Agent 14: QA     │
│                  │                       │ Agent 07: ML     │                        │ Agent 15: DevOps │
│                  │                       │ Agent 08: Learn  │                        │ Agent 16: Review │
└──────────────────┘                       └────────┬─────────┘                        └──────────────────┘
                                                    │
                                                    ▼
                                   ┌──────────────────────────────────┐
                                   │ Agent 09: Risk & Safety Agent    │
                                   │ [MANDATORY VETO AUTHORITY]       │
                                   └────────────────┬─────────────────┘
                                                    │
                                                    ▼
                                   ┌──────────────────────────────────┐
                                   │ Agent 10: Execution / Broker     │
                                   │ (Order Lifecycle & Broker I/F)   │
                                   └──────────────────────────────────┘
```

---

## 2. Cross-Agent Data & Artifact Flow

```
Agent 01 (Requirements) ──► PRD/FRD/NFRD ──► Agent 02 (Architecture) & Agent 03 (Quant)
Agent 04 (Data) ──────────► Ingestion & Schemas ──► Agent 07 (ML) & Agent 05 (Backtesting)
Agent 07 (ML) ────────────► Feature Engine & Models ──► Agent 06 (AI Architecture)
Agent 06 (AI Arch) ───────► Candidate Opportunities ──► Agent 09 (Risk & Safety)
Agent 09 (Risk & Safety) ─► Approved Decisions ──► Agent 10 (Execution Engine)
Agent 10 (Execution) ─────► Trade Fills & State ──► Agent 08 (Self-Learning) & Agent 04 (Data)
Agent 08 (Self-Learning) ─► Hypotheses & Candidates ──► Agent 05 (Backtesting) & Agent 07 (ML)
Agent 12 (Low-Level) ─────► Code Implementation ──► Agent 14 (QA) & Agent 16 (Code Review)
Agent 15 (DevOps) ────────► CI/CD & Deployments ──► Agent 00 (Orchestrator)
```

---

## 3. Detailed Agent Interaction Matrix

| Agent | Consumes Inputs From | Delivers Outputs To | Escalation Pathway |
|---|---|---|---|
| **00 Orchestrator** | All Agents, Human Operator | All Agents | Human Operator |
| **01 Requirements** | PRD/BRD, Operator, Agent 00 | 02, 03, 09, 14 | 00 |
| **02 Architecture** | 01, 09, 11, 04 | 12, 11, 06, 15, 16 | 00, 09 |
| **03 Quant** | 01, 09, 05 | 09, 05, 06, 12 | 00, 09 |
| **04 Data** | 01, 02, 05, 07 | 05, 07, 12, 09 | 00, 02 |
| **05 Backtesting** | 03, 04, 06, 07 | 07, 08, 09, 00 | 00, 09 |
| **06 AI-Architecture**| 01, 02, 07, 09 | 07, 12, 05 | 00, 02, 09 |
| **07 ML Engineering** | 04, 05, 06 | 06, 08, 12 | 00, 06 |
| **08 Self-Learning** | 04, 10, 09, 05 | 07, 05, 00 | 00, 09 |
| **09 Risk & Safety** | 00, 01, 03, 06, 10 | 10, 12, 14, 16 (VETO) | 00, Operator |
| **10 Execution** | 09, 12, 13 | 09, 04, 08, 12 | 00, 09 |
| **11 Technology** | 01, 02, 13, 15 | 12, 15, 13, 14 | 00, 02 |
| **12 Low-Level** | 02, 09, 11, 04, 06 | 14, 16, 10 | 00, 02, 09 |
| **13 Security** | 01, 02, 10, 15 | 10, 15, 12, 16 | 00, 09 |
| **14 QA / Testing** | 01, 09, 12, 05 | 16, 15, 00 | 00, 12, 09 |
| **15 DevOps / SRE** | 02, 11, 13, 14 | 14, 16, 00 | 00, 11 |
| **16 Code Review** | 12, 04, 10, 14, 09 | 00, 09, 12 | 00, 09 |
