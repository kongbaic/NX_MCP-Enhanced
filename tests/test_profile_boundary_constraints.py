from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.reader_observations import (
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationEntity,
    ObservationView,
    ReaderObservations,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.draft import build_semantic_draft


def test_internal_profile_boundary_resolves_from_overall_max_dimension():
    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            ObservationView(
                key="R2",
                kind="side",
                evidence=["test:R2"],
            )
        ],
        entities=[
            ObservationEntity(
                key="R2.STEP_EDGE",
                view_key="R2",
                shape="profile",
                cross_view_disposition="single_view",
                evidence=["test:step-edge"],
            )
        ],
        dimensions=[
            ObservationDimension(
                key="R2.STEP_TO_RIGHT",
                value=24,
                axis="Y",
                endpoints=[
                    ObservationDimensionEndpoint(
                        role="profile_boundary",
                        entity_key="R2.STEP_EDGE",
                        basis="profile_edge",
                        evidence=["test:step-edge"],
                    ),
                    ObservationDimensionEndpoint(
                        role="overall_max",
                        evidence=["test:right-edge"],
                    ),
                ],
                evidence=["test:dimension-24"],
                required_for_modeling=True,
            )
        ],
    )

    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    profile_entity = next(
        item for item in capture.entities if item.source_key == "R2.STEP_EDGE"
    )
    feature_id = linked.entity_to_feature[profile_entity.id]
    target = f"feature:{feature_id}.boundary.y"

    assert resolution.values[target] == 8.0
    assert len(compiled.relations) == 1
    relation = compiled.relations[0]
    assert relation.kind == "edge_offset"
    assert relation.axis == "Y"
    assert relation.from_side == "max"
    assert relation.value == 24.0
    assert relation.targets == [target]

    draft = build_semantic_draft(compiled, resolution)
    feature = next(item for item in draft["features"] if item["id"] == feature_id)
    assert feature["boundary"]["y"] == -8.0

    derived = next(
        item
        for item in draft["derived_dimensions"]
        if item.get("target") == target
    )
    assert derived["reader_local_value"] == 8.0
    assert derived["value"] == -8.0
