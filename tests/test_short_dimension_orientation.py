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
