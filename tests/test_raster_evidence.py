from __future__ import annotations

from nx_mcp.drawing_intelligence.raster_evidence import (
    _axis_ink_continuity,
    _compact_fragments,
    _curved_annotation_candidates,
    _radial_gradient_alignment,
    _adapt_probe,
    _oblique_annotation_lines,
    _one_sided_boundary_evidence,
    _region_scoped_witnesses,
    _witness_line_evidence,
    extract_raw_evidence,
    fragment_length_limits,
)


def test_radial_gradient_alignment_accepts_true_circle():
    import cv2
    import numpy as np

    image = np.full((240, 240), 255, np.uint8)
    cv2.circle(image, (120, 120), 60, 0, 3)
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    gradient_x = cv2.Sobel(image, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(image, cv2.CV_32F, 0, 1, ksize=3)

    mean_alignment, aligned_fraction = _radial_gradient_alignment(
        edges,
        gradient_x,
        gradient_y,
        120,
        120,
        62,
    )

    assert mean_alignment >= 0.82
    assert aligned_fraction >= 0.65


def test_radial_gradient_alignment_rejects_dense_parallel_edge_clutter():
    import cv2
    import numpy as np

    image = np.full((240, 240), 255, np.uint8)
    for y in range(20, 221, 4):
        cv2.line(image, (20, y), (220, y), 0, 1)
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    gradient_x = cv2.Sobel(image, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(image, cv2.CV_32F, 0, 1, ksize=3)

    mean_alignment, aligned_fraction = _radial_gradient_alignment(
        edges,
        gradient_x,
        gradient_y,
        120,
        120,
        60,
    )

    assert mean_alignment < 0.82
    assert aligned_fraction < 0.65


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
    pattern = raw["regions"][0]["linear_pattern_candidates"][0]
    assert pattern["kind"] == "dashed_or_centerline_candidate"
    assert pattern["segments_px"] == [
        [120, 140],
        [155, 175],
        [190, 210],
        [225, 245],
    ]


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
    assert raw["summary"]["orthogonal_line_candidate_count"] >= 1
    assert raw["orthogonal_line_candidates"]
    assert all(
        item["candidate_only"] is True
        for item in raw["orthogonal_line_candidates"]
    )
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


def test_axis_ink_continuity_separates_continuous_edge_from_sparse_hatch():
    import cv2
    import numpy as np

    image = np.full((220, 220), 255, np.uint8)
    cv2.line(image, (40, 20), (40, 200), 0, 3)
    for offset in range(30, 190, 20):
        cv2.line(image, (115, offset), (135, offset + 20), 0, 2)

    continuous_fraction, continuous_run = _axis_ink_continuity(
        image, "vertical", 40.0, 20, 200
    )
    _hatch_fraction, hatch_run = _axis_ink_continuity(
        image, "vertical", 125.0, 20, 200
    )

    assert continuous_fraction > 0.90
    assert continuous_run > 0.90
    assert hatch_run < 0.25


def test_region_scoped_witnesses_excludes_other_region_axes():
    assert _region_scoped_witnesses(
        [146.0, 295.5, 371.5, 414.0],
        orientation="vertical",
        region_bbox=[432, 88, 592, 211],
        margin=5.0,
    ) == [146.0, 295.5]


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


def test_curved_annotation_candidates_classify_exterior_curve_without_metric_geometry():
    import cv2
    import numpy as np

    image = np.full((280, 320), 255, np.uint8)
    points = [
        [40, 240],
        [40, 60],
        [140, 60],
    ]
    for angle in np.linspace(-90.0, 0.0, 40):
        radians = np.deg2rad(angle)
        points.append(
            [
                int(round(140 + 60 * np.cos(radians))),
                int(round(120 + 60 * np.sin(radians))),
            ]
        )
    points.append([200, 240])
    polygon = np.asarray(points, dtype=np.int32)
    cv2.fillPoly(image, [polygon], 150)
    cv2.polylines(image, [polygon], True, 0, 3)

    candidates = _curved_annotation_candidates(
        image,
        cv2,
        np,
    )

    assert candidates
    assert all(
        item["kind"] == "curved_boundary_candidate"
        for item in candidates
    )
    assert all(item["candidate_only"] is True for item in candidates)
    assert all(
        item["exterior_boundary_candidate"] is True
        for item in candidates
    )
    assert all(
        item["curve_classification_basis"]
        == "stable_cocircular_exterior_contour_turning"
        for item in candidates
    )
    assert any(
        float(item["curve_fit_residual_fraction"]) <= 0.025
        and float(item["turn_consistency_fraction"]) >= 0.90
        and float(item["turn_magnitude_cv"]) <= 0.25
        and 20.0 <= float(item["sweep_deg_px"]) <= 200.0
        for item in candidates
    )
    assert all(
        isinstance(item.get("curve_trace_px"), list)
        and len(item["curve_trace_px"]) >= 5
        for item in candidates
    )
    assert all(
        all(
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(value, (int, float)) for value in point)
            for point in item["curve_trace_px"]
        )
        for item in candidates
    )
    assert all("center_px" not in item for item in candidates)
    assert all("radius_px" not in item for item in candidates)


def test_curved_annotation_candidates_reject_straight_polygon_edges():
    import cv2
    import numpy as np

    image = np.full((240, 300), 255, np.uint8)
    polygon = np.asarray(
        [[40, 200], [40, 40], [240, 40], [240, 200]],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [polygon], 150)
    cv2.polylines(image, [polygon], True, 0, 3)

    candidates = _curved_annotation_candidates(
        image,
        cv2,
        np,
    )

    assert candidates == []


def test_oblique_annotation_lines_stay_geometry_only():
    import cv2
    import numpy as np

    image = np.full((300, 500), 255, np.uint8)
    cv2.line(image, (40, 250), (180, 110), 0, 2)
    cv2.line(image, (220, 200), (440, 200), 0, 2)
    edges = cv2.Canny(image, 50, 150, apertureSize=3)

    candidates = _oblique_annotation_lines(
        edges,
        image_width=500,
        image_height=300,
        cv2=cv2,
        np=np,
    )

    assert candidates
    assert all(item["kind"] == "oblique_line_candidate" for item in candidates)
    assert all(item["candidate_only"] is True for item in candidates)
    assert all(8 < item["angle_deg"] < 82 for item in candidates)
    assert all(
        0.0 <= float(item["line_edge_support_fraction"]) <= 1.0
        for item in candidates
    )
    assert max(
        float(item["line_edge_support_fraction"])
        for item in candidates
    ) >= 0.85


def test_one_sided_boundary_evidence_rejects_interior_line():
    import cv2
    import numpy as np

    image = np.full((220, 220), 255, np.uint8)
    polygon = np.array(
        [[20, 190], [20, 110], [100, 30], [190, 30], [190, 190]],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [polygon], 128)

    boundary = _one_sided_boundary_evidence(
        image,
        (20, 110),
        (100, 30),
    )
    interior = _one_sided_boundary_evidence(
        image,
        (70, 150),
        (150, 150),
    )

    assert boundary["one_sided_boundary_candidate"] is True
    assert boundary["background_side_index"] in {0, 1}
    assert boundary["material_side_index"] in {0, 1}
    assert boundary["background_side_index"] != boundary["material_side_index"]
    assert (
        boundary["side_background_fraction"][boundary["background_side_index"]]
        > boundary["side_background_fraction"][boundary["material_side_index"]]
    )
    assert max(boundary["side_background_fraction"]) >= 0.70
    assert min(boundary["side_background_fraction"]) <= 0.25
    assert max(boundary["near_side_background_fraction"]) >= 0.60
    assert interior["one_sided_boundary_candidate"] is False


def test_one_sided_boundary_evidence_rejects_nearby_interior_line():
    import cv2
    import numpy as np

    image = np.full((220, 220), 255, np.uint8)
    polygon = np.array(
        [[20, 190], [20, 30], [100, 30], [180, 110], [180, 190]],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [polygon], 128)

    # This line sits just inside the true sloped outline. A far sample can
    # already reach white background, but the immediate neighborhood remains
    # filled on both sides and must therefore fail closed as an interior line.
    interior_near_boundary = _one_sided_boundary_evidence(
        image,
        (103, 36),
        (173, 106),
    )

    assert max(interior_near_boundary["side_background_fraction"]) >= 0.70
    assert max(interior_near_boundary["near_side_background_fraction"]) < 0.60
    assert interior_near_boundary["one_sided_boundary_candidate"] is False


def test_oblique_exterior_mask_separates_silhouette_from_nearby_internal_hatch():
    import cv2
    import numpy as np

    image = np.full((260, 320), 255, np.uint8)
    polygon = np.array(
        [[40, 220], [40, 50], [170, 50], [250, 220]],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [polygon], 150)
    cv2.polylines(image, [polygon], True, 0, 5)

    # A nearby internal line intentionally parallels the real exterior slope.
    cv2.line(image, (172, 72), (231, 198), 70, 3)

    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    candidates = _oblique_annotation_lines(
        edges,
        image_width=image.shape[1],
        image_height=image.shape[0],
        cv2=cv2,
        np=np,
        gray=image,
    )

    exterior = [
        item
        for item in candidates
        if item.get("exterior_boundary_candidate") is True
        and 55.0 <= float(item["angle_deg"]) <= 75.0
    ]
    assert exterior
    assert any(
        item.get("one_sided_boundary_candidate") is True
        for item in exterior
    )

    internal = [
        item
        for item in candidates
        if item.get("exterior_boundary_candidate") is not True
        and 55.0 <= float(item["angle_deg"]) <= 75.0
    ]
    assert internal


def test_compact_fragments_does_not_silently_drop_ninth_valid_pattern():
    groups = [
        {
            "orientation": "vertical",
            "axis_px": 20.0 + index * 12.0,
            "segments": [
                [100, 112],
                [120, 132],
                [140, 152],
            ],
            "positive_gaps_px": [8, 8],
            "kind": "dashed_or_centerline_candidate",
        }
        for index in range(10)
    ]

    items = _compact_fragments(
        groups,
        image_width=1000,
        image_height=800,
        region={
            "x": 0,
            "y": 0,
            "width": 400,
            "height": 500,
        },
    )

    assert len(items) == 10



def test_short_dimension_rail_requires_two_crossing_witness_lines():
    import cv2
    import numpy as np

    from nx_mcp.drawing_intelligence.raster_evidence import (
        _dimension_geometry,
        _short_dimension_has_independent_witnesses,
    )

    assert _short_dimension_has_independent_witnesses(
        "horizontal", 120.0, 300.0, 341.0,
        [279.0, 362.0],
        [
            ("vertical", 279.0, 90, 230),
            ("vertical", 362.0, 90, 230),
        ],
        minimum_witness_length=20,
        witness_axis_tolerance=5.0,
        axis_cross_tolerance=5.0,
        region_bbox=[220, 90, 250, 300],
    )
    assert not _short_dimension_has_independent_witnesses(
        "horizontal", 120.0, 300.0, 341.0,
        [279.0, 362.0],
        [("vertical", 279.0, 90, 230)],
        minimum_witness_length=20,
        witness_axis_tolerance=5.0,
        axis_cross_tolerance=5.0,
        region_bbox=[220, 90, 250, 300],
    )

    class FixedHough:
        Canny = staticmethod(cv2.Canny)
        HoughLinesP = staticmethod(lambda *args, **kwargs: np.array(
            [
                [[300, 120, 341, 120]],
                [[279, 90, 279, 230]],
                [[362, 90, 362, 230]],
            ],
            dtype=np.int32,
        ))

    image = np.full((400, 1034), 255, dtype=np.uint8)
    raw = {"regions": [{"region_id": "R", "bbox_px": [220, 90, 250, 300]}]}
    candidates = _dimension_geometry(image, raw, FixedHough, np)
    short = [
        item for item in candidates
        if item["region_id"] == "R"
        and item["orientation"] == "horizontal"
        and item["line_span_px"] == [300, 341]
    ]
    assert len(short) == 1
    assert short[0]["short_witness_proven"] is True
    assert short[0]["status"] == "candidate_only_no_semantics"
    assert len(short[0]["witness_positions_px"]) == 2

    class NoSecondWitness(FixedHough):
        HoughLinesP = staticmethod(lambda *args, **kwargs: np.array(
            [
                [[300, 120, 341, 120]],
                [[279, 90, 279, 230]],
            ],
            dtype=np.int32,
        ))
    assert _dimension_geometry(image, raw, NoSecondWitness, np) == []
