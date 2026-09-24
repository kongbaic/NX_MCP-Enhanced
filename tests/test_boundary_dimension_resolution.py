from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservations,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.view_metric_calibration import (
    derive_view_axis_boundaries,
)


def _profile(
    ref: str,
    *,
    position_px: float,
    side: str,
) -> dict[str, object]:
    return {
        "region_id": "R1",
        "kind": "profile_edge_candidate",
        "ref": ref,
        "position_px": position_px,
        "source_orientation": "horizontal",
        "span_px": [80, 320],
        "relative_extreme_side": side,
        "candidate_only": True,
        "ownership_claimed": False,
    }


def _overall_candidate() -> dict[str, object]:
    return {
        "candidate_id": "DG_OVERALL",
        "region_id": "R1",
        "orientation": "vertical",
        "accepted_token": None,
        "global_proposal_token": "6",
        "decision_reason": "global_local_token_disagreement",
        "wide_local_linear_tokens": ["66"],
        "global_assignments": [
            {
                "source_item_index": 9,
                "text": "6",
                "token": "6",
                "bbox": [
                    [10.0, 180.0],
                    [40.0, 180.0],
                    [40.0, 220.0],
                    [10.0, 220.0],
                ],
            }
        ],
        "witness_positions_px": [100.0, 300.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 100.0,
                "nearest_anchors": [
                    {
                        **_profile(
                            "R1.structural.horizontal.TOP",
                            position_px=100.0,
                            side="min",
                        ),
                    }
                ],
            },
            {
                "witness_index": 1,
                "position_px": 300.0,
                "nearest_anchors": [
                    {
                        **_profile(
                            "R1.structural.horizontal.BOTTOM",
                            position_px=300.0,
                            side="max",
                        ),
                    }
                ],
            },
        ],
    }


def test_vertical_overall_dimension_identifies_bottom_without_pixel_metric_inference():
    boundaries = derive_view_axis_boundaries(
        candidates=[_overall_candidate()],
        region_views={"R1": "front"},
        overall_dimensions={"height_z": 66.0},
    )

    assert len(boundaries) == 1
    item = boundaries[0]
    assert item["status"] == "resolved"
    assert item["axis"] == "Z"
    assert item["engineering_coordinate_inferred_from_pixels"] is False
    assert item["ocr_conflict_preserved"] is True
    assert {
        anchor["ref"]: anchor["role"] for anchor in item["anchors"]
    } == {
        "R1.structural.horizontal.TOP": "overall_max",
        "R1.structural.horizontal.BOTTOM": "overall_min",
    }
    assert all("coordinate_mm" not in anchor for anchor in item["anchors"])


def _report() -> dict[str, object]:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [
                {
                    "candidate_id": "DG_OVERALL",
                    "source_item_index": 9,
                    "token": "6",
                    "local_tokens": ["66"],
                }
            ],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [
                {
                    "candidate_id": "DG_OVERALL",
                    "token": "66",
                }
            ],
            "routed_elsewhere_or_unclassified_observations": [],
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 400],
                "circle_groups": [
                    {
                        "circle_group_id": "C1",
                        "center_px": [200, 150],
                        "rings": [{"radius_px": 40}],
                    }
                ],
            }
        ],
        "annotation_line_candidates": [],
        "structural_profile_inventory": [
            _profile(
                "R1.structural.horizontal.TOP",
                position_px=100.0,
                side="min",
            ),
            _profile(
                "R1.structural.horizontal.BOTTOM",
                position_px=300.0,
                side="max",
            ),
        ],
        "candidates": [
            {
                **_overall_candidate(),
                # Exercise production inventory enrichment rather than relying
                # on pre-attached profile anchors.
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 100.0,
                        "nearest_anchors": [],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 300.0,
                        "nearest_anchors": [],
                    },
                ],
            },
            {
                "candidate_id": "DG_CENTER_FROM_BOTTOM",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": "40±0.02",
                "global_proposal_token": "40±0.02",
                "decision_reason": "global_geometry_assignment_confirmed_by_local_roi",
                "wide_local_linear_tokens": ["40±0.02"],
                "global_assignments": [
                    {
                        "source_item_index": 10,
                        "text": "40±0.02",
                        "token": "40±0.02",
                        "bbox": [
                            [350.0, 200.0],
                            [390.0, 200.0],
                            [390.0, 240.0],
                            [350.0, 240.0],
                        ],
                    }
                ],
                "witness_positions_px": [150.0, 300.0],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 150.0,
                        "nearest_anchors": [
                            {
                                "kind": "circle_center_axis",
                                "ref": "R1.C1.center_y",
                                "position_px": 150.0,
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 300.0,
                        "nearest_anchors": [
                            {
                                "kind": "linear_pattern_axis",
                                "ref": "R1.linear_pattern.BOTTOM",
                                "position_px": 300.0,
                            }
                        ],
                    },
                ],
            },
        ],
    }


def _context() -> HybridAdapterContext:
    return HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "evidence": ["structural:R1"],
                }
            ],
            "overall_dimension_facts": [
                {
                    "axis": "Z",
                    "value": 66,
                    "evidence": ["overall:Z"],
                }
            ],
        }
    )


def test_adapter_closes_bottom_to_circle_center_dimension_without_pixel_scaling():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    boundary_ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_view_axis_boundary_ledger"
    )
    assert boundary_ledger["engineering_coordinate_inferred_from_pixels"] is False
    boundary = boundary_ledger["items"][0]
    assert {
        anchor["ref"]: anchor["role"] for anchor in boundary["anchors"]
    }["R1.structural.horizontal.BOTTOM"] == "overall_min"

    dimension = next(
        item
        for item in partial.dimensions
        if item.key == "R1.DG_CENTER_FROM_BOTTOM"
    )
    assert dimension.unresolved_reason is None
    assert [endpoint.role for endpoint in dimension.endpoints] == [
        "entity_center",
        "overall_min",
    ]
    assert dimension.endpoints[0].entity_key == "R1.C1"
    assert dimension.endpoints[0].basis == "circle_center"

    metric_ledgers = [
        item
        for item in partial.observations
        if item["kind"]
        in {
            "hybrid_view_metric_calibration_ledger",
            "hybrid_metric_profile_edge_ledger",
            "hybrid_metric_profile_segment_ledger",
            "hybrid_metric_circle_primitive_ledger",
        }
    ]
    assert metric_ledgers
    assert all(item["engineering_authoritative"] is False for item in metric_ledgers)


def test_bottom_to_circle_center_dimension_resolves_exact_z40_through_existing_pipeline():
    partial = adapt_hybrid_ocr_report(_report(), _context())
    dimension = next(
        item
        for item in partial.dimensions
        if item.key == "R1.DG_CENTER_FROM_BOTTOM"
    )
    circle = next(item for item in partial.entities if item.key == "R1.C1")

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=[circle],
        dimensions=[dimension],
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    center_z = {
        target: value
        for target, value in resolution.values.items()
        if target.endswith(".centerline.z")
    }
    assert len(center_z) == 1
    assert next(iter(center_z.values())) == 40.0

    edge_offsets = [
        item
        for item in compiled.relations
        if item.kind == "edge_offset" and item.axis == "Z"
    ]
    assert len(edge_offsets) == 1
    assert edge_offsets[0].value == 40.0
    assert edge_offsets[0].from_side == "min"
