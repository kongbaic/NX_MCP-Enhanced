from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.reader_candidate_queries import (
    build_reader_candidate_queries,
)
from nx_mcp.drawing_intelligence.reader_candidate_values import (
    CandidateValueRegionAnswer,
    ReaderCandidateValueError,
    assemble_candidate_value_regions,
)


def _reader_input(tmp_path: Path | None = None) -> dict:
    visual_path = (
        str(tmp_path / "reader-visual-aid.json")
        if tmp_path is not None
        else "C:/workspace/reader-visual-aid.json"
    )
    return {
        "schema": "reader-input-v1",
        "reader_visual_aid_path": visual_path,
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/workspace/reader-crops/R1.png",
                "candidate_overlay_path": "C:/workspace/reader-crops/R1-candidates.png",
            },
            {
                "region_id": "R2",
                "crop_path": "C:/workspace/reader-crops/R2.png",
                "candidate_overlay_path": "C:/workspace/reader-crops/R2-candidates.png",
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
                        "candidate_id": "DG7",
                        "orientation": "horizontal",
                        "anchor_hints": [],
                    },
                    {
                        "candidate_id": "DG8",
                        "orientation": "horizontal",
                        "anchor_hints": [],
                    },
                ],
            }
        ],
    }


def _visual_aid() -> dict:
    return {
        "schema": "reader-visual-aid-v1",
        "regions": [
            {
                "region_id": "R1",
                "circle_groups": [
                    {
                        "circle_group_id": "C2",
                        "rings": [{"radius_px": 10}],
                    }
                ],
            },
            {
                "region_id": "R2",
                "circle_groups": [],
            },
        ],
    }


def _answers() -> list[CandidateValueRegionAnswer]:
    return [
        CandidateValueRegionAnswer.model_validate(
            {
                "schema": "reader-candidate-value-region-v1",
                "query_id": "Q001",
                "view_kind": "front",
                "targets": [
                    {"target_id": "DG7", "value": 23},
                    {"target_id": "DG8", "value": None},
                ],
            }
        ),
        CandidateValueRegionAnswer.model_validate(
            {
                "schema": "reader-candidate-value-region-v1",
                "query_id": "Q002",
                "view_kind": "side",
                "targets": [],
            }
        ),
    ]


def test_value_only_answers_assemble_without_endpoint_claims():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())
    partial = assemble_candidate_value_regions(plan, _answers())

    assert [item.key for item in partial.dimensions] == ["R1.DG7"]
    dimension = partial.dimensions[0]
    assert dimension.value == 23
    assert dimension.axis == "X"
    assert [item.role for item in dimension.endpoints] == [
        "unresolved",
        "unresolved",
    ]
    assert all(
        item.unresolved_kind == "intermediate_surface"
        for item in dimension.endpoints
    )
    assert any(
        item.field == "dimension_value_candidate"
        for item in partial.unresolved
    )


def test_value_only_answers_require_exact_target_set():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())
    answers = _answers()
    answers[0] = CandidateValueRegionAnswer.model_validate(
        {
            "schema": "reader-candidate-value-region-v1",
            "query_id": "Q001",
            "view_kind": "front",
            "targets": [{"target_id": "DG7", "value": 23}],
        }
    )

    with pytest.raises(ReaderCandidateValueError, match="target mismatch"):
        assemble_candidate_value_regions(plan, answers)


def test_value_only_answer_schema_forbids_endpoint_fields():
    with pytest.raises(ValidationError):
        CandidateValueRegionAnswer.model_validate(
            {
                "schema": "reader-candidate-value-region-v1",
                "query_id": "Q001",
                "view_kind": "front",
                "targets": [
                    {
                        "target_id": "DG7",
                        "value": 23,
                        "endpoint_a": "intermediate_surface",
                    }
                ],
            }
        )


ROOT = Path(__file__).resolve().parents[1]


def test_value_only_contract_has_no_endpoint_decision_task():
    contract = (
        ROOT / "skills" / "nx-agent" / "references" / "reader-candidate-value-contract.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(contract.split())

    assert "Do not emit endpoint fields" in normalized
    assert "Do not emit dimension/not_dimension/uncertain" in normalized
    assert "candidate-overlay `image_path`" in contract
    for forbidden in ("SHKSS", "main_bore", "center_height", "40±0.02"):
        assert forbidden not in contract


def test_value_only_cli_e2e(tmp_path: Path):
    reader_input_path = tmp_path / "reader-input.json"
    visual_aid_path = tmp_path / "reader-visual-aid.json"
    query_path = tmp_path / "reader-candidate-queries.json"
    partial_path = tmp_path / "reader-candidate-value-partial-observations.json"

    reader_input_path.write_text(
        json.dumps(_reader_input(tmp_path), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    visual_aid_path.write_text(
        json.dumps(_visual_aid(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "build-reader-candidate-queries",
            str(reader_input_path),
            str(query_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    for answer in _answers():
        path = tmp_path / f"reader-candidate-value-{answer.query_id}.json"
        path.write_text(
            json.dumps(
                answer.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    assemble = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "assemble-reader-candidate-values",
            str(query_path),
            str(tmp_path),
            str(partial_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert assemble.returncode == 0, assemble.stdout + assemble.stderr
    report = json.loads(assemble.stdout)
    assert report["written"] is True
    assert report["dimension_count"] == 1
    assert partial_path.is_file()
