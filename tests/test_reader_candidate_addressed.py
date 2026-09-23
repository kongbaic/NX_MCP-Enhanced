from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.reader_candidate_answers import (
    CandidateRegionAnswer,
    ReaderCandidateAnswerError,
    assemble_candidate_regions,
)
from nx_mcp.drawing_intelligence.reader_candidate_queries import (
    build_reader_candidate_queries,
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
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_id": "DG7",
                        "orientation": "horizontal",
                        "anchor_hints": [
                            {
                                "witness_index": 0,
                                "nearby_anchors": [
                                    {
                                        "kind": "region_bbox_edge",
                                        "ref": "R1.bbox.left",
                                    }
                                ],
                            },
                            {
                                "witness_index": 1,
                                "nearby_anchors": [
                                    {
                                        "kind": "circle_center_axis",
                                        "ref": "R1.C2.center_x",
                                    }
                                ],
                            },
                        ],
                    }
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
                "reason": "bounded filter still leaves five candidates",
            },
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


def _answers() -> list[CandidateRegionAnswer]:
    return [
        CandidateRegionAnswer.model_validate(
            {
                "schema": "reader-candidate-region-v1",
                "query_id": "Q001",
                "view_kind": "front",
                "targets": [
                    {
                        "target_id": "DG7",
                        "classification": "dimension",
                        "value": 23,
                        "endpoint_a": "bbox:R1.bbox.left",
                        "endpoint_b": "circle:R1.C2.center_x:centerline",
                    }
                ],
            }
        ),
        CandidateRegionAnswer.model_validate(
            {
                "schema": "reader-candidate-region-v1",
                "query_id": "Q002",
                "view_kind": "side",
                "targets": [],
            }
        ),
    ]


def test_candidate_queries_address_only_existing_dimension_candidates():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())

    assert [item.query_id for item in plan.queries] == ["Q001", "Q002"]
    assert [item.target_id for item in plan.queries[0].dimension_targets] == ["DG7"]
    assert plan.queries[0].circle_entities[0].entity_key == "C2"
    assert plan.queries[1].dimension_targets == []
    assert len(plan.queries[1].overflow_buckets) == 1
    assert plan.rules["scan_region_for_unaddressed_facts"] is False
    assert plan.rules["answer_only_listed_dimension_targets"] is True


def test_candidate_answers_assemble_into_existing_partial_observations():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())
    partial = assemble_candidate_regions(plan, _answers())

    assert [item.key for item in partial.views] == ["view.R1", "view.R2"]
    assert [item.key for item in partial.entities] == ["R1.C2"]
    assert [item.key for item in partial.dimensions] == ["R1.DG7"]
    assert partial.dimensions[0].axis == "X"
    assert partial.dimensions[0].endpoints[0].role == "overall_min"
    assert partial.dimensions[0].endpoints[1].entity_key == "R1.C2"
    assert any(item.field == "dimension_candidate_bucket" for item in partial.unresolved)


def test_candidate_answer_requires_exact_target_set():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())
    answers = _answers()
    answers[0] = CandidateRegionAnswer.model_validate(
        {
            "schema": "reader-candidate-region-v1",
            "query_id": "Q001",
            "view_kind": "front",
            "targets": [],
        }
    )

    with pytest.raises(ReaderCandidateAnswerError, match="target mismatch"):
        assemble_candidate_regions(plan, answers)


def test_candidate_answer_rejects_unlisted_anchor_ref():
    plan = build_reader_candidate_queries(_reader_input(), _visual_aid())
    answers = _answers()
    answers[0] = CandidateRegionAnswer.model_validate(
        {
            "schema": "reader-candidate-region-v1",
            "query_id": "Q001",
            "view_kind": "front",
            "targets": [
                {
                    "target_id": "DG7",
                    "classification": "dimension",
                    "value": 23,
                    "endpoint_a": "bbox:R1.bbox.right",
                    "endpoint_b": "circle:R1.C2.center_x:centerline",
                }
            ],
        }
    )

    with pytest.raises(ReaderCandidateAnswerError, match="unavailable bbox anchor"):
        assemble_candidate_regions(plan, answers)


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_contract_forbids_unaddressed_inventory():
    contract = (
        ROOT / "skills" / "nx-agent" / "references" / "reader-candidate-addressed-contract.md"
    ).read_text(encoding="utf-8")

    assert "Do not search the region for additional" in contract
    assert "every listed `dimension_target` exactly once" in contract
    for forbidden in ("SHKSS", "main_bore", "center_height", "40±0.02"):
        assert forbidden not in contract


def test_candidate_cli_build_and_assemble_e2e(tmp_path: Path):
    reader_input_path = tmp_path / "reader-input.json"
    visual_aid_path = tmp_path / "reader-visual-aid.json"
    query_path = tmp_path / "reader-candidate-queries.json"
    partial_path = tmp_path / "reader-candidate-partial-observations.json"

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
        (tmp_path / f"reader-candidate-{answer.query_id}.json").write_text(
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
            "assemble-reader-candidate-regions",
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
    assert report["schema"] == "reader-partial-observations-v1"
    assert report["dimension_count"] == 1
    assert partial_path.is_file()
