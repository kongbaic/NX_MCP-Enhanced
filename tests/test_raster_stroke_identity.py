from __future__ import annotations

import cv2
import numpy as np

from nx_mcp.drawing_intelligence.raster_stroke_identity import (
    single_ink_stroke_alias,
)
from nx_mcp.drawing_intelligence.dimension_endpoint_candidates import (
    derive_dimension_endpoint_candidates,
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
        "witness_line_evidence": [],
        "axis_px": 460.0,
    }
    bare = derive_dimension_endpoint_candidates(candidate)
    assert bare["endpoints"][1]["status"] == "ambiguous_physical_candidates"
    resolved = derive_dimension_endpoint_candidates(
        candidate, source_raster_path=_raster(tmp_path)
    )
    assert resolved["endpoints"][1]["status"] == "unique_physical_candidate"
    assert resolved["endpoints"][1]["ownership_narrowing_basis"] == (
        "unique_single_raster_stroke_profile_identity"
    )
    assert resolved["numeric_value_used_for_geometry"] is False
    # A second nearby real line must keep BOTH physical possibilities.
    rejected = derive_dimension_endpoint_candidates(
        candidate, source_raster_path=_raster(tmp_path, two_lines=True)
    )
    assert rejected["endpoints"][1]["status"] == "ambiguous_physical_candidates"
