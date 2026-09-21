"""Deterministic drawing-evidence compilation and resolution.

This package is intentionally independent from the NX execution backend.
It turns visual evidence records into geometry facts without re-reading the
drawing or guessing missing design intent.
"""

from .compiler import EvidenceCompileError, compile_evidence_graph
from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import (
    CoordinateFact,
    DatumAlignmentEvidence,
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    RelationEvidence,
    ViewEvidence,
)
from .resolver import ResolutionResult, resolve_evidence_graph

__all__ = [
    "CoordinateFact",
    "DatumAlignmentEvidence",
    "DimensionEndpoint",
    "DimensionObservation",
    "DirectValueEvidence",
    "DraftAssemblyError",
    "EvidenceCompileError",
    "EvidenceGraph",
    "OverallDimensions",
    "ProjectionEvidence",
    "RelationEvidence",
    "ResolutionResult",
    "ViewEvidence",
    "build_semantic_draft",
    "compile_evidence_graph",
    "resolve_evidence_graph",
]
