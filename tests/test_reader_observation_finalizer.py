from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.capture import validate_reader_capture_contract
from nx_mcp.drawing_intelligence.reader_observation_finalizer import (
    ReaderObservationFinalizationError,
    finalize_partial_reader_observations,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationUnresolved,
    ObservationView,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialReaderObservations,
)


def _partial() -> PartialReaderObservations:
    return PartialReaderObservations(
        overall_dimension_facts=[
            PartialOverallDimensionFact(
                axis="X",
                value=40,
                evidence=["structural:X"],
            ),
            PartialOverallDimensionFact(
                axis="Y",
                value=32,
                evidence=["structural:Y"],
            ),
            PartialOverallDimensionFact(
                axis="Z",
                value=66,
                evidence=["structural:Z"],
            ),
        ],
        views=[
            ObservationView(
                key="view.R1",
                kind="front",
                evidence=["structural:R1"],
            ),
            ObservationView(
                key="view.R2",
                kind="side",
                evidence=["structural:R2"],
            ),
        ],
        dimensions=[
            ObservationDimension(
                key="R1.DG12",
                value=24,
                axis="X",
                endpoints=[
                    ObservationDimensionEndpoint(
                        role="unresolved",
                        unresolved_kind="intermediate_surface",
                        evidence=["hybrid:DG12:whole", "hybrid:DG12:wide"],
                    ),
                    ObservationDimensionEndpoint(
                        role="unresolved",
                        unresolved_kind="intermediate_surface",
                        evidence=["hybrid:DG12:whole", "hybrid:DG12:wide"],
                    ),
                ],
                unresolved_reason="endpoint ownership remains unresolved",
                evidence=["hybrid:DG12:whole", "hybrid:DG12:wide"],
            )
        ],
        observations=[
            {
                "kind": "hybrid_ocr_coverage_ledger",
                "coverage": {
                    "observed_silent_drop_count": 0,
                },
            }
        ],
        unresolved=[
            ObservationUnresolved(
                kind="unsupported_representation",
                reason="whole/local OCR disagreement",
                field="dimension_value_candidate",
                axis="Z",
                evidence=["hybrid:DG17:whole", "hybrid:DG17:wide"],
                required_for_modeling=True,
            )
        ],
    )


def test_finalizer_builds_complete_reader_observations_without_inference():
    full = finalize_partial_reader_observations(_partial())

    assert full.overall_dimensions.length_x == 40
    assert full.overall_dimensions.width_y == 32
    assert full.overall_dimensions.height_z == 66
    assert [view.kind for view in full.views] == ["front", "side"]
    assert full.dimensions[0].endpoints[0].role == "unresolved"
    assert full.observations[-1]["kind"] == "overall_dimension_fact_ledger"


def test_finalized_observations_assemble_to_contract_valid_capture():
    full = finalize_partial_reader_observations(_partial())
    capture = assemble_reader_capture(full)

    assert capture.overall_dimensions.length_x == 40
    assert len(capture.dimensions) == 1
    assert capture.dimensions[0].endpoints[0].role == "unresolved"
    assert capture.unresolved_evidence[0].kind == "unsupported_representation"
    assert validate_reader_capture_contract(capture) == []


def test_finalizer_accepts_duplicate_same_axis_fact_when_values_agree():
    partial = _partial()
    partial.overall_dimension_facts.append(
        PartialOverallDimensionFact(
            axis="X",
            value=40.0,
            evidence=["structural:X:second-source"],
        )
    )

    full = finalize_partial_reader_observations(partial)

    assert full.overall_dimensions.length_x == 40


def test_finalizer_rejects_missing_overall_axis():
    partial = _partial()
    partial.overall_dimension_facts = [
        item for item in partial.overall_dimension_facts if item.axis != "Y"
    ]

    with pytest.raises(
        ReaderObservationFinalizationError,
        match="missing overall dimension fact for axis Y",
    ):
        finalize_partial_reader_observations(partial)


def test_finalizer_rejects_conflicting_overall_axis_facts():
    partial = _partial()
    partial.overall_dimension_facts.append(
        PartialOverallDimensionFact(
            axis="X",
            value=41,
            evidence=["structural:X:conflict"],
        )
    )

    with pytest.raises(
        ReaderObservationFinalizationError,
        match="conflicting overall dimension facts for axis X",
    ):
        finalize_partial_reader_observations(partial)


def test_finalizer_rejects_missing_explicit_view():
    partial = _partial()
    partial.views = []

    with pytest.raises(
        ReaderObservationFinalizationError,
        match="at least one explicit view",
    ):
        finalize_partial_reader_observations(partial)
