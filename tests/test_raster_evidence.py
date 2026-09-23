from __future__ import annotations

from nx_mcp.drawing_intelligence.raster_evidence import (
    _adapt_probe,
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
