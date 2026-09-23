from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservationAssemblyError,
    ReaderObservations,
    assemble_reader_capture,
)


def _base_observations() -> dict:
    return {
        "schema": "reader-observations-v1",
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "views": [
            {
                "key": "front",
                "kind": "front",
                "evidence": ["overview", "R1"],
            },
            {
                "key": "side",
                "kind": "side",
                "evidence": ["overview", "R2"],
            },
        ],
        "entities": [
            {
                "key": "front_bore",
                "view_key": "front",
                "shape": "circle",
                "cross_view_disposition": "associated",
                "evidence": ["R1"],
            },
            {
                "key": "side_bore",
                "view_key": "side",
                "shape": "hidden_parallel",
                "cross_view_disposition": "associated",
                "evidence": ["R2"],
            },
        ],
        "associations": [
            {
                "entity_keys": ["front_bore", "side_bore"],
                "basis": [
                    "projection_alignment",
                    "matching_specification",
                ],
                "evidence": ["overview"],
            }
        ],
        "values": [
            {
                "entity_key": "front_bore",
                "field": "diameter",
                "value": 20,
                "semantic": "diameter",
                "evidence": ["R1"],
            }
        ],
        "dimensions": [
            {
                "key": "center_height",
                "value": 40,
                "axis": "Z",
                "endpoints": [
                    {
                        "role": "overall_min",
                        "evidence": ["R1.vertical.left"],
                    },
                    {
                        "role": "entity_center",
                        "entity_key": "front_bore",
                        "basis": "centerline",
                        "evidence": ["R1.vertical.right"],
                    },
                ],
                "evidence": ["R1.vertical.right"],
            }
        ],
        "datum_alignments": [],
        "unresolved": [],
    }


def test_compact_observations_assemble_valid_reader_capture():
    observations = ReaderObservations.model_validate(_base_observations())

    capture = assemble_reader_capture(observations)

    assert capture.schema_version == "2.0"
    assert [view.id for view in capture.views] == ["V001", "V002"]
    assert [entity.id for entity in capture.entities] == ["E001", "E002"]
    assert capture.associations[0].entity_ids == ["E001", "E002"]
    assert capture.values[0].entity_id == "E001"
    assert capture.dimensions[0].id == "D001"
    assert capture.dimensions[0].endpoints[1].entity_id == "E001"
    assert capture.required_targets == []


def test_unresolved_endpoint_is_preserved_without_owner_inference():
    payload = _base_observations()
    payload["dimensions"][0] = {
        "key": "ambiguous_horizontal",
        "value": 24,
        "axis": "X",
        "endpoints": [
            {
                "role": "overall_min",
                "evidence": ["R1.horizontal.bottom"],
            },
            {
                "role": "unresolved",
                "candidate_entity_keys": [
                    "front_bore",
                    "side_bore",
                ],
                "unresolved_kind": "ambiguous_owner",
                "evidence": ["R1.horizontal.bottom"],
            },
        ],
        "unresolved_reason": "visible witnesses do not uniquely identify owner",
        "evidence": ["R1.horizontal.bottom"],
    }

    observations = ReaderObservations.model_validate(payload)
    capture = assemble_reader_capture(observations)

    endpoint = capture.dimensions[0].endpoints[1]
    assert endpoint.role == "unresolved"
    assert endpoint.entity_id is None
    assert endpoint.candidate_entity_ids == ["E001", "E002"]
    assert endpoint.unresolved_kind == "ambiguous_owner"


def test_insufficient_association_basis_fails_closed():
    payload = _base_observations()
    payload["associations"][0]["basis"] = ["projection_alignment"]

    observations = ReaderObservations.model_validate(payload)

    with pytest.raises(
        ReaderObservationAssemblyError,
        match="ReaderCapture schema validation failed",
    ):
        assemble_reader_capture(observations)


def test_unknown_entity_reference_rejected_before_assembly():
    payload = _base_observations()
    payload["values"][0]["entity_key"] = "missing"

    with pytest.raises(ValidationError, match="unknown entity key"):
        ReaderObservations.model_validate(payload)


ROOT = Path(__file__).resolve().parents[1]


def test_assemble_reader_capture_cli_e2e(tmp_path: Path):
    observations_path = tmp_path / "reader-observations.json"
    capture_path = tmp_path / "reader-capture.json"
    observations_path.write_text(
        json.dumps(_base_observations(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "assemble-reader-capture",
            str(observations_path),
            str(capture_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["written"] is True
    assert report["schema"] == "reader-observations-v1"
    assert report["capture_schema_version"] == "2.0"
    assert capture_path.is_file()

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    assert capture["schema_version"] == "2.0"
    assert capture["required_targets"] == []
