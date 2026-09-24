from __future__ import annotations

from nx_mcp.drawing_intelligence.reader_visual_aid import (
    build_reader_visual_aid,
)


def _candidate(
    candidate_id: str,
    *,
    orientation: str,
    axis_local_norm: float,
    witnesses: list[float],
) -> dict:
    return {
        "candidate_id": candidate_id,
        "region_id": "R1",
        "orientation": orientation,
        "axis_px": axis_local_norm * 100,
        "axis_local_norm": axis_local_norm,
        "line_span_px": [0, 100],
        "witness_positions_px": witnesses,
        "witness_positions_local_norm": [value / 100 for value in witnesses],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "position_px": value,
                "source_lines": [
                    {
                        "orientation": (
                            "vertical" if orientation == "horizontal" else "horizontal"
                        ),
                        "axis_px": value,
                        "span_px": [0, 100],
                        "span_length_px": 100,
                        "crosses_dimension_axis": True,
                    }
                ],
            }
            for index, value in enumerate(witnesses)
        ],
        "status": "candidate_only_no_semantics",
    }


def _raw() -> dict:
    candidates = [
        _candidate(
            "DG_TOP_1",
            orientation="horizontal",
            axis_local_norm=0.10,
            witnesses=[10.0, 90.0],
        ),
        _candidate(
            "DG_TOP_2",
            orientation="horizontal",
            axis_local_norm=0.15,
            witnesses=[20.0, 80.0],
        ),
        _candidate(
            "DG_TOP_3",
            orientation="horizontal",
            axis_local_norm=0.20,
            witnesses=[30.0, 70.0],
        ),
    ]
    for index in range(5):
        candidates.append(
            _candidate(
                f"DG_BOTTOM_{index + 1}",
                orientation="horizontal",
                axis_local_norm=0.80 + index * 0.02,
                witnesses=[
                    5.0 + index * 6,
                    60.0 + index * 6,
                ],
            )
        )

    return {
        "schema": "raw-evidence-v1",
        "image": {"width": 100, "height": 100},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 100, 100],
                "bbox_norm": [0.0, 0.0, 1.0, 1.0],
                "circle_groups": [],
                "linear_pattern_candidates": [
                    {
                        "orientation": "vertical",
                        "axis_px": 10.0,
                        "kind": "dashed_or_centerline_candidate",
                        "dash_score": 0.9,
                    },
                    {
                        "orientation": "vertical",
                        "axis_px": 90.0,
                        "kind": "dashed_or_centerline_candidate",
                        "dash_score": 0.9,
                    },
                ],
            }
        ],
        "dimension_geometry_candidates": candidates,
    }


def test_reader_visual_aid_bounds_and_enriches_small_buckets():
    result = build_reader_visual_aid(_raw())
    buckets = {item["bucket_id"]: item for item in result["candidate_buckets"]}

    top = buckets["R1.horizontal.top"]
    assert top["status"] == "bounded"
    assert top["candidate_count"] == 3
    assert [item["candidate_id"] for item in top["candidates"]] == [
        "DG_TOP_1",
        "DG_TOP_2",
        "DG_TOP_3",
    ]
    assert top["candidates"][0]["witness_anchor_evidence"]
    assert top["candidates"][0]["witness_line_evidence"]
    assert result["semantics_policy"] == ("geometry_only_no_engineering_claims")
    assert result["source_drawing_authoritative"] is True


def test_reader_visual_aid_never_truncates_overflow_bucket():
    result = build_reader_visual_aid(_raw())
    buckets = {item["bucket_id"]: item for item in result["candidate_buckets"]}

    bottom = buckets["R1.horizontal.bottom"]
    assert bottom["status"] == "overflow"
    assert bottom["candidate_count"] == 5
    assert bottom["candidates"] == []
    assert result["summary"]["overflow_bucket_count"] == 1
    assert result["summary"]["max_bucket_candidate_count"] == 5
    assert result["rules"]["candidate_truncation"] is False


def test_reader_visual_aid_rejects_non_v1_input():
    raw = _raw()
    raw["schema"] = "raw-evidence-v0"

    try:
        build_reader_visual_aid(raw)
    except ValueError as exc:
        assert "raw-evidence-v1" in str(exc)
    else:
        raise AssertionError("expected ValueError")
