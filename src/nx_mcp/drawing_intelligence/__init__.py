from .capture import (
    AssociationClaim,
    CaptureDatumAlignment,
    CaptureDimension,
    CaptureDimensionEndpoint,
    CaptureEntity,
    CaptureRequiredTarget,
    CaptureValue,
    CaptureView,
    ReaderCapture,
)
from .hybrid_capture_adapter import (
    HybridAdapterContext,
    HybridCaptureAdapterError,
    HybridRegionView,
    adapt_hybrid_ocr_report,
)
from .identity_linker import IdentityLinkError, IdentityLinkResult, link_reader_capture

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
from .gate0 import Gate0Error, Gate0Result, write_strict_evidence
from .resolver import ResolutionResult, resolve_evidence_graph
from .stability import (
    StabilityReport,
    compare_evidence_runs,
    logical_snapshot,
    snapshot_fingerprint,
)

__all__ = [
    "adapt_hybrid_ocr_report",
    "HybridRegionView",
    "HybridCaptureAdapterError",
    "HybridAdapterContext",
    "link_reader_capture",
    "IdentityLinkResult",
    "IdentityLinkError",
    "ReaderCapture",
    "CaptureView",
    "CaptureValue",
    "CaptureRequiredTarget",
    "CaptureEntity",
    "CaptureDimensionEndpoint",
    "CaptureDimension",
    "CaptureDatumAlignment",
    "AssociationClaim",
    "CoordinateFact",
    "DatumAlignmentEvidence",
    "DimensionEndpoint",
    "DimensionObservation",
    "DirectValueEvidence",
    "DraftAssemblyError",
    "EvidenceCompileError",
    "EvidenceGraph",
    "Gate0Error",
    "Gate0Result",
    "OverallDimensions",
    "ProjectionEvidence",
    "RelationEvidence",
    "ResolutionResult",
    "StabilityReport",
    "ViewEvidence",
    "build_semantic_draft",
    "compare_evidence_runs",
    "compile_evidence_graph",
    "logical_snapshot",
    "resolve_evidence_graph",
    "snapshot_fingerprint",
    "write_strict_evidence",
]
