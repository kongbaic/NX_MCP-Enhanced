from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "line_evidence.py"
SPEC = importlib.util.spec_from_file_location("line_evidence_prototype", MODULE_PATH)
assert SPEC and SPEC.loader
LE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LE)


def blank(width: int = 320, height: int = 220) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.uint8)


def save(path: Path, image: np.ndarray, jpeg_quality: int | None = None) -> None:
    suffix = path.suffix.lower()
    params: list[int] = []
    if suffix in {".jpg", ".jpeg"} and jpeg_quality is not None:
        params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    success, data = cv2.imencode(suffix, image, params)
    assert success
    path.write_bytes(data.tobytes())


def horizontal_by_nearest_y(evidence: dict, y: int) -> dict:
    lines = [item for item in evidence["lines"] if item["orientation"] == "horizontal"]
    return min(lines, key=lambda item: abs(item["segment_px"][1] - y))


def compact_fixture() -> dict:
    def line(line_id: str, confidence: float) -> dict:
        return {
            "id": line_id,
            "orientation": "horizontal",
            "segment_px": [10, 20, 90, 20],
            "fragments_px": [[10, 20, 40, 20], [50, 20, 90, 20]],
            "occupancy": 0.75,
            "run_stats": {
                "black_run_count": 2,
                "black_run_lengths_px": [31, 41],
                "internal_gap_count": 1,
                "internal_gap_lengths_px": [9],
            },
            "style": "solid",
            "style_scores": {"solid": confidence, "dashed": 0.1, "dash_dot": 0.0},
            "confidence": confidence,
        }

    return {
        "image": {"width_px": 160, "height_px": 120},
        "lines": [
            line("L0001", 0.95),
            line("L0002", 0.90),
            line("L0003", 0.59),
            line("L0004", 0.88),
            line("L0005", 0.91),
        ],
        "arrowheads": [
            {
                "id": "A0001",
                "tip_px": [20, 20],
                "direction_px": [1.0, 0.0],
                "bbox_px": [15, 15, 10, 10],
                "confidence": 0.8,
            },
            {
                "id": "A0002",
                "tip_px": [80, 20],
                "direction_px": [-1.0, 0.0],
                "bbox_px": [75, 15, 10, 10],
                "confidence": 0.7,
            },
        ],
        "dimension_line_candidates": [
            {
                "id": "D0001",
                "line_ref": "L0001",
                "arrow_refs": ["A0002", "A0001"],
                "confidence": 0.75,
            }
        ],
        "endpoint_candidates": [
            {
                "arrow_ref": "A0001",
                "status": "ambiguous",
                "line_candidates": [
                    {
                        "line_ref": "L0004",
                        "distance_px": 1.5,
                        "intersection_px": [20.0, 21.5],
                        "orientation_compatible": True,
                        "confidence": 0.8,
                    },
                    {
                        "line_ref": "L0001",
                        "distance_px": 1.7,
                        "intersection_px": [20.0, 21.7],
                        "orientation_compatible": False,
                        "confidence": 0.6,
                    },
                ],
            },
            {
                "arrow_ref": "A0002",
                "status": "none",
                "line_candidates": [],
            },
        ],
        "ambiguities": [
            {
                "id": "U0001",
                "refs": ["A0001", "L0004", "L0005"],
                "reason": "diagnostic text that must not enter compact evidence",
            }
        ],
    }


class LineEvidenceTests(unittest.TestCase):
    def test_compact_retention_and_field_projection(self) -> None:
        compact = LE.compact_evidence(compact_fixture())
        referenced = compact["lines"]["referenced"]
        uncertain = compact["lines"]["unlinked_uncertain"]
        self.assertEqual(set(referenced), {"L0001", "L0004", "L0005"})
        self.assertEqual(set(uncertain), {"L0003"})
        self.assertNotIn("L0002", referenced)
        self.assertNotIn("L0002", uncertain)
        self.assertEqual(
            referenced["L0001"]["style_candidate"],
            {"label": "solid", "confidence": 0.95},
        )
        encoded = LE.serialize_evidence(compact).decode("utf-8")
        for forbidden in (
            "fragments_px",
            "occupancy",
            "run_stats",
            "black_run",
            "internal_gap",
            "style_scores",
            "bbox_px",
            "intersection_px",
            "diagnostic text",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_compact_preserves_arrows_candidates_and_status(self) -> None:
        compact = LE.compact_evidence(compact_fixture())
        self.assertEqual(compact["dimensions"][0]["arrow_refs"], ["A0001", "A0002"])
        first = compact["arrows"]["A0001"]
        second = compact["arrows"]["A0002"]
        self.assertEqual(first["tip_px"], [20, 20])
        self.assertEqual(first["endpoint_status"], "ambiguous")
        self.assertEqual(first["candidates"][0], {
            "line_ref": "L0004",
            "distance_px": 1.5,
            "orientation_compatible": True,
        })
        self.assertEqual(second["endpoint_status"], "none")
        self.assertEqual(second["candidates"], [])

    def test_compact_serialization_is_byte_equivalent_ten_times(self) -> None:
        fixture = compact_fixture()
        outputs = [
            LE.serialize_evidence(LE.compact_evidence(fixture)) for _ in range(10)
        ]
        self.assertTrue(all(item == outputs[0] for item in outputs))

    def test_solid_horizontal_and_vertical(self) -> None:
        image = blank()
        cv2.line(image, (30, 50), (280, 50), (0, 0, 0), 2)
        cv2.line(image, (80, 30), (80, 190), (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        horizontal = horizontal_by_nearest_y(result, 50)
        vertical = min(
            (item for item in result["lines"] if item["orientation"] == "vertical"),
            key=lambda item: abs(item["segment_px"][0] - 80),
        )
        self.assertEqual(horizontal["style"], "solid")
        self.assertEqual(vertical["style"], "solid")

    def test_dashed_and_dash_dot(self) -> None:
        image = blank(420, 220)
        for x in range(25, 380, 28):
            cv2.line(image, (x, 60), (x + 15, 60), (0, 0, 0), 2)
        cursor = 25
        while cursor < 380:
            cv2.line(image, (cursor, 140), (min(cursor + 20, 380), 140), (0, 0, 0), 2)
            cursor += 29
            cv2.line(image, (cursor, 140), (min(cursor + 3, 380), 140), (0, 0, 0), 2)
            cursor += 12
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        self.assertEqual(horizontal_by_nearest_y(result, 60)["style"], "dashed")
        self.assertEqual(horizontal_by_nearest_y(result, 140)["style"], "dash_dot")

    def test_one_or_two_dashes_are_not_high_confidence(self) -> None:
        image = blank()
        cv2.line(image, (30, 90), (50, 90), (0, 0, 0), 2)
        cv2.line(image, (68, 90), (88, 90), (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        candidate = horizontal_by_nearest_y(result, 90)
        self.assertEqual(candidate["style"], "unknown")
        self.assertLess(candidate["confidence"], 0.55)

    def test_crossing_and_arc_do_not_turn_dashed_into_solid(self) -> None:
        image = blank(420, 220)
        for x in range(20, 390, 30):
            cv2.line(image, (x, 110), (x + 16, 110), (0, 0, 0), 2)
        cv2.line(image, (200, 25), (200, 195), (0, 0, 0), 2)
        cv2.circle(image, (300, 110), 32, (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        candidate = horizontal_by_nearest_y(result, 110)
        self.assertNotEqual(candidate["style"], "solid")

    def test_arrow_and_endpoint_candidate(self) -> None:
        image = blank()
        cv2.line(image, (60, 110), (260, 110), (0, 0, 0), 1)
        cv2.fillConvexPoly(image, np.array([[60, 110], [73, 103], [73, 117]], np.int32), (0, 0, 0))
        cv2.fillConvexPoly(image, np.array([[260, 110], [247, 103], [247, 117]], np.int32), (0, 0, 0))
        cv2.line(image, (60, 70), (60, 150), (0, 0, 0), 2)
        cv2.line(image, (260, 70), (260, 150), (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        self.assertGreaterEqual(len(result["arrowheads"]), 1)
        self.assertTrue(any(item["line_candidates"] for item in result["endpoint_candidates"]))

    def test_two_equidistant_endpoint_lines_are_ambiguous(self) -> None:
        lines = [
            {"id": "L0001", "segment_px": [95, 40, 95, 160]},
            {"id": "L0002", "segment_px": [105, 40, 105, 160]},
        ]
        arrows = [{"id": "A0001", "tip_px": [100, 100], "direction_px": [1.0, 0.0]}]
        endpoints, ambiguities = LE._endpoint_candidates(lines, arrows, [])
        self.assertEqual(endpoints[0]["status"], "ambiguous")
        self.assertEqual(len(ambiguities), 1)

    def test_partly_occluded_arrow_is_not_high_confidence(self) -> None:
        image = blank()
        cv2.fillConvexPoly(image, np.array([[90, 100], [108, 90], [108, 110]], np.int32), (0, 0, 0))
        cv2.rectangle(image, (86, 94), (100, 106), (255, 255, 255), -1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.png"
            save(path, image)
            result = LE.analyze_image(path)
        self.assertFalse(any(item["confidence"] >= 0.85 for item in result["arrowheads"]))

    def test_jpeg_antialias_is_decodable_and_stable(self) -> None:
        image = blank(420, 220)
        cv2.line(image, (20, 60), (390, 60), (0, 0, 0), 1, cv2.LINE_AA)
        for x in range(20, 390, 28):
            cv2.line(image, (x, 145), (x + 14, 145), (0, 0, 0), 1, cv2.LINE_AA)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.jpg"
            save(path, image, jpeg_quality=65)
            first = LE.serialize_evidence(LE.analyze_image(path))
            for _ in range(9):
                self.assertEqual(first, LE.serialize_evidence(LE.analyze_image(path)))

    def test_cli_ten_runs_are_byte_equivalent(self) -> None:
        image = blank()
        cv2.line(image, (20, 50), (290, 50), (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.png"
            save(source, image)
            outputs: list[bytes] = []
            for index in range(10):
                output = root / f"result-{index}.json"
                self.assertEqual(LE.main([str(source), str(output)]), 0)
                outputs.append(output.read_bytes())
        self.assertTrue(all(item == outputs[0] for item in outputs))

    def test_cli_compact_output_does_not_change_full_output(self) -> None:
        image = blank()
        cv2.line(image, (20, 50), (290, 50), (0, 0, 0), 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.png"
            full_without_compact = root / "full-without.json"
            full_with_compact = root / "full-with.json"
            compact = root / "compact.json"
            save(source, image)
            self.assertEqual(
                LE.main([str(source), str(full_without_compact)]), 0
            )
            self.assertEqual(
                LE.main(
                    [
                        str(source),
                        str(full_with_compact),
                        "--compact-output",
                        str(compact),
                    ]
                ),
                0,
            )
            self.assertEqual(
                full_without_compact.read_bytes(), full_with_compact.read_bytes()
            )
            self.assertTrue(compact.exists())
            compact_data = __import__("json").loads(compact.read_text(encoding="utf-8"))
            self.assertEqual(
                set(compact_data), {"image", "lines", "dimensions", "arrows"}
            )

    def test_cli_failure_does_not_create_success_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = LE.main([str(Path(directory) / "missing.png"), str(output)])
            self.assertNotEqual(code, 0)
            self.assertFalse(output.exists())
            self.assertIn("line-evidence failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
