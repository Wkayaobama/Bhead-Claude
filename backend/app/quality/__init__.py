"""Deterministic quality scoring for extracted job postings.

Layout:
  extractor.py  — the one normalisation of a job document into scored fields
  registry.py   — rules, bands and the flag threshold as plain data
  engine.py     — pure interpreter over the registry (no I/O, no clock)

Importing the package validates the registry, so a malformed rule fails the
process at startup rather than the first `/api/monitor/analyze` call.
"""
from app.quality.engine import QualityResult, band_for, describe, evaluate, validate_registry
from app.quality.extractor import extract_fields
from app.quality.registry import BANDS, FLAG_THRESHOLD, RULES, Band, Rule

validate_registry(RULES, BANDS, FLAG_THRESHOLD)

__all__ = [
    "BANDS",
    "Band",
    "FLAG_THRESHOLD",
    "QualityResult",
    "RULES",
    "Rule",
    "band_for",
    "describe",
    "evaluate",
    "extract_fields",
    "validate_registry",
]
