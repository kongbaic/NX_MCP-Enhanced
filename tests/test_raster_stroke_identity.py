from __future__ import annotations

import cv2
import numpy as np
import pytest

from nx_mcp.drawing_intelligence.raster_stroke_identity import (
    single_ink_stroke_alias,
)
from nx_mcp.drawing_intelligence.dimension_endpoint_candidates import (
    derive_dimension_endpoint_candidates,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    _resolve_raster_proven_endpoint_aliases,
)
from nx_mcp.drawing_intelligence.view_metric_calibration import (
    derive_view_axis_boundaries,
)


def _pair():
    return [
        {"kind": "profile_edge_candidate", "ref": "edge_strong",
         "source_orientation": "horizontal", "position_px": 550.0,
         "span_px": [84.0, 412.0], "relative_extreme_side": "max",
         "axis_tolerance_px": 3.0, "independent_geometry_source_count": 2,
         "non_dimension_crossing_source_count": 16},
        {"kind": "profile_edge_candidate", "ref": "edge_weak",
         "source_orientation": "horizontal", "position_px": 551.1,
         "span_px": [83.0, 465.0], "relative_extreme_side": "max",
         "axis_tolerance_px": 3.0, "independent_geometry_source_count": 3,
         "non_dimension_crossing_source_count": 1},
    ]


def _raster(tmp_path, *, two_lines=False):
    image = np.full((650, 600), 255, dtype=np.uint8)
    image[550:553, 90:460] = 2
    if two_lines:
        image[546:548, 90:460] = 2
    path = tmp_path / "test.png"
    assert cv2.imwrite(str(path), image)
    return str(path)


def test_alias_needs_a_single_supported_raster_stroke(tmp_path):
    path = _raster(tmp_path)
    pair = _pair()
    assert single_ink_stroke_alias(pair, path)["ref"] == "edge_strong"
    assert single_ink_stroke_alias(pair, str(tmp_path / "absent.png")) is None
    assert single_ink_stroke_alias(pair, None) is None
    pair[1]["non_dimension_crossing_source_count"] = 0
    assert single_ink_stroke_alias(pair, path) is None


def test_distinct_strokes_and_incompatible_boundaries_remain_ambiguous(tmp_path):
    pair = _pair()
    assert single_ink_stroke_alias(pair, _raster(tmp_path, two_lines=True)) is None
    path = _raster(tmp_path)
    pair[1]["relative_extreme_side"] = "min"
    assert single_ink_stroke_alias(pair, path) is None
    pair = _pair()
    pair[1]["position_px"] = 555.0
    assert single_ink_stroke_alias(pair, path) is None
    pair = _pair()
    pair[1]["span_px"] = [350.0, 600.0]
    assert single_ink_stroke_alias(pair, path) is None


def test_endpoint_narrowing_uses_only_raster_proven_identity(tmp_path):
    pair = _pair()
    candidate = {
        "candidate_id": "DG_generic",
        "orientation": "vertical",
        "accepted_token": "40",
        "global_assignments": [{"token": "40", "bbox": [
            [420, 360], [460, 360], [460, 390], [420, 390],
        ]}],
        "witness_positions_px": [315.0, 550.5],
        "witness_anchor_evidence": [
            {"witness_index": 0, "nearest_anchors": [{
                "kind": "circle_center_axis", "ref": "center", "position_px": 315.0
            }]},
            {"witness_index": 1, "nearest_anchors": pair},
        ],
        "witness_line_evidence": [{
            "witness_index": 1,
            "source_lines": [{
                "orientation": "horizontal",
                "axis_px": 550.5,
                "span_px": [180.0, 410.0],
                "crosses_dimension_axis": True,
            }],
        }],
        "axis_px": 400.0,
    }
    bare = derive_dimension_endpoint_candidates(candidate)
    assert bare["endpoints"][1]["status"] == "ambiguous_physical_candidates"
    resolved = _resolve_raster_proven_endpoint_aliases(
        bare, source_raster_path=_raster(tmp_path)
    )
    assert resolved["endpoints"][1]["status"] == "unique_physical_candidate"
    assert resolved["endpoints"][1]["ownership_narrowing_basis"] == (
        "unique_single_raster_stroke_profile_identity"
    )
    assert resolved["numeric_value_used_for_geometry"] is False
    # A second nearby real line must keep BOTH physical possibilities.
    rejected = _resolve_raster_proven_endpoint_aliases(
        bare, source_raster_path=_raster(tmp_path, two_lines=True)
    )
    assert rejected["endpoints"][1]["status"] == "ambiguous_physical_candidates"


def _profile_overall_fixture():
    first, second = _pair()
    first = {**first, "region_id": "R_TEST"}
    second = {**second, "region_id": "R_TEST"}
    minimum = {
        **first,
        "ref": "independent_upper_contour",
        "relative_extreme_side": "min",
        "position_px": 200.0,
        "span_px": [85.0, 470.0],
        "non_dimension_crossing_source_count": 8,
    }
    return [minimum, first, second]


def _derive_overall(profile_inventory, raster):
    return derive_view_axis_boundaries(
        candidates=[],
        region_views={"R_TEST": "front"},
        overall_dimensions={"length_x": 50.0, "width_y": 35.0, "height_z": 80.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R_TEST", "Z")},
        source_raster_path=raster,
    )


def test_shared_stroke_identity_closes_independent_overall_extreme(tmp_path):
    # The 80mm comes exclusively from the independent structural evidence.
    # The image ONLY verifies duplicate detections of one physical edge.
    inventory = _profile_overall_fixture()
    assert _derive_overall(inventory, None) == []
    resolved = _derive_overall(inventory, _raster(tmp_path))
    assert len(resolved) == 1
    boundary = resolved[0]
    assert boundary["status"] == "resolved"
    assert boundary["axis"] == "Z"
    assert boundary["overall_dimension_value"] == 80.0
    assert boundary["engineering_coordinate_inferred_from_pixels"] is False
    assert {item["role"] for item in boundary["anchors"]} == {
        "overall_min", "overall_max"
    }
    assert any(
        item["ref"] == "edge_strong" and item["role"] == "overall_min"
        for item in boundary["anchors"]
    )


def test_overall_extreme_does_not_promote_parallel_lines_or_wrong_scope(tmp_path):
    inventory = _profile_overall_fixture()
    assert _derive_overall(inventory, _raster(tmp_path, two_lines=True)) == []
    inventory[2]["non_dimension_crossing_source_count"] = 0
    assert _derive_overall(inventory, _raster(tmp_path)) == []
    # Global Z in another region does not prove this contour's Z bounds.
    assert derive_view_axis_boundaries(
        candidates=[],
        region_views={"R_TEST": "front"},
        overall_dimensions={"length_x": 50.0, "width_y": 35.0, "height_z": 80.0},
        profile_inventory=_profile_overall_fixture(),
        region_overall_fact_axes={("OTHER", "Z")},
        source_raster_path=_raster(tmp_path),
    ) == []



@pytest.mark.parametrize(
    ("two_lines", "missing_raster", "expected_advisory"),
    [
        (False, False, True),
        (True, False, False),
        (False, True, False),
    ],
)
def test_local_only_overall_reuses_raster_proven_duplicate_contour(
    tmp_path, two_lines, missing_raster, expected_advisory,
):
    """Shared ink is one physical owner; distinct strokes stay blocking."""
    from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
        HybridRegionView, _coverage_unresolved,
    )
    from nx_mcp.drawing_intelligence.reader_semantic_answers import (
        PartialOverallDimensionFact,
    )

    strong, weak = _pair()
    # Match production's region-scoped raster profile inventory: candidates
    # with no region_id must not acquire engineering endpoint ownership.
    strong = {**strong, "region_id": "R_TEST"}
    weak = {**weak, "region_id": "R_TEST"}
    upper = {
        **strong,
        "ref": "upper_independent",
        "position_px": 200.0,
        "relative_extreme_side": "min",
    }
    raster = _raster(tmp_path, two_lines=two_lines)
    if missing_raster:
        raster = str(tmp_path / "missing.png")

    candidate = {
        "candidate_id": "DG_LOCAL_OVERALL",
        "region_id": "R_TEST",
        "orientation": "vertical",
        "accepted_token": None,
        "witness_positions_px": [200.0, 550.2],
        "witness_anchor_evidence": [
            {"witness_index": 0, "nearest_anchors": [upper]},
            {"witness_index": 1, "nearest_anchors": [strong, weak]},
        ],
        "witness_line_evidence": [
            {"witness_index": 0, "source_lines": [{
                "crosses_dimension_axis": True
            }]},
            {"witness_index": 1, "source_lines": [{
                "crosses_dimension_axis": True
            }]},
        ],
    }
    boundary = {
        "status": "resolved",
        "region_id": "R_TEST",
        "axis": "Z",
        "candidate_id": None,
        "overall_dimension_value": 66.0,
        "anchors": [
            {"ref": "upper_independent", "role": "overall_max"},
            {"ref": "edge_strong", "role": "overall_min"},
        ],
        "basis": "independent_overall_dimension_plus_unique_profile_extremes",
        "overall_fact_scope": "same_region_structural_evidence",
        "engineering_coordinate_inferred_from_pixels": False,
    }
    report = {
        "source_raster": raster,
        "structural_profile_inventory": [upper, strong, weak],
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "unassigned_linear_observations": [
                {
                    "source_item_index": 9,
                    "token": "6",
                    "bbox": [[7, 357], [47, 357], [47, 402], [7, 402]],
                }
            ],
            "local_only_linear_observations": [
                {"candidate_id": "DG_LOCAL_OVERALL", "token": "66"}
            ],
        },
    }
    unresolved = _coverage_unresolved(
        report,
        {"DG_LOCAL_OVERALL": candidate},
        {"R_TEST": HybridRegionView(
            region_id="R_TEST", view_kind="front", evidence=["test:R_TEST"]
        )},
        boundaries=[boundary],
        overall_dimension_facts=[
            PartialOverallDimensionFact(
                axis="Z",
                value=66.0,
                evidence=["structural:R_TEST:context"],
            )
        ],
    )
    local = next(item for item in unresolved if item.field == "local_only_linear_text")
    whole = next(item for item in unresolved if item.field == "unassigned_linear_text")
    assert (not local.required_for_modeling) is expected_advisory
    assert whole.required_for_modeling is True
    if expected_advisory:
        assert "advisory duplicate coverage" in local.reason
