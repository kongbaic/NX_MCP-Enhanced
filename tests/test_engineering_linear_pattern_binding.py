from __future__ import annotations

from nx_mcp.drawing_intelligence import link_reader_capture
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.engineering_linear_pattern_binding import (
    bind_callout_to_linear_pattern,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservations,
    assemble_reader_capture,
)


def _region() -> dict[str, object]:
    return {
        "region_id": "R1",
        "bbox_px": [0, 0, 400, 300],
        "circle_groups": [],
        "linear_pattern_candidates": [
            {
                "orientation": "horizontal",
                "axis_px": 200.0,
                "span_px": [140, 360],
                "kind": "dashed_or_centerline_candidate",
            },
            {
                "orientation": "horizontal",
                "axis_px": 224.0,
                "span_px": [220, 360],
                "kind": "dashed_or_centerline_candidate",
            },
        ],
    }


def test_oblique_leader_binds_unique_linear_pattern_with_margin():
    result = bind_callout_to_linear_pattern(
        [[20, 20], [120, 20], [120, 70], [20, 70]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 66], [160, 197]],
                "angle_deg": 71.0,
                "length_px": 138.5,
                "candidate_only": True,
            }
        ],
        _region(),
        view_kind="front",
    )

    assert result["status"] == "bound"
    assert result["pattern_index"] == 0
    assert result["orientation"] == "horizontal"
    assert result["axis"] == "X"
    assert result["pattern_target_distance_px"] == 3.0
    assert result["basis"] == "callout_oblique_leader_to_unique_linear_pattern"


def test_linear_pattern_binding_fails_closed_without_target_margin():
    region = _region()
    region["linear_pattern_candidates"] = [
        {
            "orientation": "horizontal",
            "axis_px": 198.0,
            "span_px": [140, 360],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 202.0,
            "span_px": [140, 360],
            "kind": "dashed_or_centerline_candidate",
        },
    ]

    result = bind_callout_to_linear_pattern(
        [[20, 20], [120, 20], [120, 70], [20, 70]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 66], [160, 200]],
                "angle_deg": 71.0,
                "length_px": 140.5,
                "candidate_only": True,
            }
        ],
        region,
        view_kind="front",
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "multiple_linear_pattern_targets_without_margin"


def _m6_report() -> dict[str, object]:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 1,
                    "text": "M6深12",
                    "bbox": [
                        [20.0, 20.0],
                        [120.0, 20.0],
                        [120.0, 70.0],
                        [20.0, 70.0],
                    ],
                    "confidence": 0.99,
                }
            ],
        },
        "regions": [_region()],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 66], [160, 197]],
                "angle_deg": 71.0,
                "length_px": 138.5,
                "candidate_only": True,
            }
        ],
        "candidates": [],
    }


def test_m6_hidden_projection_carries_axis_thread_and_depth_to_linker():
    context = HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "evidence": ["structural:R1"],
                }
            ],
        }
    )
    partial = adapt_hybrid_ocr_report(_m6_report(), context)

    assert len(partial.entities) == 1
    entity = partial.entities[0]
    assert entity.shape == "hidden_parallel"

    values = {
        item.field: item.value
        for item in partial.values
        if item.entity_key == entity.key
    }
    assert values == {
        "axis": "X",
        "thread_depth": 12.0,
        "thread_spec": "M6",
    }

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=partial.entities,
        values=partial.values,
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)

    feature_id = linked.entity_to_feature[next(iter(linked.entity_to_feature))]
    direct = {
        item.target: item.value
        for item in linked.evidence.direct_values
    }
    assert direct[f"feature:{feature_id}.axis"] == "X"
    assert direct[f"feature:{feature_id}.thread_spec"] == "M6"
    assert direct[f"feature:{feature_id}.thread_depth"] == 12.0
    assert not any(
        target.startswith(f"feature:{feature_id}.centerline.")
        for target in direct
    )



def test_linear_pattern_coincident_with_structural_profile_is_not_hidden_owner():
    result = bind_callout_to_linear_pattern(
        [[20, 20], [120, 20], [120, 70], [20, 70]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 66], [160, 197]],
                "angle_deg": 71.0,
                "length_px": 138.5,
                "candidate_only": True,
            }
        ],
        _region(),
        view_kind="front",
        profile_inventory=[
            {
                "region_id": "R1",
                "kind": "profile_edge_candidate",
                "ref": "R1.structural.horizontal.001",
                "position_px": 200.5,
                "source_orientation": "horizontal",
                "span_px": [100, 360],
            }
        ],
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "no_leader_to_linear_pattern_match"
