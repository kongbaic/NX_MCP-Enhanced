from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.reader_semantic_queries import (
    ReaderSemanticQueryError,
    build_reader_semantic_queries,
)


def _reader_input() -> dict:
    return {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/workspace/reader-crops/R1.png",
            },
            {
                "region_id": "R2",
                "crop_path": "C:/workspace/reader-crops/R2.png",
            },
        ],
        "candidate_buckets": [
            {
                "bucket_id": "R1.horizontal.bottom",
                "region_id": "R1",
                "orientation": "horizontal",
                "band": "bottom",
                "status": "bounded",
                "candidate_count": 2,
                "candidates": [
                    {
                        "candidate_id": "DG9",
                        "orientation": "horizontal",
                        "anchor_hints": [],
                    },
                    {
                        "candidate_id": "DG12",
                        "orientation": "horizontal",
                        "anchor_hints": [],
                    },
                ],
            },
            {
                "bucket_id": "R2.vertical.right",
                "region_id": "R2",
                "orientation": "vertical",
                "band": "right",
                "status": "overflow",
                "candidate_count": 5,
                "candidates": [],
            },
        ],
    }


def test_builds_one_bounded_query_per_region():
    plan = build_reader_semantic_queries(_reader_input())

    assert plan.schema_version == "reader-semantic-queries-v1"
    assert [item.query_id for item in plan.queries] == ["Q001", "Q002"]
    assert [item.region_id for item in plan.queries] == ["R1", "R2"]
    assert plan.queries[0].image_path.endswith("R1.png")
    assert plan.queries[0].allowed_evidence_labels == [
        "R1",
        "R1.horizontal.bottom",
    ]
    assert plan.queries[1].allowed_evidence_labels == [
        "R2",
        "R2.vertical.right",
    ]


def test_query_plan_does_not_enable_cross_view_semantics():
    plan = build_reader_semantic_queries(_reader_input())

    assert plan.rules["read_only_query_image"] is True
    assert plan.rules["open_unlisted_images"] is False
    assert plan.rules["scan_workspace"] is False
    assert plan.rules["cross_view_identity"] is False
    assert plan.rules["global_feature_merge"] is False
    assert plan.rules["reader_capture_output"] is False
    assert plan.rules["second_interpretation"] is False
    assert plan.rules["programmatic_image_analysis"] is False
    assert plan.rules["pixel_measurement"] is False
    assert plan.rules["image_transform"] is False
    assert plan.rules["ascii_render"] is False


def test_overflow_bucket_exposes_no_candidates():
    plan = build_reader_semantic_queries(_reader_input())

    bucket = plan.queries[1].candidate_buckets[0]
    assert bucket.status == "overflow"
    assert bucket.candidate_count == 5
    assert bucket.candidates == []


def test_region_query_count_is_bounded():
    payload = _reader_input()
    payload["regions"] = [
        {
            "region_id": f"R{index}",
            "crop_path": f"C:/workspace/reader-crops/R{index}.png",
        }
        for index in range(1, 6)
    ]

    with pytest.raises(ReaderSemanticQueryError, match="exceeds bounded maximum"):
        build_reader_semantic_queries(payload)


ROOT = Path(__file__).resolve().parents[1]


def test_build_reader_semantic_queries_cli_e2e(tmp_path: Path):
    reader_input = tmp_path / "reader-input.json"
    output = tmp_path / "reader-semantic-queries.json"
    reader_input.write_text(
        json.dumps(_reader_input(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "build-reader-semantic-queries",
            str(reader_input),
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["written"] is True
    assert report["schema"] == "reader-semantic-queries-v1"
    assert report["query_count"] == 2
    assert output.is_file()
