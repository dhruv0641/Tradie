# ADR-0001: Modular Monolith Architecture for Trading Brain with Decoupled Research Brain

## Context & Problem Statement
The AI Trader system requires high modularity across 12 distinct functional modules (Data Ingestion, Feature Engineering, Regime Detection, Signal Generation, Aggregation, Risk Engine, Supervisor, Execution, Evaluation, Learning, Dashboard, Capital Management). We must decide on the overall system architecture pattern while satisfying TRD-ARCH-1–5, avoiding premature distributed complexity (Guiding Principle 7), and strictly enforcing the physical isolation of the Research Brain from live execution (TRD-ARCH-2, FRD-X-4).

## Decision
Adopt a **Modular Monolith** architecture pattern for the **Trading Brain**, with the **Research Brain** deployed as a physically separate, sandboxed service.

1. **Trading Brain Modular Monolith**:
   - All modules (1–8, 11, 12) reside in a single deployable process.
   - Module boundaries are strictly enforced via typed Python `Protocol`/ABC interfaces (`TRD-API-1`).
   - Inter-module communication within the Trading Brain uses direct in-process function calls, eliminating network latency, message serialization overhead, and broker failure points.
2. **Research Brain Physical Decoupling**:
   - The Research Brain (Module 10, backtesting, model training, candidate generation) runs in a separate process/container.
   - Holds zero live broker credentials and has no network path to order submission or capital scaling.
   - Output to the Trading Brain is strictly restricted to proposing `PromotionEvent` records in the Model Registry.

## Consequences
### Positive
- Minimizes operational overhead and infrastructure costs for a single-operator system managing initial ₹10,000 capital.
- Preserves single-threaded evaluation order and deterministic execution without distributed consensus issues.
- Guarantees complete structural isolation of research experimentation from live capital.
- Modules can be cleanly extracted into independent microservices later if scaling justifies it.

### Negative / Risks
- Monolithic process crash affects all Trading Brain modules (mitigated by startup state reconciliation and clean component error isolation).

## Status
Accepted (Derived from HLD §4, TRD-ARCH-1–5).
