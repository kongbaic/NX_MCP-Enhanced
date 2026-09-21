from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence import EvidenceGraph, write_strict_evidence


ROOT = Path(__file__).resolve().parents[1]


def _capture(**overrides):
    base = {
        "schema_version": "1.0",
        "coordinate_system": "part_center_xy_bottom_z0",
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "views": [],
        "projections": [],
        "dimensions": [],
        "datum_alignments": [],
        "direct_values": [],
        "relations": [],
        "required_targets": [],
        "observations": [],
        "unresolved_evidence": [],
    }
    base.update(overrides)
    return base


def _valid_dimension():
    return {
        "id": "D_MAIN_Z40",
        "value": 40,
        "axis": "Z",
        "endpoints": [
            {"role": "overall_min"},
            {
                "role": "feature_center",
                "target": "feature:F_MAIN.centerline.z",
            },
        ],
        "source_ids": ["ANN_40"],
        "required_for_modeling": True,
    }


def _gate0(raw):
    result = write_strict_evidence(raw)
    # Every successful Gate 0 result must survive the strict schema again.
    strict = EvidenceGraph.model_validate(result.evidence.model_dump(mode="json"))
    return result, strict


def _gate0_items(result):
    added = [
        item
        for item in result.evidence.unresolved_evidence
        if str(item.get("id", "")).startswith("G0_")
    ]
    observations = [
        item
        for item in result.evidence.observations
        if item.get("kind") == "gate0_quarantine"
    ]
    return added, observations


def test_gate0_passes_legal_dimension_without_quarantine():
    result, strict = _gate0(_capture(dimensions=[_valid_dimension()]))

    assert len(strict.dimensions) == 1
    assert strict.dimensions[0].id == "D_MAIN_Z40"
    assert result.report["passed_dimensions"] == 1
    assert result.report["quarantined_dimensions"] == 0
    assert result.report["added_blocking_unresolved"] == 0


@pytest.mark.parametrize(
    "record",
    [
        {
            "id": "D_MISSING",
            "value": 24,
            "axis": "X",
            "source_ids": ["ANN_24"],
            "required_for_modeling": True,
        },
        {
            "id": "D_EMPTY",
            "value": 40,
            "axis": "Z",
            "endpoints": [],
            "source_ids": ["ANN_40"],
            "required_for_modeling": True,
        },
        {
            "id": "D_ONE",
            "value": 40,
            "axis": "Z",
            "endpoints": [{"role": "overall_min"}],
            "required_for_modeling": True,
        },
        {
            "id": "D_THREE",
            "value": 40,
            "axis": "Z",
            "endpoints": [
                {"role": "overall_min"},
                {"role": "feature_center", "target": "feature:F_A.centerline.z"},
                {"role": "overall_max"},
            ],
            "required_for_modeling": True,
        },
    ],
)
def test_gate0_quarantines_missing_or_wrong_endpoint_count(record):
    result, strict = _gate0(_capture(dimensions=[record]))
    added, observations = _gate0_items(result)

    assert strict.dimensions == []
    assert result.report["passed_dimensions"] == 0
    assert result.report["quarantined_dimensions"] == 1
    assert len(added) == 1
    assert added[0]["required_for_modeling"] is True
    assert added[0]["raw_path"] == "$.dimensions[0]"
    assert added[0]["raw_record"] == record
    assert len(observations) == 1
    assert observations[0]["raw_record"] == record


@pytest.mark.parametrize(
    "role",
    [
        "intermediate_surface",
        "step_surface",
        "feature_boundary",
        "profile_boundary",
        "profile_edge",
        "hidden_surface_top",
        "internal_surface",
    ],
)
def test_gate0_quarantines_unsupported_endpoint_roles(role):
    record = {
        "id": "D_BAD_ROLE",
        "value": 8,
        "axis": "Z",
        "endpoints": [
            {"role": "overall_min"},
            {"role": role, "target": "feature:F_STEP.top_surface"},
        ],
        "source_ids": ["ANN_8"],
        "required_for_modeling": True,
    }

    result, strict = _gate0(_capture(dimensions=[record]))
    added, _ = _gate0_items(result)

    assert strict.dimensions == []
    assert result.report["quarantined_dimensions"] == 1
    assert len(added) == 1
    assert "strict-schema compliant" in added[0]["reason"]


def test_gate0_quarantines_overall_endpoint_that_carries_target():
    record = {
        "id": "D_H66",
        "value": 66,
        "axis": "Z",
        "endpoints": [
            {"role": "overall_min", "target": "body:front.overall.z_min"},
            {"role": "overall_max", "target": "body:front.overall.z_max"},
        ],
        "source_ids": ["OBS_DIM_66"],
    }

    result, strict = _gate0(_capture(dimensions=[record]))
    added, _ = _gate0_items(result)

    assert strict.dimensions == []
    assert len(added) == 1
    assert added[0]["raw_record"] == record


def test_gate0_quarantines_string_dimension_value_without_parsing_nominal():
    record = {
        "id": "D_FRONT_40TOL",
        "value": "40 +/- 0.02",
        "axis": "Z",
        "endpoints": [
            {
                "role": "intermediate_surface",
                "note": "candidate lower endpoint",
            },
            {
                "role": "feature_center",
                "target": "feature:F_MAIN.centerline.z",
            },
        ],
        "source_ids": ["ANN_40TOL"],
        "required_for_modeling": True,
        "endpoint_binding": "unresolved",
    }

    result, strict = _gate0(_capture(dimensions=[record]))
    added, _ = _gate0_items(result)

    assert strict.dimensions == []
    assert len(added) == 1
    assert added[0]["raw_record"]["value"] == "40 +/- 0.02"
    assert not any(
        item.value == 40
        for item in strict.dimensions
    )


def test_gate0_quarantines_unknown_axis_without_inference():
    record = {
        "id": "D_16_SIDE",
        "value": 16,
        "axis": "unknown",
        "endpoints": [],
        "source_ids": ["ANN_16_SIDE"],
        "required_for_modeling": True,
    }

    result, strict = _gate0(_capture(dimensions=[record]))
    added, _ = _gate0_items(result)

    assert strict.dimensions == []
    assert len(added) == 1
    assert added[0]["raw_record"]["axis"] == "unknown"


def test_gate0_passes_legal_relation():
    relation = {
        "id": "R_ALIGN",
        "kind": "alignment",
        "axis": "Z",
        "targets": [
            "feature:F_A.centerline.z",
            "feature:F_B.centerline.z",
        ],
        "source_ids": ["OBS_ALIGN"],
        "required_for_modeling": True,
    }

    result, strict = _gate0(_capture(relations=[relation]))

    assert len(strict.relations) == 1
    assert strict.relations[0].kind == "alignment"
    assert result.report["passed_relations"] == 1
    assert result.report["quarantined_relations"] == 0


@pytest.mark.parametrize(
    "relation",
    [
        {
            "id": "R_CBORE_COAXIAL",
            "kind": "coaxial_members",
            "targets": [
                "feature:F_CB.member.through",
                "feature:F_CB.member.counterbore",
            ],
            "source_ids": ["OBS_CBORE_CONCENTRIC"],
        },
        {
            "id": "R_COMPOUND_MEMBERS",
            "type": "compound_hole_membership",
            "targets": ["feature:F_COMPOUND"],
            "detail": "raw Reader relation",
            "source_ids": ["ANN_CB"],
            "required_for_modeling": True,
        },
        {
            "id": "R_CB_MEMBERS",
            "type": "compound_hole_members",
            "feature_id": "F_CB_HOLE",
            "members": ["member:through", "member:counterbore"],
            "source_ids": ["OBS_CB_CIRCLES"],
            "required_for_modeling": True,
        },
    ],
)
def test_gate0_quarantines_reader_defined_relation_vocab_without_mapping(relation):
    result, strict = _gate0(_capture(relations=[relation]))
    added, observations = _gate0_items(result)

    assert strict.relations == []
    assert result.report["passed_relations"] == 0
    assert result.report["quarantined_relations"] == 1
    assert len(added) == 1
    assert added[0]["raw_record"] == relation
    assert len(observations) == 1


def test_gate0_preserves_existing_reader_unresolved():
    existing = {
        "id": "U_READER_START_SIDE",
        "target": "feature:F_M6.start_side",
        "reason": "drawing does not establish start side",
        "required_for_modeling": True,
        "evidence": ["OBS_M6"],
    }

    result, strict = _gate0(_capture(unresolved_evidence=[existing]))

    assert strict.unresolved_evidence == [existing]
    assert result.report["added_unresolved"] == 0
    assert result.report["total_unresolved"] == 1


def test_gate0_preserves_extra_fields_as_observation_without_semantic_inference():
    record = _valid_dimension()
    record["tolerance"] = {"type": "bilateral", "value": 0.02}
    record["note"] = "Reader raw note"

    result, strict = _gate0(_capture(dimensions=[record]))

    assert len(strict.dimensions) == 1
    extras = [
        item
        for item in strict.observations
        if item.get("kind") == "gate0_extra_fields"
    ]
    assert len(extras) == 1
    assert extras[0]["extra_fields"]["tolerance"]["value"] == 0.02
    assert extras[0]["extra_fields"]["note"] == "Reader raw note"


def test_gate0_quarantine_keeps_safe_single_target_when_unambiguous():
    record = {
        "id": "D_BAD",
        "value": 40,
        "axis": "Z",
        "endpoints": [
            {
                "role": "intermediate_surface",
                "target": "feature:F_MAIN.centerline.z",
            },
            {"role": "overall_min"},
        ],
        "required_for_modeling": True,
    }

    result, _ = _gate0(_capture(dimensions=[record]))
    added, _ = _gate0_items(result)

    assert added[0]["target"] == "feature:F_MAIN.centerline.z"


def test_gate0_duplicate_global_evidence_id_quarantines_later_record():
    capture = _capture(
        views=[
            {"id": "DUP", "kind": "front"},
        ],
        projections=[
            {
                "id": "DUP",
                "feature_id": "F_MAIN",
                "view_id": "V_FRONT",
                "shape": "circle",
            }
        ],
    )

    result, strict = _gate0(capture)
    added, _ = _gate0_items(result)

    assert len(strict.views) == 1
    assert strict.projections == []
    assert any("duplicate evidence id" in item["reason"] for item in added)


def test_gate0_invalid_required_target_is_quarantined_not_coerced():
    result, strict = _gate0(
        _capture(required_targets=["feature:F_MAIN.centerline.z", "", 123])
    )
    added, _ = _gate0_items(result)

    assert strict.required_targets == ["feature:F_MAIN.centerline.z"]
    assert len([item for item in added if item["raw_path"].startswith("$.required_targets")]) == 2


def test_gate0_identical_capture_is_deterministic():
    capture = _capture(
        dimensions=[
            _valid_dimension(),
            {
                "id": "D_BAD",
                "value": 24,
                "axis": "Y",
                "endpoints": [],
                "source_ids": ["ANN_24"],
            },
        ],
        unresolved_evidence=[
            {
                "id": "U_EXISTING",
                "reason": "existing Reader ambiguity",
                "required_for_modeling": True,
            }
        ],
    )

    first = write_strict_evidence(capture)
    second = write_strict_evidence(capture)

    assert first.evidence.model_dump(mode="json") == second.evidence.model_dump(mode="json")
    assert first.report == second.report


def test_gate0_cli_writes_schema_valid_output_even_with_blocking_unresolved(tmp_path: Path):
    raw = _capture(
        dimensions=[
            {
                "id": "D_EMPTY",
                "value": 40,
                "axis": "Z",
                "endpoints": [],
                "source_ids": ["ANN_40"],
                "required_for_modeling": True,
            }
        ]
    )
    capture_path = tmp_path / "reader-capture.json"
    output_path = tmp_path / "drawing-evidence.json"
    capture_path.write_text(json.dumps(raw), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "gate0",
            str(capture_path),
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["written"] is True
    assert report["schema_valid"] is True
    assert report["quarantined_dimensions"] == 1
    assert report["added_blocking_unresolved"] == 1

    strict_raw = json.loads(output_path.read_text(encoding="utf-8"))
    strict = EvidenceGraph.model_validate(strict_raw)
    assert strict.dimensions == []
    assert len(strict.unresolved_evidence) == 1


def test_gate0_cli_refuses_in_place_overwrite(tmp_path: Path):
    path = tmp_path / "reader-capture.json"
    path.write_text(json.dumps(_capture()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "gate0",
            str(path),
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["written"] is False
    assert report["schema_valid"] is False


@pytest.mark.parametrize("target", ["datum:A", "gdt:position", "body:front.overall.z_min"])
def test_gate0_quarantines_direct_targets_not_consumable_by_frozen_draft(target):
    record = {
        "id": "DV_UNSUPPORTED",
        "target": target,
        "value": 40,
        "source_ids": ["OBS_UNSUPPORTED"],
    }

    result, strict = _gate0(_capture(direct_values=[record]))
    added, observations = _gate0_items(result)

    assert strict.direct_values == []
    assert result.report["passed_direct_values"] == 0
    assert result.report["quarantined_direct_values"] == 1
    assert len(added) == 1
    assert added[0]["raw_record"] == record
    assert "not consumable by the frozen semantic-draft contract" in added[0]["reason"]
    assert len(observations) == 1


@pytest.mark.parametrize(
    "target",
    [
        "feature:F_MAIN.diameter",
        "overall_dimensions.length_x",
        "profile.width",
    ],
)
def test_gate0_allows_direct_targets_supported_by_frozen_draft(target):
    record = {
        "id": "DV_SUPPORTED",
        "target": target,
        "value": 40,
        "source_ids": ["OBS_SUPPORTED"],
    }

    result, strict = _gate0(_capture(direct_values=[record]))

    assert len(strict.direct_values) == 1
    assert strict.direct_values[0].target == target
    assert result.report["passed_direct_values"] == 1
    assert result.report["quarantined_direct_values"] == 0
