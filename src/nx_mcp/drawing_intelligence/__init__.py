"""Deterministic drawing-evidence resolution.

This package is intentionally independent from the NX execution backend.
It turns evidence records into geometry facts without re-reading the drawing
or guessing missing design intent.
"""

from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import (
    CoordinateFact,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
)
from .resolver import ResolutionResult, resolve_evidence_graph

__all__ = [
    "CoordinateFact",
    "DirectValueEvidence",
    "DraftAssemblyError",
    "EvidenceGraph",
    "OverallDimensions",
    "RelationEvidence",
    "ResolutionResult",
    "build_semantic_draft",
    "resolve_evidence_graph",
]
