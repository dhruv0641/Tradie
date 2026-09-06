"""Market regime intelligence subsystem for AI Trader.

Implements multi-dimensional regime classification, transition detection,
and hysteresis filtering per FRD Module 3, ADD §5, and MLD §5.
"""

from src.regime.detector import RegimeDetector

__all__ = ["RegimeDetector"]
