"""Model governance, validation pipeline, and promotion controls subsystem.

Conforms to FRD Module 10 (FRD-LEARN-3-8), ADD §8, §12, and MLD §9, §10.
"""

from src.governance.validation_runner import (
    ValidationRunner,
    ValidationRunnerConfig,
)

__all__ = [
    "ValidationRunner",
    "ValidationRunnerConfig",
]
