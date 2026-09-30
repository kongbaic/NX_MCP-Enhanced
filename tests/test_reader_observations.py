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
                    "unique_orthographic_counterpart",
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


def test_overlapping_observation_associations_are_rejected_before_assembly():
    payload = _base_observations()
    payload["associations"].append(
        {
            "entity_keys": ["front_bore", "side_bore"],
            "basis": ["projection_alignment", "unique_orthographic_counterpart"],
            "evidence": ["overview-duplicate"],
        }
    )

    with pytest.raises(ValidationError, match="appears in multiple observation associations"):
        ReaderObservations.model_validate(payload)


def test_observation_association_cannot_contain_two_entities_from_same_view():
    payload = _base_observations()
    payload["entities"].append(
        {
            "key": "front_bore_2",
            "view_key": "front",
            "shape": "circle",
            "cross_view_disposition": "associated",
            "evidence": ["R1.other"],
        }
    )
    payload["associations"] = [
        {
            "entity_keys": ["front_bore", "front_bore_2"],
            "basis": ["projection_alignment", "unique_orthographic_counterpart"],
            "evidence": ["overview"],
        }
    ]

    with pytest.raises(ValidationError, match="multiple entities from the same view"):
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


def test_pattern_symmetry_maps_entity_key_to_capture_entity_id():
    payload = _base_observations()
    payload["pattern_symmetries"] = [
        {
            "entity_key": "front_bore",
            "axis": "X",
            "evidence": ["R1.symmetric-pair"],
        }
    ]

    observations = ReaderObservations.model_validate(payload)
    capture = assemble_reader_capture(observations)

    symmetry = next(
        item
        for item in capture.observations
        if item.get("kind") == "symmetric_count_two_overall_center"
    )
    assert symmetry["entity_id"] == "E001"
    assert symmetry["axis"] == "X"
    assert symmetry["datum"] == "overall_center"
    assert symmetry["source_ids"] == ["R1.symmetric-pair"]


def test_centerline_alignment_survives_capture_assembly():
    payload = _base_observations()
    payload["centerline_alignments"] = [
        {
            "entity_keys": ["front_bore", "side_bore"],
            "feature_axis": "Y",
            "evidence": ["coaxial:evidence"],
        }
    ]

    observations = ReaderObservations.model_validate(payload)
    capture = assemble_reader_capture(observations)

    assert len(capture.centerline_alignments) == 1
    alignment = capture.centerline_alignments[0]
    assert alignment.entity_ids == ["E001", "E002"]
    assert alignment.feature_axis == "Y"
    assert alignment.source_ids == ["coaxial:evidence"]



def test_span_center_ledgers_map_dimension_keys_to_capture_ids():
    payload = _base_observations()
    payload["dimensions"].append(
        {
            "key": "profile_span",
            "value": 20,
            "axis": "X",
            "endpoints": [
                {
                    "role": "overall_min",
                    "evidence": ["span:left"],
                },
                {
                    "role": "overall_max",
                    "evidence": ["span:right"],
                },
            ],
            "evidence": ["span"],
        }
    )
    payload["observations"] = [
        {
            "kind": "hybrid_projected_profile_level_ledger",
            "schema": "1.0",
            "items": [
                {
                    "dimension_key": "center_height",
                    "endpoint_index": 0,
                    "axis": "Z",
                }
            ],
        },
        {
            "kind": "hybrid_symmetric_dimension_pair_ledger",
            "schema": "1.0",
            "items": [
                {
                    "dimension_key": "center_height",
                    "axis": "X",
                }
            ],
        },
        {
            "kind": "hybrid_profile_span_center_ledger",
            "schema": "1.0",
            "items": [
                {
                    "dimension_key": "profile_span",
                    "profile_entity_keys": ["front_bore", "side_bore"],
                }
            ],
        },
        {
            "kind": "hybrid_dimension_span_center_identity_ledger",
            "schema": "1.0",
            "items": [
                {
                    "dimension_key": "center_height",
                    "span_dimension_key": "profile_span",
                    "endpoint_index": 0,
                }
            ],
        },
    ]

    observations = ReaderObservations.model_validate(payload)
    capture = assemble_reader_capture(observations)

    projected_level_ledger = next(
        item
        for item in capture.observations
        if item.get("kind") == "hybrid_projected_profile_level_ledger"
    )
    assert projected_level_ledger["items"][0]["dimension_id"] == "D001"

    symmetric_pair_ledger = next(
        item
        for item in capture.observations
        if item.get("kind") == "hybrid_symmetric_dimension_pair_ledger"
    )
    assert symmetric_pair_ledger["items"][0]["dimension_id"] == "D001"

    span_ledger = next(
        item
        for item in capture.observations
        if item.get("kind") == "hybrid_profile_span_center_ledger"
    )
    span_item = span_ledger["items"][0]
    assert span_item["dimension_id"] == "D002"
    assert span_item["profile_entity_ids"] == ["E001", "E002"]

    identity_ledger = next(
        item
        for item in capture.observations
        if item.get("kind") == "hybrid_dimension_span_center_identity_ledger"
    )
    identity_item = identity_ledger["items"][0]
    assert identity_item["dimension_id"] == "D001"
    assert identity_item["span_dimension_id"] == "D002"
