# AI Trader — Autonomous Intelligent Trading System

Autonomous, AI-powered trading platform for Indian financial markets (NSE Equities / NIFTY derivatives) operating strictly within deterministic, non-negotiable risk boundaries.

## Architecture & Governance

The platform operates under the master governance framework detailed in [AGENTS.md](file:///c:/Users/dobar_zdc9vhh/OneDrive/Desktop/AI%20Tradie/AGENTS.md), enforced by a 17-specialist software engineering team:
- **Safety First**: Deterministic risk controls with independent execution paths; Agent 09 (Risk & Safety) has binding veto authority over all live capital and orders.
- **Brain Isolation**: Strict separation between Research Brain (training, backtesting, exploration) and Trading Brain (deterministic live execution).
- **NO TRADE Validity**: Capital preservation strictly prioritized over trade volume.

## Quickstart & Environment Setup

This project uses `uv` for fast, hermetic dependency resolution and Python runtime management.

### 1. Prerequisites
- `uv` installed (`irm https://astral.sh/uv/install.ps1 | iex` on Windows or `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux/macOS)

### 2. Environment Bootstrap
```bash
# Install Python 3.12 hermetically and sync all dependencies
uv python install 3.12
uv sync --all-extras
```

### 3. Running Quality Checks
```bash
# Static analysis and formatting
uv run ruff check .
uv run ruff format --check .

# Strict type checking
uv run mypy src tests

# Test execution with branch coverage
uv run pytest
```

### 4. Git Pre-Commit Hooks
```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## Directory Structure
```
ai-trader/
├── .agents/              # Antigravity agent configurations & rules
├── .github/workflows/    # Continuous Integration pipelines
├── agents/               # 17 specialist agent runbooks
├── docs/                 # Authoritative architecture and specifications
├── src/                  # Production runtime source code
├── tests/                # Unit, integration, and safety test suites
├── pyproject.toml        # Build manifest and dependency specifications
└── STORY.md              # Project status and live state tracker
```
