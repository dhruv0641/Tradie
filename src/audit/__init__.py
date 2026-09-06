"""Audit and post-trade evaluation subsystem (EPIC-17).

Provides immutable DecisionRecord logging to PostgreSQL, post-trade variance driver
classification and Indian statutory cost attribution, and non-fabricated decision
explainability query tools (BRD BR-7, FRD-EVAL-1..6, DDD §5.2..§5.3).
"""

from src.audit.decision_logger import (
    AuditPersistenceError,
    DecisionAuditService,
    KillSwitchProtocol,
    TamperEvidenceViolationError,
)
from src.audit.explain import (
    DecisionExplainer,
    ExplanationReport,
    RecordNotFoundError,
)
from src.audit.trade_evaluator import (
    CanonicalVarianceDriver,
    TradeEvaluator,
)

__all__ = [
    "AuditPersistenceError",
    "CanonicalVarianceDriver",
    "DecisionAuditService",
    "DecisionExplainer",
    "ExplanationReport",
    "KillSwitchProtocol",
    "RecordNotFoundError",
    "TamperEvidenceViolationError",
    "TradeEvaluator",
]
