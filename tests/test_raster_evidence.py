from __future__ import annotations

from nx_mcp.drawing_intelligence.raster_evidence import (
    _adapt_probe,
    _witness_line_evidence,
    extract_raw_evidence,
    fragment_length_limits,
)


def test_fragment_length_limits_preserve_reference_scale():
    assert fragment_length_limits(1774) == (10, 90)


def test_fragment_length_limits_scale_with_image_width():
    reference = fragment_length_limits(1774)
    for width in (1331, 2218):
        minimum, maximum = fragment_length_limits(width)
        scale = width / 1774
        assert abs(minimum - reference[0] * scale) <= 1.0
        assert abs(maximum - reference[1] * scale) <= 1.0


def test_fragment_length_limits_reject_invalid_width():
    try:
        fragment_length_limits(0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_probe_adapter_stays_geometry_only():
    probe = {
        "image": {"width": 1000, "height": 500},
        "probe_parameters": {
            "fragment_length_limits_px": [6, 51],
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox": {
                    "x": 100,
                    "y": 50,
                    "width": 400,
                    "height": 300,
                },
                "circle_evidence": [
                    {
                        "cx": 300,
                        "cy": 200,
                        "radius_px": 50,
                        "edge_support": 0.95,
                    }
                ],
                "fragment_groups": [
                    {
                        "orientation": "horizontal",
                        "axis_px": 160.0,
                        "segments": [
                            [120, 140],
                            [155, 175],
                            [190, 210],
                            [225, 245],
                        ],
                        "positive_gaps_px": [15, 15, 15],
                        "kind": "dashed_or_centerline_candidate",
                    }
                ],
            }
        ],
    }

    raw = _adapt_probe(probe)

    assert raw["schema"] == "raw-evidence-v0"
    assert raw["semantics_policy"] == "geometry_only_no_engineering_claims"
    assert raw["probe_parameters"]["fragment_length_limits_px"] == [6, 51]
    assert raw["regions"][0]["bbox_px"] == [100, 50, 400, 300]
    assert raw["regions"][0]["circle_groups"][0]["center_px"] == [300, 200]
    assert raw["regions"][0]["linear_pattern_candidates"][0]["kind"] == (
        "dashed_or_centerline_candidate"
    )


def test_extract_raw_evidence_from_synthetic_engineering_drawing(tmp_path):
    import cv2
    import numpy as np

    image = np.full((650, 1200, 3), 255, np.uint8)

    cv2.rectangle(image, (100, 100), (520, 400), (0, 0, 0), 3)
    cv2.circle(image, (310, 240), 80, (0, 0, 0), 3)
    for x in range(180, 440, 28):
        cv2.line(image, (x, 240), (x + 14, 240), (0, 0, 0), 2)
    for y in range(140, 350, 28):
        cv2.line(image, (310, y), (310, y + 14), (0, 0, 0), 2)

    cv2.rectangle(image, (720, 120), (980, 410), (0, 0, 0), 3)
    for y in range(150, 380, 30):
        cv2.line(image, (800, y), (800, y + 15), (0, 0, 0), 2)
        cv2.line(image, (900, y), (900, y + 15), (0, 0, 0), 2)

    cv2.line(image, (100, 470), (520, 470), (0, 0, 0), 2)
    cv2.line(image, (100, 400), (100, 490), (0, 0, 0), 2)
    cv2.line(image, (520, 400), (520, 490), (0, 0, 0), 2)
    cv2.line(image, (180, 440), (440, 440), (0, 0, 0), 2)
    cv2.line(image, (180, 390), (180, 460), (0, 0, 0), 2)
    cv2.line(image, (440, 390), (440, 460), (0, 0, 0), 2)

    cv2.line(image, (580, 100), (580, 400), (0, 0, 0), 2)
    cv2.line(image, (520, 100), (600, 100), (0, 0, 0), 2)
    cv2.line(image, (520, 400), (600, 400), (0, 0, 0), 2)

    cv2.line(image, (720, 470), (980, 470), (0, 0, 0), 2)
    cv2.line(image, (720, 410), (720, 490), (0, 0, 0), 2)
    cv2.line(image, (980, 410), (980, 490), (0, 0, 0), 2)

    image_path = tmp_path / "synthetic-drawing.png"
    assert cv2.imwrite(str(image_path), image)

    raw = extract_raw_evidence(image_path)

    assert raw["schema"] == "raw-evidence-v1"
    assert raw["semantics_policy"] == "geometry_only_no_engineering_claims"
    assert raw["summary"]["region_count"] == 2
    assert raw["summary"]["circle_group_count"] >= 1
    assert raw["summary"]["linear_pattern_candidate_count"] >= 1
    assert raw["summary"]["dimension_geometry_candidate_count"] >= 1
    assert raw["probe_parameters"]["fragment_length_limits_px"] == [7, 61]
    assert all(
        item["status"] == "candidate_only_no_semantics"
        for item in raw["dimension_geometry_candidates"]
    )
    assert all(
        len(item["witness_line_evidence"]) == len(item["witness_positions_px"])
        for item in raw["dimension_geometry_candidates"]
    )
    assert all(
        all("source_lines" in witness for witness in item["witness_line_evidence"])
        for item in raw["dimension_geometry_candidates"]
    )

def test_witness_line_evidence_excludes_same_axis_lines_from_other_region():
    evidence = _witness_line_evidence(
        [50.0],
        [
            ("vertical", 50.0, 10, 90),
            ("vertical", 50.0, 210, 260),
        ],
        dimension_axis=80.0,
        witness_axis_tolerance=2.0,
        cross_tolerance=5.0,
        region_bbox=[0, 0, 100, 100],
        region_margin=5.0,
    )

    assert evidence == [
        {
            "witness_index": 0,
            "position_px": 50.0,
            "source_lines": [
                {
                    "orientation": "vertical",
                    "axis_px": 50.0,
                    "span_px": [10, 90],
                    "span_length_px": 80,
                    "crosses_dimension_axis": True,
                }
            ],
        }
    ]

