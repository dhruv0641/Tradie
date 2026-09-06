"""Research Brain package.

Physically and architecturally isolated research environment for feature engineering,
model training, candidate hypothesis generation, and post-trade variance attribution.

Governing Principles:
- Research Brain vs Trading Brain Strict Separation (TRD-ARCH-2, FRD-X-4, BRD BR-6).
- Zero live broker credentials, zero execution authority, read-only historical data.
"""

from src.research.environment import (
    ResearchBrainConfig,
    ResearchBrainEnvironment,
    ResearchIsolationError,
    check_research_ast_isolation,
)

__all__ = [
    "ResearchBrainConfig",
    "ResearchBrainEnvironment",
    "ResearchIsolationError",
    "check_research_ast_isolation",
]
