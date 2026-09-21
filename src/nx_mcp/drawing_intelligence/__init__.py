"""Deterministic drawing-evidence resolution.

This package is intentionally independent from the NX execution backend.
It turns evidence records into geometry facts without re-reading the drawing
or guessing missing design intent.
"""

from .evidence import (
    CoordinateFact,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
)
from .resolver import ResolutionResult, resolve_evidence_graph

__all__ = [
    "CoordinateFact",
    "EvidenceGraph",
    "OverallDimensions",
    "RelationEvidence",
    "ResolutionResult",
    "resolve_evidence_graph",
]
