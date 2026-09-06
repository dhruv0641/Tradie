---
name: architecture-guard
description: >-
  Use this skill to verify system architecture boundaries, enforce modular monolith contracts,
  audit Research Brain vs. Trading Brain isolation, and check for forbidden import edges.
---

# Architecture Guard Runbook (Agent 02)

## Mission
Guard system modularity and architectural boundaries. Enforce TRD-ARCH-2, TRD-ARCH-3, HLD §8, and ADR-0001/ADR-0003.

---

## 1. Architectural Invariants to Verify

### 1.1 Safety Isolation Verification
The safety-critical modules (`src/risk_engine/`, `src/supervisor/`, `src/kill_switch/`) must remain completely decoupled from AI and probabilistic components.
- **Forbidden Imports in Safety Path**:
  - `src/features/` (Feature engine)
  - `src/agents/` (Trading agents roster)
  - `src/models/` (ML models, XGBoost, PyTorch, Scikit-learn)
  - `src/learning/` (Self-learning pipeline)
  - Any external LLM API client (`openai`, `anthropic`, `google-genai`)
  - Any asynchronous event broker client (`kafka`, `rabbitmq`, `redis-pubsub`)

### 1.2 Research Brain Isolation Verification
Per TRD-ARCH-2:
- Research Brain scripts and notebooks under `research/` must have:
  - Zero imports from `src/execution/` or `src/broker/`.
  - Zero access to live broker configuration files (`.env.live`).
  - Read-only access to market data archives.

---

## 2. Static Architectural Audit Script

Run this script to programmatically verify zero forbidden imports in the safety path:

```python
"""Architecture boundary verification script."""
import sys
from pathlib import Path

FORBIDDEN_TERMS = [
    "src.features",
    "src.agents",
    "src.models",
    "src.learning",
    "openai",
    "anthropic",
    "google.genai",
    "kafka",
    "pika",
]

SAFETY_DIRS = [
    Path("src/risk_engine"),
    Path("src/supervisor"),
    Path("src/kill_switch"),
]

def check_safety_isolation() -> int:
    violations = 0
    for directory in SAFETY_DIRS:
        if not directory.exists():
            continue
        for file in directory.glob("*.py"):
            content = file.read_text(encoding="utf-8")
            for term in FORBIDDEN_TERMS:
                if term in content:
                    print(f"CRITICAL VIOLATION: {file} imports forbidden module '{term}'!")
                    violations += 1
    return violations

if __name__ == "__main__":
    count = check_safety_isolation()
    if count > 0:
        print(f"FAILED: {count} architectural boundary violations detected.")
        sys.exit(1)
    print("SUCCESS: Zero forbidden imports in safety path.")
    sys.exit(0)
```

---

## 3. Boundary Audit Commands

```powershell
# 1. Search for forbidden AI/ML imports in safety-critical directories
Select-String -Path .\src\risk_engine\*.py, .\src\supervisor\*.py, .\src\kill_switch\*.py -Pattern "features|agents|models|learning"

# 2. Search for live execution imports in research directory
Select-String -Path .\research\*.py -Pattern "execution|broker_adapter|kiteconnect|upstox"
```
