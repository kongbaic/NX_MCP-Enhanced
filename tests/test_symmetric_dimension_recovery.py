from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservations,
    assemble_reader_capture,
)


def test_real_like_right_view_16_and_8_resolve_upper_hole_y24():
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [
                {
                    "source_item_index": 0,
                    "text": "16",
                    "token": "16",
                    "bbox": [
                        [724.0, 73.0],
                        [769.0, 73.0],
                        [769.0, 115.0],
                        [724.0, 115.0],
                    ],
                },
                {
                    "source_item_index": 4,
                    "text": "8",
                    "token": "8",
                    "bbox": [
                        [812.0, 120.0],
                        [838.0, 120.0],
                        [838.0, 156.0],
                        [812.0, 156.0],
                    ],
                },
            ],
            "local_only_linear_observations": [],
            "routed_elsewhere_or_unclassified_observations": [],
        },
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [617, 109, 250, 561],
                "circle_groups": [
                    {
                        "circle_group_id": "C1",
                        "center_px": [745.0, 234.0],
                        "rings": [
                            {"radius_px": 17.0},
                            {"radius_px": 28.0},
                        ],
                    }
                ],
                "linear_pattern_candidates": [],
            }
        ],
        "annotation_line_candidates": [],
        "structural_profile_inventory": [
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.LEFT_OVERALL",
                "position_px": 620.667,
                "source_orientation": "vertical",
                "span_px": [482, 667],
                "relative_extreme_side": "min",
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.BOSS_LEFT",
                "position_px": 703.7,
                "source_orientation": "vertical",
                "span_px": [110, 482],
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.RIGHT_OVERALL",
                "position_px": 785.8,
                "source_orientation": "vertical",
                "span_px": [110, 667],
                "relative_extreme_side": "max",
            },
        ],
        "candidates": [
            {
                "candidate_id": "DG1",
                "region_id": "R2",
                "orientation": "horizontal",
                "axis_px": 160.0,
                "line_span_px": [737, 795],
                "witness_positions_px": [703.7, 744.0, 785.8],
                "witness_anchor_evidence": [],
                "accepted_token": None,
                "global_assignments": [],
            }
        ],
    }
    context = HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R2",
                    "view_kind": "side",
                    "evidence": ["test:R2"],
                }
            ],
            "overall_dimension_facts": [
                {
                    "axis": "Y",
                    "value": 32,
                    "evidence": ["test:overall-y"],
                }
            ],
        }
    )

    partial = adapt_hybrid_ocr_report(report, context)
    recovered = [
        item
        for item in partial.dimensions
        if item.key.startswith("R2.RECOVERED_HALF_")
    ]
    assert len(recovered) == 1
    dimension = recovered[0]
    assert dimension.value == 8.0
    assert dimension.axis == "Y"
    assert [item.role for item in dimension.endpoints] == [
        "entity_center",
        "overall_max",
    ]
    assert dimension.endpoints[0].entity_key == "R2.C1"

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=partial.entities,
        dimensions=[dimension],
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    circle_entity = next(
        item for item in capture.entities if item.source_key == "R2.C1"
    )
    feature_id = linked.entity_to_feature[circle_entity.id]
    assert resolution.values[f"feature:{feature_id}.centerline.y"] == 24.0

    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_symmetric_dimension_recovery_ledger"
    )
    assert ledger["items"][0]["engineering_coordinate_inferred_from_pixels"] is False
