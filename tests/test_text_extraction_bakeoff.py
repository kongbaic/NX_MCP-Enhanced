from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "text_extraction_bakeoff.py"

spec = importlib.util.spec_from_file_location("text_extraction_bakeoff", MODULE_PATH)
assert spec is not None
assert spec.loader is not None
bakeoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bakeoff)


def test_normalize_token_handles_engineering_glyph_variants():
    assert bakeoff._normalize_token(" Φ20 ") == "Ø20"
    assert bakeoff._normalize_token("φ8") == "Ø8"
    assert bakeoff._normalize_token("∅12") == "Ø12"
    assert bakeoff._normalize_token("40 ± 0.02") == "40±0.02"


def test_bbox_orientation_reports_horizontal_and_vertical():
    horizontal = [[0.0, 0.0], [10.0, 0.0], [10.0, 3.0], [0.0, 3.0]]
    vertical = [[0.0, 0.0], [0.0, 10.0], [3.0, 10.0], [3.0, 0.0]]

    assert bakeoff._bbox_orientation_deg(horizontal) == 0.0
    assert bakeoff._bbox_orientation_deg(vertical) == 90.0


def test_score_reports_exact_token_precision_and_recall():
    items = [
        bakeoff.OcrItem(
            text="Ø20",
            bbox=[[0.0, 0.0], [10.0, 0.0], [10.0, 3.0], [0.0, 3.0]],
            confidence=0.9,
            orientation_deg=0.0,
        ),
        bakeoff.OcrItem(
            text="24",
            bbox=[[0.0, 5.0], [10.0, 5.0], [10.0, 8.0], [0.0, 8.0]],
            confidence=0.8,
            orientation_deg=0.0,
        ),
        bakeoff.OcrItem(
            text="noise",
            bbox=[[0.0, 9.0], [10.0, 9.0], [10.0, 12.0], [0.0, 12.0]],
            confidence=0.7,
            orientation_deg=0.0,
        ),
    ]

    report = bakeoff._score(["Φ20", "24", "R5"], items)

    assert report["matched_count"] == 2
    assert report["exact_token_recall"] == pytest.approx(2 / 3)
    assert report["exact_token_precision"] == pytest.approx(2 / 3)
    assert report["missed"] == ["R5"]
    assert report["extra_text"] == ["noise"]


def test_manifest_requires_supported_schema_and_cases(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "text-extraction-bakeoff-v1",
                "cases": [
                    {
                        "case_id": "drawing-a",
                        "image": "drawing-a.png",
                        "expected_tokens": ["24"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = bakeoff._load_manifest(manifest)

    assert loaded["cases"][0]["case_id"] == "drawing-a"


def test_manifest_rejects_empty_cases(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "text-extraction-bakeoff-v1",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least one case"):
        bakeoff._load_manifest(manifest)
