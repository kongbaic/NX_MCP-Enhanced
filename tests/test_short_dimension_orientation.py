from __future__ import annotations

import cv2
import numpy as np

from nx_mcp.drawing_intelligence.short_dimension_orientation import (
    infer_labeled_dimension_axis_span,
)


def test_labeled_dimension_axis_span_prefers_unique_near_label_edge(tmp_path):
    image = np.full((420, 420), 255, dtype=np.uint8)
    cv2.line(image, (80, 60), (80, 360), 0, 2)
    cv2.line(image, (160, 220), (160, 360), 0, 2)
    path = tmp_path / "dimension.png"
    assert cv2.imwrite(str(path), image)

    span = infer_labeled_dimension_axis_span(
        str(path),
        [[166, 250], [260, 250], [260, 280], [166, 280]],
        expected_direction="vertical",
    )

    assert span is not None
    assert abs(span[0] - 220.0) <= 3.0
    assert abs(span[1] - 360.0) <= 3.0


def test_labeled_dimension_axis_span_rejects_equally_near_competitors(tmp_path):
    image = np.full((420, 420), 255, dtype=np.uint8)
    cv2.line(image, (150, 180), (150, 360), 0, 2)
    cv2.line(image, (170, 180), (170, 360), 0, 2)
    path = tmp_path / "ambiguous.png"
    assert cv2.imwrite(str(path), image)

    span = infer_labeled_dimension_axis_span(
        str(path),
        [[155, 250], [165, 250], [165, 280], [155, 280]],
        expected_direction="vertical",
    )

    assert span is None

def test_labeled_dimension_axis_span_snaps_to_unique_terminal_witnesses(tmp_path):
    image = np.full((420, 420), 255, dtype=np.uint8)
    cv2.line(image, (150, 100), (150, 300), 0, 2)
    cv2.line(image, (90, 88), (155, 88), 0, 2)
    cv2.line(image, (90, 302), (155, 302), 0, 2)
    path = tmp_path / "dimension-terminals.png"
    assert cv2.imwrite(str(path), image)

    span = infer_labeled_dimension_axis_span(
        str(path),
        [[170, 185], [260, 185], [260, 215], [170, 215]],
        expected_direction="vertical",
    )

    assert span is not None
    assert abs(span[0] - 88.0) <= 3.0
    assert abs(span[1] - 302.0) <= 3.0


def test_labeled_dimension_axis_span_keeps_axis_endpoint_when_terminal_is_ambiguous(
    tmp_path,
):
    image = np.full((420, 420), 255, dtype=np.uint8)
    cv2.line(image, (150, 100), (150, 300), 0, 2)
    cv2.line(image, (90, 82), (155, 82), 0, 2)
    cv2.line(image, (90, 118), (155, 118), 0, 2)
    path = tmp_path / "dimension-ambiguous-terminal.png"
    assert cv2.imwrite(str(path), image)

    span = infer_labeled_dimension_axis_span(
        str(path),
        [[170, 185], [260, 185], [260, 215], [170, 215]],
        expected_direction="vertical",
    )

    assert span is not None
    assert 97.0 <= span[0] <= 103.0




def test_short_dimension_pair_accepts_witness_lines_one_glyph_height_outside_label(tmp_path):
    import cv2
    import numpy as np
    from nx_mcp.drawing_intelligence.short_dimension_orientation import (
        infer_short_dimension_visual_topology,
    )

    image = np.full((420, 500), 255, np.uint8)
    cv2.line(image, (85, 200), (440, 200), 0, 2)
    cv2.line(image, (85, 270), (440, 270), 0, 2)
    cv2.line(image, (104, 200), (104, 270), 0, 2)
    path = tmp_path / "offset.png"
    assert cv2.imwrite(str(path), image)
    bbox = [[64, 228], [95, 228], [95, 247], [64, 247]]
    topology = infer_short_dimension_visual_topology(str(path), bbox)
    assert topology is not None
    assert topology[0] == "vertical"
    assert any(
        abs(first - 200) < 4 and abs(second - 270) < 4
        for first, second in topology[1]
    )

    # One exposed horizontal witness does not establish a dimension span.
    cv2.line(image, (85, 270), (440, 270), 255, 5)
    assert cv2.imwrite(str(path), image)
    assert infer_short_dimension_visual_topology(str(path), bbox) is None
