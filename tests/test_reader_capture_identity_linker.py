from __future__ import annotations

import nx_mcp.drawing_intelligence.identity_linker as identity_linker

import json
import subprocess
import sys
from pathlib import Path

import pytest
import nx_mcp.drawing_intelligence.identity_linker as identity_linker_module
from pydantic import ValidationError

from nx_mcp.drawing_intelligence import (
    AssociationClaim,
    CaptureCenterlineAlignment,
    CaptureDatumAlignment,
    CaptureDimension,
    CaptureDimensionEndpoint,
    CaptureEntity,
    CaptureRequiredTarget,
    CaptureValue,
    CaptureView,
    ReaderCapture,
    build_semantic_draft,
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.capture import (
    CaptureUnresolvedEvidence,
    validate_reader_capture_contract,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.stability import compare_evidence_runs

ROOT = Path(__file__).resolve().parents[1]


def _capture(prefix: str, *, reverse_association: bool = False) -> ReaderCapture:
    front = f"{prefix}_FRONT_ENTITY"
    side = f"{prefix}_SIDE_ENTITY"
    association_entities = [front, side]
    if reverse_association:
        association_entities.reverse()

    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(
                id=f"{prefix}_VF",
                kind="front",
                source_ids=[f"{prefix}_SRC_VIEW_FRONT"],
            ),
            CaptureView(
                id=f"{prefix}_VS",
                kind="side",
                source_ids=[f"{prefix}_SRC_VIEW_SIDE"],
            ),
        ],
        entities=[
            CaptureEntity(
                id=front,
                view_id=f"{prefix}_VF",
                shape="circle",
                cross_view_disposition="associated",
                source_ids=[f"{prefix}_SRC_FRONT"],
            ),
            CaptureEntity(
                id=side,
                view_id=f"{prefix}_VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
                source_ids=[f"{prefix}_SRC_SIDE"],
            ),
        ],
        associations=[
            AssociationClaim(
                id=f"{prefix}_ASSOC",
                entity_ids=association_entities,
                basis=["projection_alignment", "unique_orthographic_counterpart"],
                source_ids=[f"{prefix}_SRC_ASSOC"],
            )
        ],
        values=[
            CaptureValue(
                id=f"{prefix}_DIA",
                entity_id=front,
                field="diameter",
                value=20,
                source_ids=[f"{prefix}_SRC_DIA"],
            ),
            CaptureValue(
                id=f"{prefix}_FIT",
                entity_id=front,
                field="fit",
                value="H7",
                source_ids=[f"{prefix}_SRC_FIT"],
            ),
        ],
        dimensions=[
            CaptureDimension(
                id=f"{prefix}_Z40",
                value=40,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="overall_min",
                        source_ids=[f"{prefix}_SRC_Z40_MIN"],
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id=front,
                        basis="centerline",
                        source_ids=[f"{prefix}_SRC_Z40_CENTER"],
                    ),
                ],
                source_ids=[f"{prefix}_SRC_Z40"],
            )
        ],
        required_targets=[],
    )


def test_identity_linker_feature_id_ignores_reader_local_entity_names():
    first = link_reader_capture(_capture("A"))
    second = link_reader_capture(_capture("TOTALLY_DIFFERENT"))

    first_ids = {item.feature_id for item in first.evidence.projections}
    second_ids = {item.feature_id for item in second.evidence.projections}

    assert len(first_ids) == 1
    assert first_ids == second_ids

    first_feature = next(iter(first_ids))
    assert first.evidence.direct_values[0].target.startswith(
        f"feature:{first_feature}."
    )
    assert first.evidence.dimensions[0].endpoints[1].target == (
        f"feature:{first_feature}.centerline.z"
    )


def test_identity_linker_association_order_does_not_change_feature_id():
    first = link_reader_capture(_capture("A", reverse_association=False))
    second = link_reader_capture(_capture("A", reverse_association=True))

    assert first.entity_to_feature == second.entity_to_feature
    assert {
        item.feature_id for item in first.evidence.projections
    } == {
        item.feature_id for item in second.evidence.projections
    }


def test_identity_linker_without_association_keeps_view_entities_separate():
    capture = _capture("A")
    capture.associations = []

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 2
    assert len(set(result.entity_to_feature.values())) == 2


def test_production_capture_rejects_same_view_multi_entity_association():
    with pytest.raises(ValidationError, match="multiple entities from the same view"):
        ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[CaptureView(id="VF", kind="front")],
            entities=[
                CaptureEntity(id="E1", view_id="VF", shape="circle"),
                CaptureEntity(id="E2", view_id="VF", shape="circle"),
            ],
            associations=[
                AssociationClaim(
                    id="A_BAD",
                    entity_ids=["E1", "E2"],
                    basis=["explicit_section_correspondence"],
                    required_for_modeling=True,
                )
            ],
        )


def test_identity_linker_accepts_shared_raster_profile_identity_across_region_views():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[
            CaptureView(id="V_R1", kind="front"),
            CaptureView(id="V_R2", kind="front"),
        ],
        entities=[
            CaptureEntity(
                id="E_R1",
                view_id="V_R1",
                shape="profile",
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id="E_R2",
                view_id="V_R2",
                shape="profile",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A_SHARED_RASTER",
                entity_ids=["E_R1", "E_R2"],
                basis=["shared_raster_profile_identity"],
                source_ids=["SRC_SHARED_RASTER"],
                required_for_modeling=False,
            )
        ],
        required_targets=[
            CaptureRequiredTarget(entity_id="E_R1", field="boundary.x"),
            CaptureRequiredTarget(entity_id="E_R2", field="boundary.x"),
        ],
    )

    result = link_reader_capture(capture)

    assert result.entity_to_feature["E_R1"] == result.entity_to_feature["E_R2"]
    assert result.report["rejected_associations"] == 0


def test_identity_linker_quarantines_legacy_same_view_multi_entity_association():
    capture = ReaderCapture.model_construct(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle"),
            CaptureEntity(id="E2", view_id="VF", shape="circle"),
        ],
        associations=[
            AssociationClaim(
                id="A_BAD",
                entity_ids=["E1", "E2"],
                basis=["explicit_section_correspondence"],
                required_for_modeling=True,
            )
        ],
        values=[],
        dimensions=[],
        datum_alignments=[],
        required_targets=[],
        observations=[],
        unresolved_evidence=[],
        schema_version="2.0",
        coordinate_system="overall_min_xyz",
    )

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 2
    assert any(
        item["id"] == "U_ASSOC_A_BAD"
        and item["required_for_modeling"] is True
        for item in result.evidence.unresolved_evidence
    )


def test_identity_linker_identical_disconnected_components_fail_closed():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle"),
            CaptureEntity(id="E2", view_id="VF", shape="circle"),
        ],
    )

    result = link_reader_capture(capture)

    assert result.report["identity_collisions"] == 1
    assert result.report["blocking_unresolved"] >= 1
    assert any(
        str(item.get("id", "")).startswith("U_IDENTITY_COLLISION_")
        for item in result.evidence.unresolved_evidence
    )


def test_identity_linker_dimension_axis_maps_entity_center_target_deterministically():
    capture = _capture("A")
    result = link_reader_capture(capture)
    feature_id = result.entity_to_feature["A_FRONT_ENTITY"]

    dimension = result.evidence.dimensions[0]
    assert dimension.axis == "Z"
    assert dimension.endpoints[1].target == (
        f"feature:{feature_id}.centerline.z"
    )


def test_identity_linker_output_passes_strict_evidence_schema():
    result = link_reader_capture(_capture("A"))

    # model_dump + model_validate exercises the public strict boundary.
    raw = result.evidence.model_dump(mode="json")
    validated = type(result.evidence).model_validate(raw)

    assert validated.schema_version == "1.0"
    assert validated.coordinate_system == "overall_min_xyz"


def test_link_capture_cli_produces_strict_downstream_consumable_evidence(tmp_path: Path):
    capture = _capture("CLI")
    capture_path = tmp_path / "reader-capture.json"
    evidence_path = tmp_path / "drawing-evidence.json"
    capture_path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
            str(capture_path),
            str(evidence_path),
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
    assert report["capture_entities"] == 2
    assert report["physical_components"] == 1
    assert evidence_path.exists()

    from nx_mcp.drawing_intelligence import EvidenceGraph

    graph = EvidenceGraph.model_validate(
        json.loads(evidence_path.read_text(encoding="utf-8"))
    )
    compiled = compile_evidence_graph(graph)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)

    assert draft["features"]
    assert draft["dimension_closure"]["status"] in {
        "closed",
        "incomplete",
        "conflict",
    }


def test_link_capture_cli_feature_identity_is_local_id_independent(tmp_path: Path):
    feature_ids = []

    for prefix in ("FIRST", "SECOND_COMPLETELY_DIFFERENT"):
        capture = _capture(prefix)
        capture_path = tmp_path / f"{prefix}-capture.json"
        evidence_path = tmp_path / f"{prefix}-evidence.json"
        capture_path.write_text(
            json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "nx_mcp.drawing_intelligence",
                "link-capture",
                str(capture_path),
                str(evidence_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

        raw = json.loads(evidence_path.read_text(encoding="utf-8"))
        feature_ids.append(
            sorted({item["feature_id"] for item in raw["projections"]})
        )

    assert feature_ids[0] == feature_ids[1]


def test_link_capture_cli_refuses_in_place_overwrite(tmp_path: Path):
    capture = _capture("CLI")
    path = tmp_path / "reader-capture.json"
    path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
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
    assert path.exists()


def test_reader_capture_normalizes_string_observations():
    capture = ReaderCapture.model_validate(
        {
            "schema_version": "2.0",
            "coordinate_system": "overall_min_xyz",
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "views": [],
            "entities": [],
            "associations": [],
            "values": [],
            "dimensions": [],
            "datum_alignments": [],
            "required_targets": [],
            "observations": [
                "first prose observation",
                {"kind": "already_structured", "value": 1},
            ],
            "unresolved_evidence": [],
        }
    )

    assert capture.observations[0] == {
        "kind": "reader_observation",
        "text": "first prose observation",
        "capture_index": 0,
    }
    assert capture.observations[1] == {
        "kind": "already_structured",
        "value": 1,
    }


def test_identity_collision_placeholders_keep_disconnected_components_distinct():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_LEFT",
                view_id="VF",
                shape="hidden_parallel",
            ),
            CaptureEntity(
                id="E_RIGHT",
                view_id="VF",
                shape="hidden_parallel",
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D_SPACING",
                value=24,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_LEFT",
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_RIGHT",
                    ),
                ],
                required_for_modeling=True,
            )
        ],
        unresolved_evidence=[
            {
                "id": "U_PAIRING",
                "reason": "cross-view pairing is not uniquely established",
                "required_for_modeling": True,
            }
        ],
    )

    result = link_reader_capture(capture)

    left = result.entity_to_feature["E_LEFT"]
    right = result.entity_to_feature["E_RIGHT"]

    assert left != right
    assert left.endswith("_AMB_01")
    assert right.endswith("_AMB_02")
    assert result.report["identity_collisions"] == 1

    compiled = compile_evidence_graph(result.evidence)
    spacing = next(
        item for item in compiled.relations
        if item.id == "D_SPACING"
    )

    assert spacing.kind == "center_distance"
    assert len(spacing.targets) == 2
    assert spacing.targets[0] != spacing.targets[1]



def test_identity_collision_is_advisory_when_all_colliding_projections_are_noncritical():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_LEFT",
                view_id="VF",
                shape="circle",
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_RIGHT",
                view_id="VF",
                shape="circle",
                required_for_modeling=False,
            ),
        ],
    )

    result = link_reader_capture(capture)

    left = result.entity_to_feature["E_LEFT"]
    right = result.entity_to_feature["E_RIGHT"]
    collision = next(
        item
        for item in result.evidence.unresolved_evidence
        if item["id"].startswith("U_IDENTITY_COLLISION_")
    )

    assert left != right
    assert left.endswith("_AMB_01")
    assert right.endswith("_AMB_02")
    assert collision["required_for_modeling"] is False
    assert result.report["identity_collisions"] == 1
    assert result.report["blocking_unresolved"] == 0

def test_run02_shape_string_observations_collision_and_spacing_is_linkable(tmp_path: Path):
    capture = ReaderCapture.model_validate(
        {
            "schema_version": "2.0",
            "coordinate_system": "overall_min_xyz",
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "views": [
                {"id": "V_FRONT", "kind": "front", "source_ids": ["OBS_V_FRONT"]},
                {"id": "V_SIDE", "kind": "side", "source_ids": ["OBS_V_SIDE"]},
            ],
            "entities": [
                {
                    "id": "E_FRONT_05",
                    "view_id": "V_FRONT",
                    "shape": "hidden_parallel",
                    "cross_view_disposition": "unresolved",
                    "source_ids": ["OBS_E_FRONT_05"],
                    "required_for_modeling": True,
                },
                {
                    "id": "E_FRONT_06",
                    "view_id": "V_FRONT",
                    "shape": "hidden_parallel",
                    "cross_view_disposition": "unresolved",
                    "source_ids": ["OBS_E_FRONT_06"],
                    "required_for_modeling": True,
                },
            ],
            "associations": [],
            "values": [],
            "dimensions": [
                {
                    "id": "D_04",
                    "value": 24,
                    "axis": "X",
                    "endpoints": [
                        {
                            "role": "entity_center",
                            "entity_id": "E_FRONT_05",
                            "basis": "centerline",
                            "source_ids": ["OBS_D04_LEFT"],
                        },
                        {
                            "role": "entity_center",
                            "entity_id": "E_FRONT_06",
                            "basis": "centerline",
                            "source_ids": ["OBS_D04_RIGHT"],
                        },
                    ],
                    "source_ids": ["OBS_DIM_D04"],
                    "required_for_modeling": True,
                }
            ],
            "datum_alignments": [],
            "required_targets": [],
            "observations": [
                "Two hidden groups are visible in the front view."
            ],
            "unresolved_evidence": [
                {
                    "id": "U_05",
                    "kind": "member_identity",
                    "reason": "the two candidates cannot be uniquely paired across views",
                    "entity_ids": ["E_FRONT_05", "E_FRONT_06"],
                    "source_ids": ["OBS_MEMBER_IDENTITY"],
                    "required_for_modeling": True,
                }
            ],
        }
    )

    capture_path = tmp_path / "capture-run-02.json"
    evidence_path = tmp_path / "linked-run-02.json"
    capture_path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
            str(capture_path),
            str(evidence_path),
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
    assert report["identity_collisions"] == 1
    assert evidence_path.exists()


def test_identity_linker_canonicalizes_hole_diameter_alias():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_SIDE", kind="side")],
        entities=[
            CaptureEntity(
                id="E_SIDE_A",
                view_id="V_SIDE",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_DIA_A",
                entity_id="E_SIDE_A",
                field="hole_diameter",
                value=20,
            )
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_SIDE", kind="side")],
        entities=[
            CaptureEntity(
                id="E_SIDE_B",
                view_id="V_SIDE",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_DIA_B",
                entity_id="E_SIDE_B",
                field="diameter",
                value=20,
            )
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    assert linked_a.evidence.direct_values[0].target.endswith(".diameter")
    assert linked_b.evidence.direct_values[0].target.endswith(".diameter")


def test_identity_linker_canonicalizes_thread_depth_alias():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_THREAD_A",
                view_id="V_FRONT",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_THREAD_SPEC_A",
                entity_id="E_THREAD_A",
                field="thread_spec",
                value="M6",
            ),
            CaptureValue(
                id="S_DEPTH_A",
                entity_id="E_THREAD_A",
                field="depth",
                value=12,
            ),
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_THREAD_B",
                view_id="V_FRONT",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_THREAD_SPEC_B",
                entity_id="E_THREAD_B",
                field="thread_spec",
                value="M6",
            ),
            CaptureValue(
                id="S_DEPTH_B",
                entity_id="E_THREAD_B",
                field="thread_depth",
                value=12,
            ),
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    assert {
        item.target.rsplit(".", 1)[1]
        for item in linked_a.evidence.direct_values
    } == {"thread_spec", "thread_depth"}


def test_identity_linker_canonicalizes_edge_on_hole_profile_shape():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EFC", view_id="VF", shape="circle"),
            CaptureEntity(id="ESA", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EFC", "ESA"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(id="S1", entity_id="ESA", field="diameter", value=20)
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EFC2", view_id="VF", shape="circle"),
            CaptureEntity(id="ESB", view_id="VS", shape="profile"),
        ],
        associations=[
            AssociationClaim(
                id="A2",
                entity_ids=["EFC2", "ESB"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(id="S2", entity_id="ESB", field="diameter", value=20)
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    side_shapes_a = {
        item.shape
        for item in linked_a.evidence.projections
        if item.view_id == "VS"
    }
    side_shapes_b = {
        item.shape
        for item in linked_b.evidence.projections
        if item.view_id == "VS"
    }
    assert side_shapes_a == {"hidden_parallel"}
    assert side_shapes_b == {"hidden_parallel"}


def test_identity_linker_ignores_unreferenced_outer_profile():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="VS", kind="side")],
        entities=[
            CaptureEntity(id="E_PROFILE", view_id="VS", shape="profile"),
            CaptureEntity(id="E_HOLE", view_id="VS", shape="hidden_parallel"),
        ],
        values=[
            CaptureValue(
                id="S_HOLE",
                entity_id="E_HOLE",
                field="diameter",
                value=6.6,
            )
        ],
    )

    result = link_reader_capture(capture)

    assert "E_PROFILE" not in result.entity_to_feature
    assert "E_HOLE" in result.entity_to_feature
    assert result.report["ignored_orphan_profiles"] == 1
    assert all(
        item.source_ids[0] != "E_PROFILE"
        for item in result.evidence.projections
    )


def test_identity_linker_derives_formal_required_targets():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle")
        ],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="hole_diameter",
                value=20,
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=18,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_max"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E1",
                    ),
                ],
                required_for_modeling=True,
            )
        ],
        required_targets=[
            CaptureRequiredTarget(
                entity_id="E1",
                field="centerline",
            )
        ],
    )

    result = link_reader_capture(capture)
    feature_id = result.entity_to_feature["E1"]

    assert result.evidence.required_targets == [
        f"feature:{feature_id}.centerline.z",
        f"feature:{feature_id}.diameter",
    ]
    assert any(
        item.get("kind") == "reader_required_targets_advisory"
        for item in result.evidence.observations
    )


def test_reader_capture_rejects_unknown_top_level_and_nested_fields():
    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "overall_min_xyz",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": 50,
                    "height_z": 20,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
                "unexpected": 1,
            }
        )

    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "overall_min_xyz",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": 50,
                    "height_z": 20,
                    "unexpected": 1,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
            }
        )


def test_reader_capture_rejects_non_numeric_overall_scalar():
    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "overall_min_xyz",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": "50",
                    "height_z": 20,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
            }
        )


def test_current_capture_contract_rejects_legacy_value_alias_and_freeform_blocker():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="circle")],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="hole_diameter",
                value=10,
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                reason="modeling-critical ambiguity",
                required_for_modeling=True,
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("non-canonical field" in item for item in errors)
    assert any("structured kind" in item for item in errors)


def test_open_slot_tangent_relation_closes_only_bottom_z():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="V1", shape="circle"),
            CaptureEntity(id="E2", view_id="V1", shape="slot_edges"),
        ],
        values=[
            CaptureValue(id="D1", entity_id="E1", field="diameter", value=20),
            CaptureValue(id="K1", entity_id="E2", field="type", value="slot"),
            CaptureValue(id="W1", entity_id="E2", field="width", value=2),
            CaptureValue(id="A1", entity_id="E2", field="width_axis", value="X"),
            CaptureValue(id="Z1", entity_id="E2", field="top_z", value=66),
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="feature_value",
                reason="through unknown",
                entity_ids=["E2"],
                field="through_axis",
                source_ids=["test"],
                required_for_modeling=True,
            ),
            CaptureUnresolvedEvidence(
                id="U2",
                kind="feature_value",
                reason="bottom from tangent",
                entity_ids=["E2"],
                field="bottom_z",
                source_ids=["test"],
                required_for_modeling=True,
            ),
        ],
        observations=[
            {
                "kind": "hybrid_open_slot_ledger",
                "items": [
                    {
                        "slot_entity_id": "E2",
                        "circle_entity_id": "E1",
                        "region_id": "R1",
                        "source_item_index": 2,
                        "top_boundary_ref": "R1.TOP",
                        "circle_entity": "R1.C1",
                        "basis": (
                            "unique_overall_top_gap_plus_two_descending_walls_plus_"
                            "circle_center_alignment_and_upper_circle_termination"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
            }
        ],
    )

    relations, resolved = identity_linker._open_slot_tangent_relations(
        capture,
        {"E1": "F_CIRCLE", "E2": "F_SLOT"},
    )

    assert len(relations) == 2
    tangent = next(item for item in relations if item.kind == "upper_tangent")
    alignment = next(item for item in relations if item.kind == "alignment")
    assert tangent.targets == [
        "feature:F_CIRCLE.centerline.z",
        "feature:F_SLOT.bottom_z",
    ]
    assert tangent.diameter_target == "feature:F_CIRCLE.diameter"
    assert alignment.axis == "X"
    assert alignment.targets == [
        "feature:F_CIRCLE.centerline.x",
        "feature:F_SLOT.centerline.x",
    ]
    assert resolved == {("F_SLOT", "bottom_z")}

    unresolved = identity_linker._linked_reader_unresolved(
        capture,
        {"E1": "F_CIRCLE", "E2": "F_SLOT"},
        relation_resolved_fields=resolved,
    )
    assert [item["field"] for item in unresolved] == ["through_axis"]


def test_current_capture_contract_accepts_canonical_slot_value_fields():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="slot_edges")],
        values=[
            CaptureValue(id="K1", entity_id="E1", field="type", value="slot"),
            CaptureValue(id="W1", entity_id="E1", field="width", value=2),
            CaptureValue(id="A1", entity_id="E1", field="width_axis", value="X"),
            CaptureValue(id="A2", entity_id="E1", field="through_axis", value="Y"),
            CaptureValue(id="Z1", entity_id="E1", field="top_z", value=20),
            CaptureValue(id="Z2", entity_id="E1", field="bottom_z", value=10),
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert not any("non-canonical field" in item for item in errors)


def test_current_capture_contract_accepts_canonical_start_side_value():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="hidden_parallel")],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="start_side",
                value="max",
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert not any("non-canonical field" in item for item in errors)


def test_current_capture_contract_accepts_split_thread_entry_values():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="hidden_parallel")],
        values=[
            CaptureValue(
                id="M1",
                entity_id="E1",
                field="material_side",
                value="min",
            ),
            CaptureValue(
                id="E2",
                entity_id="E1",
                field="entry_endpoint",
                value="max",
            ),
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert not any("non-canonical field" in item for item in errors)


def _unresolved_capture(prefix: str, kind: str) -> ReaderCapture:
    entity_id = f"{prefix}_ENTITY"
    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id=f"{prefix}_VIEW", kind="front")],
        entities=[
            CaptureEntity(
                id=entity_id,
                view_id=f"{prefix}_VIEW",
                shape="hidden_parallel",
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id=f"{prefix}_U",
                kind=kind,
                reason="wording may differ between runs",
                entity_ids=[entity_id],
                field="termination",
                required_for_modeling=True,
            )
        ],
    )


def test_structured_unresolved_is_stable_across_local_id_changes():
    first = link_reader_capture(
        _unresolved_capture("RUN_A", "termination")
    ).evidence
    second = link_reader_capture(
        _unresolved_capture("RUN_B", "termination")
    ).evidence

    report = compare_evidence_runs([first, second])

    assert report.stable is True
    assert report.unique_fingerprints == 1
    assert report.unresolved_semantic_drift == []


def test_targetless_unresolved_semantic_drift_changes_fingerprint():
    first = link_reader_capture(
        _unresolved_capture("RUN_A", "termination")
    ).evidence
    second = link_reader_capture(
        _unresolved_capture("RUN_B", "start_side")
    ).evidence

    report = compare_evidence_runs([first, second])

    assert report.stable is False
    assert report.unique_fingerprints == 2
    assert report.unresolved_semantic_drift
    assert "unresolved_semantics" in report.changed_sections[2]


def test_check_capture_cli_is_authoritative_contract_gate(tmp_path: Path):
    valid = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="circle")],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="diameter",
                value=10,
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="termination",
                reason="termination is not directly established",
                entity_ids=["E1"],
                field="termination",
                required_for_modeling=True,
            )
        ],
    )
    valid_path = tmp_path / "valid-capture.json"
    valid_path.write_text(
        json.dumps(valid.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "check-capture",
            str(valid_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_valid"] is True
    assert report["contract_valid"] is True

    invalid = valid.model_dump(mode="json")
    invalid["values"][0]["field"] = "hole_diameter"
    invalid_path = tmp_path / "invalid-capture.json"
    invalid_path.write_text(
        json.dumps(invalid, ensure_ascii=False),
        encoding="utf-8",
    )

    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "check-capture",
            str(invalid_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert failed.returncode == 1
    failed_report = json.loads(failed.stdout)
    assert failed_report["schema_valid"] is True
    assert failed_report["contract_valid"] is False
    assert any(
        "non-canonical field" in item
        for item in failed_report["errors"]
    )


def test_production_capture_rejects_alignment_only_association_basis():
    common = dict(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
    )

    for insufficient_basis in (
        ["projection_alignment", "shared_centerline"],
        ["projection_alignment", "matching_specification"],
    ):
        with pytest.raises(ValidationError, match="identity-sufficient visual basis"):
            ReaderCapture(
                **common,
                associations=[
                    AssociationClaim(
                        id="A_INSUFFICIENT",
                        entity_ids=["EF", "ES"],
                        basis=insufficient_basis,
                    )
                ],
            )

    strong = ReaderCapture(
        **common,
        associations=[
            AssociationClaim(
                id="A_STRONG",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
    )
    result = link_reader_capture(strong)
    assert result.report["physical_components"] == 1
    assert result.report["rejected_associations"] == 0

def test_current_capture_contract_requires_entity_center_visual_basis():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="VF", shape="circle")],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=10,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_min"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E1",
                    ),
                ],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)
    assert any("requires centerline/center_mark/explicit_midline basis" in item for item in errors)

    capture.dimensions[0].endpoints[1].basis = "center_mark"
    assert validate_reader_capture_contract(capture) == []


def test_identity_linker_preserves_labeled_dimension_relation_ledger_without_geometry():
    ledger = {
        "kind": "hybrid_labeled_dimension_relation_ledger",
        "schema": "1.0",
        "items": [
            {
                "target_id": "LD_0004",
                "source_item_index": 4,
                "source_text": "S- 4.5 mm",
                "region_id": "R1",
                "value": 4.5,
                "axis": "X",
                "relation": "between_profile_boundaries",
                "profile_transition_geometry": "orthogonal",
                "symmetry_scope": "single",
                "evidence": ["hybrid:whole:4", "structural:R1"],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
        "engineering_value_source": "hybrid_ocr",
        "relation_source": "bounded_structural_context",
    }
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        observations=[ledger],
    )

    result = link_reader_capture(capture)

    preserved = [
        item
        for item in result.evidence.observations
        if item.get("kind") == "hybrid_labeled_dimension_relation_ledger"
    ]
    assert preserved == [ledger]
    assert result.evidence.relations == []
    assert result.evidence.required_targets == []


def test_identity_linker_preserves_labeled_dimension_relation_ledger_with_optional_null_metadata():
    ledger = {
        "kind": "hybrid_labeled_dimension_relation_ledger",
        "schema": "1.0",
        "items": [
            {
                "target_id": "LD_0004",
                "source_item_index": 4,
                "source_text": "S - 4.5 mm",
                "region_id": "R3",
                "value": 4.5,
                "axis": "X",
                "relation": "between_profile_boundaries",
                "profile_transition_geometry": None,
                "symmetry_scope": None,
                "evidence": ["hybrid:whole:4", "structural:R3"],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
        "engineering_value_source": "hybrid_ocr",
        "relation_source": "bounded_structural_context",
    }
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        observations=[ledger],
    )

    result = link_reader_capture(capture)

    preserved = [
        item
        for item in result.evidence.observations
        if item.get("kind") == "hybrid_labeled_dimension_relation_ledger"
    ]
    assert preserved == [ledger]


def test_identity_linker_rejects_labeled_dimension_ledger_with_invalid_provenance_flags():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        observations=[
            {
                "kind": "hybrid_labeled_dimension_relation_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "target_id": "LD_0004",
                        "source_item_index": 4,
                        "source_text": "S- 4.5 mm",
                        "region_id": "R1",
                        "value": 4.5,
                        "axis": "X",
                        "relation": "between_profile_boundaries",
                        "profile_transition_geometry": "orthogonal",
                        "symmetry_scope": "single",
                        "evidence": ["hybrid:whole:4", "structural:R1"],
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": True,
                "pixel_geometry_used_for_topology_only": True,
                "engineering_value_source": "hybrid_ocr",
                "relation_source": "bounded_structural_context",
            }
        ],
    )

    result = link_reader_capture(capture)

    assert not [
        item
        for item in result.evidence.observations
        if item.get("kind") == "hybrid_labeled_dimension_relation_ledger"
    ]
    assert result.evidence.relations == []
    assert result.evidence.required_targets == []


def test_identity_linker_collapses_equivalent_cross_view_direct_writers():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
                source_ids=["SRC_FRONT"],
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=10,
                source_ids=["SRC_SIDE"],
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert len(diameter) == 1
    assert diameter[0].value == 10
    assert diameter[0].id.startswith("L_DIRECT_")
    assert diameter[0].source_ids == [
        "VF_DIA",
        "SRC_FRONT",
        "VS_DIA",
        "SRC_SIDE",
    ]

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["features"]


def test_identity_linker_does_not_collapse_conflicting_direct_values():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=11,
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert diameter == []

    conflicts = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "direct_value_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["required_for_modeling"] is True
    assert conflicts[0]["candidates"] == [
        {"value": 10, "semantic": None},
        {"value": 11, "semantic": None},
    ]

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["dimension_closure"]["status"] == "incomplete"


def test_identity_linker_does_not_collapse_explicit_semantic_disagreement():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
                semantic="diameter",
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=10,
                semantic="feature_dimension",
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert diameter == []

    conflicts = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "direct_value_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["candidates"] == [
        {"value": 10, "semantic": "diameter"},
        {"value": 10, "semantic": "feature_dimension"},
    ]


def test_stability_detects_different_direct_conflict_candidates():
    def build(second_value: int):
        capture = ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=100,
                width_y=50,
                height_z=20,
            ),
            views=[
                CaptureView(id="VF", kind="front"),
                CaptureView(id="VS", kind="side"),
            ],
            entities=[
                CaptureEntity(id="EF", view_id="VF", shape="circle"),
                CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
            ],
            associations=[
                AssociationClaim(
                    id="A1",
                    entity_ids=["EF", "ES"],
                    basis=["projection_alignment", "unique_orthographic_counterpart"],
                )
            ],
            values=[
                CaptureValue(
                    id="V1",
                    entity_id="EF",
                    field="diameter",
                    value=10,
                ),
                CaptureValue(
                    id="V2",
                    entity_id="ES",
                    field="diameter",
                    value=second_value,
                ),
            ],
        )
        return link_reader_capture(capture).evidence

    report = compare_evidence_runs([build(11), build(12)])

    assert report.stable is False
    assert "unresolved_semantics" in report.changed_sections[2]
    assert report.unresolved_semantic_drift


def test_contract_requires_cross_view_disposition_for_modeling_entity():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="circle",
            ),
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("requires cross_view_disposition" in error for error in errors)


def test_contract_accepts_consistent_cross_view_dispositions():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="EA",
                view_id="VF",
                shape="circle",
                cross_view_disposition="associated",
                source_ids=["OBS_EA"],
            ),
            CaptureEntity(
                id="EB",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
                source_ids=["OBS_EB"],
            ),
            CaptureEntity(
                id="EC",
                view_id="VF",
                shape="slot_edges",
                cross_view_disposition="single_view",
                source_ids=["OBS_EC"],
            ),
            CaptureEntity(
                id="ED",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="unresolved",
                source_ids=["OBS_ED"],
            ),
            CaptureEntity(
                id="EE",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="unresolved",
                source_ids=["OBS_EE"],
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EA", "EB"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
                source_ids=["OBS_A1"],
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="cross_view_identity",
                reason="alignment exists but identity-specific evidence is insufficient",
                entity_ids=["ED", "EE"],
                basis=["projection_alignment", "shared_centerline"],
                source_ids=["OBS_U1"],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []


def test_contract_rejects_inconsistent_cross_view_disposition():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="EA",
                view_id="VF",
                shape="circle",
                cross_view_disposition="single_view",
            ),
            CaptureEntity(
                id="EB",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EA", "EB"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("declares single_view" in error for error in errors)


def test_unresolved_dimension_endpoint_is_normalized_by_linker():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
                source_ids=["OBS_E1"],
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=16,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["OBS_D1_OVERALL_MAX"],
                    ),
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        candidate_entity_ids=["E1"],
                        unresolved_kind="ambiguous_owner",
                        source_ids=["OBS_D1_AMBIGUOUS"],
                    ),
                ],
                unresolved_reason="visible endpoint does not uniquely own a center",
                source_ids=["OBS_D1"],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []

    result = link_reader_capture(capture)

    assert result.evidence.dimensions == []
    unresolved = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "dimension_endpoint"
    ]
    assert len(unresolved) == 1
    assert unresolved[0]["capture_dimension_id"] == "D1"
    assert unresolved[0]["dimension_value"] == 16
    assert unresolved[0]["axis"] == "Y"
    assert unresolved[0]["required_for_modeling"] is True
    assert unresolved[0]["feature_ids"]


def test_contract_rejects_legacy_dimension_endpoint_unresolved_container():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U_DIM_OLD",
                kind="dimension_endpoint",
                reason="legacy split-container dimension ambiguity",
                dimension_value=16,
                axis="Y",
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any(
        "must be represented by dimensions[]" in error
        for error in errors
    )


def test_identity_linker_quarantines_dimension_whose_endpoints_collapse():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="EF",
                view_id="VF",
                shape="circle",
                cross_view_disposition="associated",
                source_ids=["OBS_EF"],
            ),
            CaptureEntity(
                id="ES",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
                source_ids=["OBS_ES"],
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
                source_ids=["OBS_A1"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D_COLLAPSE",
                value=12,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="EF",
                        basis="centerline",
                        source_ids=["OBS_D_COLLAPSE_FRONT"],
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="ES",
                        basis="centerline",
                        source_ids=["OBS_D_COLLAPSE_SIDE"],
                    ),
                ],
                source_ids=["OBS_D_COLLAPSE"],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []

    result = link_reader_capture(capture)

    assert result.evidence.dimensions == []
    collapsed = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("id") == "U_DIM_COLLAPSE_D_COLLAPSE"
    ]
    assert len(collapsed) == 1
    assert collapsed[0]["kind"] == "dimension_endpoint"
    assert collapsed[0]["dimension_value"] == 12
    assert collapsed[0]["axis"] == "X"
    assert collapsed[0]["required_for_modeling"] is True
    assert collapsed[0]["feature_ids"]
    assert len(collapsed[0]["feature_ids"]) == 1

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["dimension_closure"]["status"] == "incomplete"


def test_production_capture_rejects_overlapping_association_claims():
    associations = [
        AssociationClaim(
            id="A_LEFT",
            entity_ids=["E_FRONT_LEFT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "unique_orthographic_counterpart"],
        ),
        AssociationClaim(
            id="A_RIGHT",
            entity_ids=["E_FRONT_RIGHT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "unique_orthographic_counterpart"],
        ),
    ]
    with pytest.raises(ValidationError, match="appears in multiple associations"):
        ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=10,
            ),
            views=[
                CaptureView(id="VF", kind="front"),
                CaptureView(id="VS", kind="side"),
            ],
            entities=[
                CaptureEntity(
                    id="E_FRONT_LEFT",
                    view_id="VF",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
                CaptureEntity(
                    id="E_FRONT_RIGHT",
                    view_id="VF",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
                CaptureEntity(
                    id="E_SIDE_GROUP",
                    view_id="VS",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
            ],
            associations=associations,
        )


def test_identity_linker_quarantines_legacy_transitive_same_view_collision():
    entities = [
        CaptureEntity(
            id="E_FRONT_LEFT",
            view_id="VF",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
        CaptureEntity(
            id="E_FRONT_RIGHT",
            view_id="VF",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
        CaptureEntity(
            id="E_SIDE_GROUP",
            view_id="VS",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
    ]
    associations = [
        AssociationClaim(
            id="A_LEFT",
            entity_ids=["E_FRONT_LEFT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "unique_orthographic_counterpart"],
        ),
        AssociationClaim(
            id="A_RIGHT",
            entity_ids=["E_FRONT_RIGHT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "unique_orthographic_counterpart"],
        ),
    ]
    capture = ReaderCapture.model_construct(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=10,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=entities,
        associations=associations,
        values=[],
        dimensions=[],
        datum_alignments=[],
        required_targets=[],
        observations=[],
        unresolved_evidence=[],
        schema_version="2.0",
        coordinate_system="overall_min_xyz",
    )

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 3
    assert len(set(result.entity_to_feature.values())) == 3
    blockers = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "association_structure"
    ]
    assert len(blockers) == 1
    assert "transitive association component" in blockers[0]["reason"]


def test_feature_id_ignores_direct_value_and_datum_payload():
    base = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="circle",
            )
        ],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="diameter",
                value=20,
            )
        ],
    )
    changed = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF2", kind="front")],
        entities=[
            CaptureEntity(
                id="E2",
                view_id="VF2",
                shape="circle",
            )
        ],
        values=[
            CaptureValue(
                id="S2",
                entity_id="E2",
                field="diameter",
                value=25,
            )
        ],
        datum_alignments=[
            CaptureDatumAlignment(
                id="DA1",
                entity_id="E2",
                axis="X",
                datum="overall_center",
            )
        ],
    )

    first = link_reader_capture(base)
    second = link_reader_capture(changed)

    assert first.entity_to_feature["E1"] == second.entity_to_feature["E2"]

def test_stability_is_permutation_invariant_within_identity_collision_group():
    def make_capture(thread_id: str, left_id: str, right_id: str) -> ReaderCapture:
        return ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[CaptureView(id="VF", kind="front")],
            entities=[
                CaptureEntity(
                    id=thread_id,
                    view_id="VF",
                    shape="hidden_parallel",
                ),
                CaptureEntity(
                    id=left_id,
                    view_id="VF",
                    shape="hidden_parallel",
                ),
                CaptureEntity(
                    id=right_id,
                    view_id="VF",
                    shape="hidden_parallel",
                ),
            ],
            values=[
                CaptureValue(
                    id="THREAD_SPEC",
                    entity_id=thread_id,
                    field="thread_spec",
                    value="M6",
                ),
                CaptureValue(
                    id="THREAD_DEPTH",
                    entity_id=thread_id,
                    field="thread_depth",
                    value=12,
                ),
                CaptureValue(
                    id="LEFT_DIA",
                    entity_id=left_id,
                    field="diameter",
                    value=6.6,
                ),
                CaptureValue(
                    id="RIGHT_DIA",
                    entity_id=right_id,
                    field="diameter",
                    value=6.6,
                ),
            ],
            dimensions=[
                CaptureDimension(
                    id="D_SPACING",
                    value=24,
                    axis="X",
                    endpoints=[
                        CaptureDimensionEndpoint(
                            role="entity_center",
                            entity_id=left_id,
                            basis="centerline",
                        ),
                        CaptureDimensionEndpoint(
                            role="entity_center",
                            entity_id=right_id,
                            basis="centerline",
                        ),
                    ],
                )
            ],
        )

    first = link_reader_capture(
        make_capture("A_THREAD", "B_LEFT", "C_RIGHT")
    ).evidence
    second = link_reader_capture(
        make_capture("Z_THREAD", "A_LEFT", "B_RIGHT")
    ).evidence

    report = compare_evidence_runs([first, second])

    assert report.stable
    assert report.unique_fingerprints == 1


def test_stability_still_detects_real_value_drift_inside_collision_group():
    def make_capture(diameter: float) -> ReaderCapture:
        return ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[CaptureView(id="VF", kind="front")],
            entities=[
                CaptureEntity(id="E1", view_id="VF", shape="hidden_parallel"),
                CaptureEntity(id="E2", view_id="VF", shape="hidden_parallel"),
            ],
            values=[
                CaptureValue(
                    id="V1",
                    entity_id="E1",
                    field="diameter",
                    value=diameter,
                ),
                CaptureValue(
                    id="V2",
                    entity_id="E2",
                    field="diameter",
                    value=6.6,
                ),
            ],
        )

    first = link_reader_capture(make_capture(6.6)).evidence
    second = link_reader_capture(make_capture(8.0)).evidence

    report = compare_evidence_runs([first, second])

    assert not report.stable
    assert report.unique_fingerprints == 2

def test_production_feature_value_unresolved_requires_one_entity_and_field():
    base_kwargs = dict(
        id="U_VALUE",
        kind="feature_value",
        reason="value is not uniquely readable",
        required_for_modeling=True,
    )

    with pytest.raises(ValidationError, match="exactly one local entity"):
        CaptureUnresolvedEvidence(
            **base_kwargs,
            entity_ids=[],
            field="diameter",
        )

    with pytest.raises(ValidationError, match="requires the ambiguous field"):
        CaptureUnresolvedEvidence(
            **base_kwargs,
            entity_ids=["E1"],
        )

    valid = CaptureUnresolvedEvidence(
        **base_kwargs,
        entity_ids=["E1"],
        field="diameter",
    )

    assert valid.entity_ids == ["E1"]
    assert valid.field == "diameter"


def test_identity_ambiguity_remains_fieldless_cross_view_unresolved():
    item = CaptureUnresolvedEvidence(
        id="U_ID",
        kind="cross_view_identity",
        reason="same physical identity is not uniquely established",
        entity_ids=["E_FRONT", "E_SIDE"],
        required_for_modeling=True,
    )

    assert item.field is None
    assert item.entity_ids == ["E_FRONT", "E_SIDE"]

def test_reader_capture_rejects_inconsistent_opposite_overall_dimension_chain():
    with pytest.raises(
        ValidationError,
        match="resolved overall-boundary dimensions",
    ):
        ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[CaptureView(id="VF", kind="front")],
            entities=[
                CaptureEntity(
                    id="E_CENTER",
                    view_id="VF",
                    shape="circle",
                )
            ],
            dimensions=[
                CaptureDimension(
                    id="D_FROM_MIN",
                    value=40,
                    axis="Z",
                    endpoints=[
                        CaptureDimensionEndpoint(role="overall_min"),
                        CaptureDimensionEndpoint(
                            role="entity_center",
                            entity_id="E_CENTER",
                            basis="centerline",
                        ),
                    ],
                ),
                CaptureDimension(
                    id="D_FROM_MAX",
                    value=18,
                    axis="Z",
                    endpoints=[
                        CaptureDimensionEndpoint(
                            role="entity_center",
                            entity_id="E_CENTER",
                            basis="centerline",
                        ),
                        CaptureDimensionEndpoint(role="overall_max"),
                    ],
                ),
            ],
        )


def test_reader_capture_accepts_consistent_opposite_overall_dimension_chain():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_CENTER",
                view_id="VF",
                shape="circle",
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D_FROM_MIN",
                value=48,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_min"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_CENTER",
                        basis="centerline",
                    ),
                ],
            ),
            CaptureDimension(
                id="D_FROM_MAX",
                value=18,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_CENTER",
                        basis="centerline",
                    ),
                    CaptureDimensionEndpoint(role="overall_max"),
                ],
            ),
        ],
    )

    assert len(capture.dimensions) == 2


def test_reader_capture_rejects_other_shape_for_cylindrical_semantics():
    with pytest.raises(
        ValidationError,
        match="must use circle/concentric_circles/hidden_parallel",
    ):
        ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[CaptureView(id="VF", kind="front")],
            entities=[
                CaptureEntity(
                    id="E_HOLE",
                    view_id="VF",
                    shape="other",
                )
            ],
            values=[
                CaptureValue(
                    id="S_THREAD",
                    entity_id="E_HOLE",
                    field="thread_spec",
                    value="M6",
                )
            ],
        )



def test_production_multiview_contract_requires_traceable_sources():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="EF",
                view_id="VF",
                shape="circle",
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id="ES",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
            )
        ],
        values=[
            CaptureValue(
                id="S1",
                entity_id="ES",
                field="diameter",
                value=20,
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=18,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_max"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="EF",
                        basis="centerline",
                    ),
                ],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("view 'VF' requires non-empty source_ids" in item for item in errors)
    assert any("modeling-critical entity 'EF' requires non-empty" in item for item in errors)
    assert any("association 'A1' requires non-empty source_ids" in item for item in errors)
    assert any("value 'S1' requires non-empty source_ids" in item for item in errors)
    assert any("modeling-critical dimension 'D1' requires" in item for item in errors)


def test_cross_view_identity_unique_sufficient_pair_must_be_association():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="EF",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="unresolved",
                source_ids=["OBS_EF"],
            ),
            CaptureEntity(
                id="ES",
                view_id="VS",
                shape="concentric_circles",
                cross_view_disposition="unresolved",
                source_ids=["OBS_ES"],
            ),
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="cross_view_identity",
                reason="only one candidate pair remains",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
                source_ids=["OBS_PAIR"],
                required_for_modeling=True,
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any(
        "one unique cross-view pair with identity-sufficient basis" in item
        for item in errors
    )


def test_cross_view_identity_insufficient_basis_may_remain_unresolved():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="EF",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="unresolved",
                source_ids=["OBS_EF"],
            ),
            CaptureEntity(
                id="ES",
                view_id="VS",
                shape="concentric_circles",
                cross_view_disposition="unresolved",
                source_ids=["OBS_ES"],
            ),
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="cross_view_identity",
                reason="alignment is visible but identity-specific evidence is absent",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "shared_centerline"],
                source_ids=["OBS_PAIR"],
                required_for_modeling=True,
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []


def test_unresolved_basis_is_preserved_and_compared():
    def make(basis):
        capture = ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=66,
            ),
            views=[
                CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
                CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
            ],
            entities=[
                CaptureEntity(
                    id="EF",
                    view_id="VF",
                    shape="hidden_parallel",
                    cross_view_disposition="unresolved",
                    source_ids=["OBS_EF"],
                ),
                CaptureEntity(
                    id="ES",
                    view_id="VS",
                    shape="hidden_parallel",
                    cross_view_disposition="unresolved",
                    source_ids=["OBS_ES"],
                ),
            ],
            unresolved_evidence=[
                CaptureUnresolvedEvidence(
                    id="U1",
                    kind="cross_view_identity",
                    reason="identity remains unresolved",
                    entity_ids=["EF", "ES"],
                    basis=basis,
                    source_ids=["OBS_PAIR"],
                )
            ],
        )
        return link_reader_capture(capture).evidence

    first = make(["projection_alignment", "shared_centerline"])
    second = make(["projection_alignment", "shared_center_mark"])

    report = compare_evidence_runs([first, second])

    assert report.stable is False
    assert "unresolved_semantics" in report.changed_sections[2]
    assert report.unresolved_semantic_drift



def test_multiview_dimension_endpoint_witness_contract_is_structured():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
                source_ids=["OBS_E1"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        unresolved_kind="intermediate_surface",
                        source_ids=["OBS_STEP_WITNESS"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["OBS_OUTER_WITNESS"],
                    ),
                ],
                unresolved_reason="first witness terminates on intermediate surface",
                source_ids=["OBS_DIM_8"],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []

    linked = link_reader_capture(capture)
    item = next(
        entry
        for entry in linked.evidence.unresolved_evidence
        if entry.get("kind") == "dimension_endpoint"
    )
    assert item["endpoint_unresolved_kinds"] == ["intermediate_surface"]
    assert "OBS_STEP_WITNESS" in item["source_ids"]
    assert "OBS_OUTER_WITNESS" in item["source_ids"]


def test_multiview_dimension_endpoint_contract_rejects_untraceable_or_malformed_unresolved():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
                source_ids=["OBS_E1"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        candidate_entity_ids=["E1"],
                    ),
                    CaptureDimensionEndpoint(role="overall_max"),
                ],
                unresolved_reason="ownership not resolved",
                source_ids=["OBS_DIM_8"],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("endpoint 0 requires non-empty source_ids" in item for item in errors)
    assert any("endpoint 1 requires non-empty source_ids" in item for item in errors)
    assert any("unresolved endpoint 0 requires unresolved_kind" in item for item in errors)


def test_intermediate_surface_endpoint_cannot_carry_feature_candidates():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["OBS_VF"]),
            CaptureView(id="VS", kind="side", source_ids=["OBS_VS"]),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
                source_ids=["OBS_E1"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        unresolved_kind="intermediate_surface",
                        candidate_entity_ids=["E1"],
                        source_ids=["OBS_STEP_WITNESS"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["OBS_OUTER_WITNESS"],
                    ),
                ],
                unresolved_reason="witness terminates on intermediate surface",
                source_ids=["OBS_DIM_8"],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any(
        "intermediate_surface endpoint 0 must not carry candidate_entity_ids" in item
        for item in errors
    )


def test_identity_linker_required_targets_exclude_non_numeric_direct_values():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="other",
                required_for_modeling=False,
            )
        ],
        values=[
            CaptureValue(
                id="THREAD_SPEC",
                entity_id="E1",
                field="thread_spec",
                value="M6",
            ),
            CaptureValue(
                id="THREAD_DEPTH",
                entity_id="E1",
                field="thread_depth",
                value=12,
            ),
            CaptureValue(
                id="FIT",
                entity_id="E1",
                field="fit",
                value="H7",
            ),
            CaptureValue(
                id="THROUGH",
                entity_id="E1",
                field="through",
                value=True,
            ),
        ],
    )

    result = link_reader_capture(capture)
    feature_id = result.entity_to_feature["E1"]

    assert {
        item.target: item.value
        for item in result.evidence.direct_values
    } == {
        f"feature:{feature_id}.fit": "H7",
        f"feature:{feature_id}.thread_depth": 12,
        f"feature:{feature_id}.thread_spec": "M6",
        f"feature:{feature_id}.through": True,
    }
    assert result.evidence.required_targets == [
        f"feature:{feature_id}.thread_depth"
    ]

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)

    assert resolution.values == {
        f"feature:{feature_id}.thread_depth": 12.0
    }
    assert not [
        item
        for item in resolution.unresolved
        if item.get("id")
        in {
            f"target:feature:{feature_id}.thread_spec",
            f"target:feature:{feature_id}.fit",
            f"target:feature:{feature_id}.through",
        }
    ]


def test_capture_accepts_circle_center_as_entity_center_basis():
    endpoint = CaptureDimensionEndpoint(
        role="entity_center",
        entity_id="E1",
        basis="circle_center",
        source_ids=["OBS_CIRCLE_CENTER"],
    )

    assert endpoint.role == "entity_center"
    assert endpoint.entity_id == "E1"
    assert endpoint.basis == "circle_center"


def _symmetric_profile_span_capture(*, include_symmetry_observation):
    observations = []
    if include_symmetry_observation:
        observations.append(
            {
                "kind": "hybrid_symmetric_profile_span_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "candidate_id": "DG_SPAN",
                        "axis": "X",
                        "datum": "overall_center",
                        "profile_entity_ids": ["E_LEFT", "E_RIGHT"],
                        "dimension_value": 40.0,
                        "overall_dimension_value": 100.0,
                        "source_ids": ["SRC_PROFILE_SPAN_SYMMETRY"],
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_identity_only": True,
                    }
                ],
            }
        )
    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=80,
            height_z=20,
        ),
        views=[CaptureView(id="VF", kind="front", source_ids=["SRC_FRONT"])],
        entities=[
            CaptureEntity(
                id="E_LEFT",
                view_id="VF",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["SRC_LEFT"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_RIGHT",
                view_id="VF",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["SRC_RIGHT"],
                required_for_modeling=False,
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D_SPAN",
                value=40,
                axis="X",
                direction=1,
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_LEFT",
                        basis="profile_edge",
                        source_ids=["SRC_LEFT_ENDPOINT"],
                    ),
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_RIGHT",
                        basis="profile_edge",
                        source_ids=["SRC_RIGHT_ENDPOINT"],
                    ),
                ],
                source_ids=["hybrid:DG_SPAN:whole", "hybrid:DG_SPAN:wide"],
            )
        ],
        observations=observations,
    )


def test_identity_linker_emits_generic_profile_span_midpoint_without_symmetry():
    capture = _symmetric_profile_span_capture(
        include_symmetry_observation=False
    )
    linked = link_reader_capture(capture)

    relation = next(
        item
        for item in linked.evidence.relations
        if item.kind == "midpoint"
    )

    assert relation.id.startswith("R_PROFILE_SPAN_MIDPOINT_")
    assert relation.required_for_modeling is False
    assert relation.targets[1].startswith("constraints.span_centers.C_")
    assert relation.targets[1].endswith(".x")
    assert relation.metadata["basis"] == (
        "resolved_profile_boundary_span_midpoint"
    )
    assert relation.metadata["engineering_coordinate_inferred_from_pixels"] is False


def test_profile_span_midpoint_identity_is_stable_when_endpoint_order_reverses():
    first_capture = _symmetric_profile_span_capture(
        include_symmetry_observation=False
    )
    second_capture = _symmetric_profile_span_capture(
        include_symmetry_observation=False
    )
    second_capture.dimensions[0].endpoints.reverse()

    first = next(
        item
        for item in link_reader_capture(first_capture).evidence.relations
        if item.kind == "midpoint"
    )
    second = next(
        item
        for item in link_reader_capture(second_capture).evidence.relations
        if item.kind == "midpoint"
    )

    assert first.id == second.id
    assert first.targets[1] == second.targets[1]


def _span_center_bridge_capture(
    *,
    endpoint_kind="intermediate_surface",
    two_unresolved=False,
):
    capture = _symmetric_profile_span_capture(
        include_symmetry_observation=False
    )
    second_endpoint = (
        CaptureDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            source_ids=["SRC_DISTANCE_RIGHT"],
        )
        if two_unresolved
        else CaptureDimensionEndpoint(
            role="overall_max",
            source_ids=["SRC_DISTANCE_RIGHT"],
        )
    )
    capture.dimensions.append(
        CaptureDimension(
            id="D_DISTANCE",
            value=30,
            axis="X",
            direction=1,
            endpoints=[
                CaptureDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind=endpoint_kind,
                    source_ids=["SRC_DISTANCE_LEFT"],
                ),
                second_endpoint,
            ],
            unresolved_reason="endpoint ownership unresolved",
            source_ids=["SRC_DISTANCE"],
        )
    )
    capture.observations.extend(
        [
            {
                "kind": "hybrid_profile_span_center_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "dimension_id": "D_SPAN",
                        "axis": "X",
                        "profile_entity_ids": ["E_LEFT", "E_RIGHT"],
                        "selected_witness_positions_px": [30.0, 70.0],
                        "span_midpoint_px": 50.0,
                        "basis": "resolved_profile_boundary_span_midpoint",
                        "source_ids": ["SRC_SPAN_CENTER"],
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            },
            {
                "kind": "hybrid_dimension_span_center_identity_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "dimension_id": "D_DISTANCE",
                        "endpoint_index": 0,
                        "axis": "X",
                        "span_dimension_id": "D_SPAN",
                        "basis": (
                            "unique_witness_to_resolved_profile_span_midpoint"
                        ),
                        "source_ids": ["SRC_WITNESS_TO_SPAN_CENTER"],
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            },
        ]
    )
    return capture


def test_identity_linker_resolves_intermediate_surface_to_profile_span_center():
    capture = _span_center_bridge_capture()

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_DISTANCE"
    ]
    bridge = next(
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    )
    assert bridge.kind == "edge_offset"
    assert bridge.from_side == "max"
    assert bridge.value == 30
    assert bridge.targets[0].startswith("constraints.span_centers.C_")
    assert bridge.metadata["basis"] == (
        "dimension_endpoint_resolved_by_profile_span_center_identity"
    )

    midpoint = next(
        item
        for item in linked.evidence.relations
        if item.kind == "midpoint"
    )
    centered = next(
        item
        for item in linked.evidence.relations
        if item.kind == "centered_span"
    )
    assert centered.value == 40
    assert centered.direction == 1
    assert centered.targets == midpoint.targets

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    center_target = bridge.targets[0]
    assert resolution.values[center_target] == 70.0
    assert resolution.values[centered.targets[0]] == 50.0
    assert resolution.values[centered.targets[2]] == 90.0
    assert not [
        item
        for item in resolution.unresolved
        if item.get("required_for_modeling") is True
    ]


def test_span_center_bridge_requires_every_unresolved_endpoint_to_be_covered():
    capture = _span_center_bridge_capture(two_unresolved=True)

    linked = link_reader_capture(capture)

    assert not [item for item in linked.evidence.relations if item.id == "D_DISTANCE"]
    unresolved = [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_DISTANCE"
    ]
    assert len(unresolved) == 1
    assert unresolved[0]["endpoint_unresolved_kinds"] == ["intermediate_surface"]


def test_span_center_bridge_never_overrides_ambiguous_owner():
    capture = _span_center_bridge_capture(endpoint_kind="ambiguous_owner")

    linked = link_reader_capture(capture)

    assert not [item for item in linked.evidence.relations if item.id == "D_DISTANCE"]
    unresolved = [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_DISTANCE"
    ]
    assert len(unresolved) == 1
    assert unresolved[0]["endpoint_unresolved_kinds"] == ["ambiguous_owner"]


def _symmetric_center_distance_bridge_capture(
    *,
    endpoint_kind="intermediate_surface",
    include_symmetric_pair=True,
    duplicate_pair=False,
):
    capture = _span_center_bridge_capture(
        endpoint_kind=endpoint_kind,
        two_unresolved=True,
    )
    distance = next(item for item in capture.dimensions if item.id == "D_DISTANCE")
    distance.value = 60
    distance.source_ids = [
        "SRC_DISTANCE",
        "hybrid:DG_DISTANCE:whole",
    ]

    if include_symmetric_pair:
        record = {
            "dimension_id": "D_DISTANCE",
            "candidate_id": "DG_DISTANCE",
            "axis": "X",
            "datum": "overall_center",
            "dimension_value": 60,
            "overall_dimension_value": 100,
            "selected_witness_positions_px": [20.0, 80.0],
            "overall_candidate_id": "DG_OVERALL",
            "overall_region_id": "R1",
            "overall_witness_positions_px": [0.0, 100.0],
            "midpoint_residual_px": 0.0,
            "midpoint_tolerance_px": 2.0,
            "basis": (
                "rotational_symmetry_plus_structurally_shared_raster_view"
                "_plus_overall_witness_midpoint"
            ),
            "source_ids": ["SRC_SYMMETRIC_DISTANCE"],
        }
        items = [record, dict(record)] if duplicate_pair else [record]
        capture.observations.append(
            {
                "kind": "hybrid_symmetric_dimension_pair_ledger",
                "schema": "1.0",
                "items": items,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )
    return capture


def test_symmetric_center_distance_bridge_anchors_span_center_and_mirror():
    capture = _symmetric_center_distance_bridge_capture()

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_DISTANCE"
    ]

    distance = next(
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    )
    assert distance.kind == "center_distance"
    assert distance.value == 60
    assert distance.direction == 1
    assert distance.targets[0].startswith("constraints.span_centers.C_")
    assert distance.targets[1].startswith("constraints.symmetric_centers.C_")
    assert distance.metadata["basis"] == (
        "overall_center_symmetric_center_distance"
    )
    assert distance.metadata["engineering_coordinate_inferred_from_pixels"] is False

    anchors = [
        item
        for item in linked.evidence.relations
        if item.id.startswith("R_SYMMETRIC_CENTER_PAIR_")
    ]
    assert {item.from_side for item in anchors} == {"min", "max"}
    assert {item.value for item in anchors} == {20.0}

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    assert resolution.values[distance.targets[0]] == 20.0
    assert resolution.values[distance.targets[1]] == 80.0
    assert resolution.ok


def test_symmetric_intermediate_surface_bridge_preserves_virtual_span():
    capture = _symmetric_center_distance_bridge_capture()
    capture.dimensions = [
        item for item in capture.dimensions if item.id == "D_DISTANCE"
    ]
    capture.observations = [
        observation
        for observation in capture.observations
        if observation.get("kind")
        not in {
            "hybrid_profile_span_center_ledger",
            "hybrid_dimension_span_center_identity_ledger",
            "hybrid_projected_profile_level_ledger",
        }
    ]

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_DISTANCE"
    ]

    distance = next(
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    )
    assert distance.kind == "coordinate_distance"
    assert distance.value == 60
    assert distance.direction == 1
    assert all(
        target.startswith("constraints.symmetric_profile_levels.C_")
        for target in distance.targets
    )
    assert distance.metadata["basis"] == (
        "overall_center_symmetric_intermediate_surface_span"
    )
    assert distance.metadata["physical_endpoint_ownership_unresolved"] is True
    assert distance.metadata["engineering_coordinate_inferred_from_pixels"] is False
    assert distance.metadata["pixel_geometry_used_for_identity_only"] is True

    anchors = [
        item
        for item in linked.evidence.relations
        if item.id.startswith("R_SYMMETRIC_INTERMEDIATE_")
    ]
    assert {item.from_side for item in anchors} == {"min", "max"}
    assert {item.value for item in anchors} == {20.0}

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    assert resolution.values[distance.targets[0]] == 20.0
    assert resolution.values[distance.targets[1]] == 80.0
    assert not [
        item
        for item in resolution.unresolved
        if item.get("required_for_modeling") is True
    ]

    draft = build_semantic_draft(compiled, resolution)
    min_id = distance.targets[0].split(".")[2]
    max_id = distance.targets[1].split(".")[2]
    levels = draft["constraints"]["symmetric_profile_levels"]
    assert levels[min_id]["x"] == -30.0
    assert levels[max_id]["x"] == 30.0


def test_symmetric_intermediate_surface_bridge_rejects_span_center_identity_matches():
    capture = _symmetric_center_distance_bridge_capture()
    identity_ledger = next(
        observation
        for observation in capture.observations
        if observation.get("kind") == "hybrid_dimension_span_center_identity_ledger"
    )
    identity_ledger["items"].append(dict(identity_ledger["items"][0]))

    linked = link_reader_capture(capture)

    assert not [item for item in linked.evidence.relations if item.id == "D_DISTANCE"]
    assert any(
        item.get("capture_dimension_id") == "D_DISTANCE"
        for item in linked.evidence.unresolved_evidence
    )


@pytest.mark.parametrize(
    "invalid_case",
    ["non_center_datum", "midpoint_mismatch", "distance_equals_overall", "no_direction"],
)
def test_symmetric_intermediate_surface_bridge_rejects_invalid_pair_evidence(
    invalid_case,
):
    capture = _symmetric_center_distance_bridge_capture()
    pair_ledger = next(
        observation
        for observation in capture.observations
        if observation.get("kind") == "hybrid_symmetric_dimension_pair_ledger"
    )
    pair = pair_ledger["items"][0]
    distance = next(item for item in capture.dimensions if item.id == "D_DISTANCE")

    if invalid_case == "non_center_datum":
        pair["datum"] = "feature_center"
    elif invalid_case == "midpoint_mismatch":
        pair["selected_witness_positions_px"] = [20.0, 70.0]
    elif invalid_case == "distance_equals_overall":
        distance.value = 100
        pair["dimension_value"] = 100
    else:
        distance.direction = None

    linked = link_reader_capture(capture)

    assert not [item for item in linked.evidence.relations if item.id == "D_DISTANCE"]
    assert any(
        item.get("capture_dimension_id") == "D_DISTANCE"
        for item in linked.evidence.unresolved_evidence
    )


def test_symmetric_intermediate_surface_bridge_does_not_override_projected_owner():
    capture = _projected_profile_bridge_capture(
        symmetric=True,
        one_sided=True,
    )

    linked = link_reader_capture(capture)

    distance = next(
        item
        for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    )
    assert distance.metadata["basis"] == (
        "overall_center_symmetric_projected_profile_level"
    )
    assert any(
        target.endswith(".boundary.x")
        for target in distance.targets
    )


def test_symmetric_center_distance_bridge_requires_structured_pair_topology():
    capture = _symmetric_center_distance_bridge_capture(
        include_symmetric_pair=False
    )

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_DISTANCE"
        for item in linked.evidence.unresolved_evidence
    )


def test_symmetric_center_distance_bridge_rejects_duplicate_pair_topology():
    capture = _symmetric_center_distance_bridge_capture(
        duplicate_pair=True
    )

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_DISTANCE"
        for item in linked.evidence.unresolved_evidence
    )


def test_symmetric_center_distance_bridge_never_overrides_ambiguous_owner():
    capture = _symmetric_center_distance_bridge_capture(
        endpoint_kind="ambiguous_owner"
    )

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.relations
        if item.id == "D_DISTANCE"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_DISTANCE"
        and "ambiguous_owner" in item.get("endpoint_unresolved_kinds", [])
        for item in linked.evidence.unresolved_evidence
    )


def test_identity_linker_anchors_structured_symmetric_profile_span():
    capture = _symmetric_profile_span_capture(include_symmetry_observation=True)
    linked = link_reader_capture(capture)

    left_feature = linked.entity_to_feature["E_LEFT"]
    right_feature = linked.entity_to_feature["E_RIGHT"]
    left_target = f"feature:{left_feature}.boundary.x"
    right_target = f"feature:{right_feature}.boundary.x"

    anchor = next(
        relation
        for relation in linked.evidence.relations
        if relation.id == "R_SYMMETRIC_PROFILE_ANCHOR_D_SPAN"
    )
    assert anchor.kind == "edge_offset"
    assert anchor.value == 30.0
    assert anchor.targets == [left_target]
    assert anchor.metadata["basis"] == (
        "structured_overall_center_symmetric_profile_span"
    )

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    assert resolution.values[left_target] == 30.0
    assert resolution.values[right_target] == 70.0
    assert resolution.ok


def test_identity_linker_does_not_anchor_profile_span_without_structured_symmetry():
    capture = _symmetric_profile_span_capture(include_symmetry_observation=False)
    linked = link_reader_capture(capture)

    assert not any(
        relation.id == "R_SYMMETRIC_PROFILE_ANCHOR_D_SPAN"
        for relation in linked.evidence.relations
    )

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert not resolution.ok


def test_identity_linker_expands_structured_symmetric_count_two_without_hybrid_marker():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=10,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["SRC_FRONT"]),
            CaptureView(id="VS", kind="side", source_ids=["SRC_SIDE"]),
        ],
        entities=[
            CaptureEntity(
                id="E_FRONT_PAIR",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="associated",
                source_ids=["SRC_FRONT_PAIR"],
            ),
            CaptureEntity(
                id="E_SIDE_PAIR",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
                source_ids=["SRC_SIDE_PAIR"],
            ),
        ],
        associations=[
            AssociationClaim(
                id="A_PAIR",
                entity_ids=["E_FRONT_PAIR", "E_SIDE_PAIR"],
                basis=["projection_alignment", "unique_orthographic_counterpart"],
                source_ids=["SRC_PAIR_SPEC"],
            )
        ],
        values=[
            CaptureValue(
                id="V_COUNT",
                entity_id="E_SIDE_PAIR",
                field="count",
                value=2,
            ),
            CaptureValue(
                id="V_DIA",
                entity_id="E_SIDE_PAIR",
                field="diameter",
                value=6.6,
            ),
            CaptureValue(
                id="V_THROUGH",
                entity_id="E_SIDE_PAIR",
                field="through",
                value=True,
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D_X24",
                value=24,
                axis="X",
                direction=1,
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_FRONT_PAIR",
                        basis="centerline",
                        source_ids=["SRC_LEFT_MEMBER"],
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_FRONT_PAIR",
                        basis="centerline",
                        source_ids=["SRC_RIGHT_MEMBER"],
                    ),
                ],
                source_ids=["SRC_SPACING_24"],
            ),
            CaptureDimension(
                id="D_Y24",
                value=24,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_SIDE_PAIR",
                        basis="centerline",
                    ),
                    CaptureDimensionEndpoint(role="overall_max"),
                ],
            ),
        ],
        observations=[
            {
                "id": "PS001",
                "kind": "symmetric_count_two_overall_center",
                "entity_id": "E_FRONT_PAIR",
                "axis": "X",
                "datum": "overall_center",
                "source_ids": ["SRC_PAIR_SYMMETRY"],
                "required_for_modeling": True,
            }
        ],
    )

    linked = link_reader_capture(capture)
    feature_id = linked.entity_to_feature["E_FRONT_PAIR"]
    assert linked.entity_to_feature["E_SIDE_PAIR"] == feature_id

    axis = next(
        item
        for item in linked.evidence.direct_values
        if item.target == f"feature:{feature_id}.axis"
    )
    assert axis.value == "Z"

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)

    reader_x0 = f"feature:{feature_id}.explicit_centers.0.0"
    reader_x1 = f"feature:{feature_id}.explicit_centers.1.0"
    reader_y0 = f"feature:{feature_id}.explicit_centers.0.1"
    reader_y1 = f"feature:{feature_id}.explicit_centers.1.1"

    assert resolution.values[reader_x0] == 8.0
    assert resolution.values[reader_x1] == 32.0
    assert resolution.values[reader_y0] == 8.0
    assert resolution.values[reader_y1] == 8.0
    assert resolution.ok

    feature = next(item for item in draft["features"] if item["id"] == feature_id)
    assert feature["axis"] == "Z"
    assert feature["explicit_centers"] == [[-12.0, -8.0], [12.0, -8.0]]


def test_identity_linker_rejects_marker_only_symmetric_count_two_without_structured_observation():
    marker = "hybrid:symmetric-count2-overall-center"
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=10,
        ),
        views=[CaptureView(id="VS", kind="side")],
        entities=[
            CaptureEntity(
                id="E_PAIR",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
            )
        ],
        values=[
            CaptureValue(id="V_AXIS", entity_id="E_PAIR", field="axis", value="Z"),
            CaptureValue(id="V_COUNT", entity_id="E_PAIR", field="count", value=2),
            CaptureValue(id="V_DIA", entity_id="E_PAIR", field="diameter", value=6.6),
            CaptureValue(id="V_THROUGH", entity_id="E_PAIR", field="through", value=True),
        ],
        dimensions=[
            CaptureDimension(
                id="D_X24",
                value=24,
                axis="X",
                direction=1,
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_PAIR",
                        basis="centerline",
                        source_ids=[marker],
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_PAIR",
                        basis="centerline",
                        source_ids=[marker],
                    ),
                ],
                source_ids=[marker],
            ),
            CaptureDimension(
                id="D_Y24",
                value=24,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_PAIR",
                        basis="centerline",
                    ),
                    CaptureDimensionEndpoint(role="overall_max"),
                ],
            ),
        ],
    )

    linked = link_reader_capture(capture)

    assert any(
        item.get("id") == "U_DIM_COLLAPSE_D_X24"
        and item.get("required_for_modeling") is True
        for item in linked.evidence.unresolved_evidence
    )
    assert not any(
        target.startswith("feature:") and ".explicit_centers." in target
        for target in linked.evidence.required_targets
    )

def test_centerline_alignment_propagates_transverse_coordinates_without_merging_features():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front", source_ids=["front"]),
            CaptureView(id="VS", kind="side", source_ids=["side"]),
        ],
        entities=[
            CaptureEntity(
                id="THREAD",
                view_id="VF",
                shape="hidden_parallel",
                source_ids=["thread"],
            ),
            CaptureEntity(
                id="RECESS",
                view_id="VS",
                shape="concentric_circles",
                source_ids=["recess"],
            ),
        ],
        values=[
            CaptureValue(
                id="V1",
                entity_id="THREAD",
                field="axis",
                value="X",
                source_ids=["thread"],
            ),
            CaptureValue(
                id="V2",
                entity_id="THREAD",
                field="thread_spec",
                value="M6",
                source_ids=["thread"],
            ),
            CaptureValue(
                id="V3",
                entity_id="RECESS",
                field="recessed_hole",
                value=True,
                source_ids=["recess"],
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="DZ",
                value=18,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="THREAD",
                        basis="centerline",
                        source_ids=["dz-thread"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_min",
                        source_ids=["dz-base"],
                    ),
                ],
                source_ids=["dz"],
            ),
            CaptureDimension(
                id="DY",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="RECESS",
                        basis="circle_center",
                        source_ids=["dy-recess"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["dy-edge"],
                    ),
                ],
                source_ids=["dy"],
            ),
        ],
        centerline_alignments=[
            CaptureCenterlineAlignment(
                id="CA001",
                entity_ids=["THREAD", "RECESS"],
                feature_axis="X",
                source_ids=["coaxial"],
            )
        ],
    )

    linked = link_reader_capture(capture)
    assert linked.entity_to_feature["THREAD"] != linked.entity_to_feature["RECESS"]

    compiled = compile_evidence_graph(linked.evidence)
    relation_ids = {item.id for item in compiled.relations}
    assert {"CA001_Y", "CA001_Z"} <= relation_ids

    resolution = resolve_evidence_graph(compiled)
    thread_feature = linked.entity_to_feature["THREAD"]
    recess_feature = linked.entity_to_feature["RECESS"]
    assert resolution.values[f"feature:{recess_feature}.centerline.y"] == 24
    assert resolution.values[f"feature:{thread_feature}.centerline.y"] == 24
    assert resolution.values[f"feature:{thread_feature}.centerline.z"] == 18
    assert resolution.values[f"feature:{recess_feature}.centerline.z"] == 18




def _projected_profile_bridge_capture(
    *,
    symmetric=False,
    one_sided=False,
    ambiguous_profile_target=False,
    endpoint_kind="intermediate_surface",
) -> ReaderCapture:
    entities = [
        CaptureEntity(
            id="E_BOTTOM",
            view_id="VF",
            shape="profile",
            source_ids=["hybrid:profile-edge:R1.BOTTOM"],
            required_for_modeling=False,
        ),
        CaptureEntity(
            id="E_LEFT",
            view_id="VF",
            shape="profile",
            source_ids=["hybrid:profile-edge:R1.LEFT"],
            required_for_modeling=False,
        ),
        CaptureEntity(
            id="E_RIGHT",
            view_id="VF",
            shape="profile",
            source_ids=["hybrid:profile-edge:R1.RIGHT"],
            required_for_modeling=False,
        ),
    ]
    if ambiguous_profile_target:
        entities.append(
            CaptureEntity(
                id="E_LEFT_ALT",
                view_id="VF",
                shape="profile",
                source_ids=["hybrid:profile-edge:R1.LEFT_ALT"],
                required_for_modeling=False,
            )
        )

    if symmetric:
        dimension = CaptureDimension(
            id="D_PROJECTED",
            value=60,
            axis="X",
            direction=1,
            endpoints=[
                CaptureDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind=endpoint_kind,
                    candidate_entity_ids=(
                        ["E_LEFT", "E_LEFT_ALT"]
                        if endpoint_kind == "ambiguous_owner"
                        else []
                    ),
                    source_ids=["SRC_LEFT_WITNESS"],
                ),
                CaptureDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind="intermediate_surface",
                    source_ids=["SRC_RIGHT_WITNESS"],
                ),
            ],
            unresolved_reason="projected profile ownership unresolved",
            source_ids=["hybrid:DG_PROJECTED:whole"],
        )
        projected_items = [
            {
                "dimension_id": "D_PROJECTED",
                "candidate_id": "DG_PROJECTED",
                "endpoint_index": 0,
                "axis": "X",
                "profile_refs": (
                    ["R1.LEFT", "R1.LEFT_ALT"]
                    if ambiguous_profile_target
                    else ["R1.LEFT"]
                ),
                "profile_entity_ids": (
                    ["E_LEFT", "E_LEFT_ALT"]
                    if ambiguous_profile_target
                    else ["E_LEFT"]
                ),
                "overall_role": None,
                "basis": "extension_line_projection_to_structural_profile_level",
                "source_ids": ["SRC_LEFT_PROJECTED"],
            },
        ]
        if not one_sided:
            projected_items.append(
                {
                    "dimension_id": "D_PROJECTED",
                    "candidate_id": "DG_PROJECTED",
                    "endpoint_index": 1,
                    "axis": "X",
                    "profile_refs": ["R1.RIGHT"],
                    "profile_entity_ids": ["E_RIGHT"],
                    "overall_role": None,
                    "basis": "extension_line_projection_to_structural_profile_level",
                    "source_ids": ["SRC_RIGHT_PROJECTED"],
                }
            )
    else:
        dimension = CaptureDimension(
            id="D_PROJECTED",
            value=28,
            axis="Z",
            direction=1,
            endpoints=[
                CaptureDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind=endpoint_kind,
                    candidate_entity_ids=(
                        ["E_BOTTOM"]
                        if endpoint_kind == "ambiguous_owner"
                        else []
                    ),
                    source_ids=["SRC_BOTTOM_WITNESS"],
                ),
                CaptureDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind="intermediate_surface",
                    source_ids=["SRC_STEP_WITNESS"],
                ),
            ],
            unresolved_reason="projected profile ownership unresolved",
            source_ids=["hybrid:DG_PROJECTED:whole"],
        )
        projected_items = [
            {
                "dimension_id": "D_PROJECTED",
                "candidate_id": "DG_PROJECTED",
                "endpoint_index": 0,
                "axis": "Z",
                "profile_refs": ["R1.BOTTOM"],
                "profile_entity_ids": ["E_BOTTOM"],
                "overall_role": "overall_min",
                "basis": "extension_line_projection_to_structural_profile_level",
                "source_ids": ["SRC_BOTTOM_PROJECTED"],
            },
            {
                "dimension_id": "D_PROJECTED",
                "candidate_id": "DG_PROJECTED",
                "endpoint_index": 1,
                "axis": "Z",
                "profile_refs": ["R1.LEFT"],
                "profile_entity_ids": ["E_LEFT"],
                "overall_role": None,
                "basis": "extension_line_projection_to_structural_profile_level",
                "source_ids": ["SRC_STEP_PROJECTED"],
            },
        ]

    observations = [
        {
            "kind": "hybrid_projected_profile_level_ledger",
            "schema": "1.0",
            "items": projected_items,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }
    ]
    if symmetric:
        observations.append(
            {
                "kind": "hybrid_symmetric_dimension_pair_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "dimension_id": "D_PROJECTED",
                        "candidate_id": "DG_PROJECTED",
                        "axis": "X",
                        "datum": "overall_center",
                        "dimension_value": 60,
                        "overall_dimension_value": 100,
                        "selected_witness_positions_px": [20.0, 80.0],
                        "overall_candidate_id": "DG_OVERALL",
                        "overall_region_id": "R1",
                        "overall_witness_positions_px": [0.0, 100.0],
                        "midpoint_residual_px": 0.0,
                        "midpoint_tolerance_px": 2.0,
                        "basis": (
                            "rotational_symmetry_plus_structurally_shared_raster_view"
                            "_plus_overall_witness_midpoint"
                        ),
                        "source_ids": ["SRC_SYMMETRIC_PROJECTED"],
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )

    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=entities,
        dimensions=[dimension],
        observations=observations,
    )


def _view_axis_boundary_capture(*, overall_value=80.0, inferred=False):
    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[
            CaptureView(
                id="VF",
                kind="front",
                source_ids=["structural:R1:context"],
            )
        ],
        entities=[
            CaptureEntity(
                id="E_TOP",
                view_id="VF",
                shape="profile",
                source_ids=["hybrid:profile-edge:R1.TOP"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_BOTTOM",
                view_id="VF",
                shape="profile",
                source_ids=["hybrid:profile-edge:R1.BOTTOM"],
                required_for_modeling=False,
            ),
        ],
        observations=[
            {
                "kind": "hybrid_view_axis_boundary_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "status": "resolved",
                        "region_id": "R1",
                        "view_kind": "front",
                        "axis": "Z",
                        "candidate_id": None,
                        "overall_dimension_value": overall_value,
                        "anchors": [
                            {
                                "ref": "R1.TOP",
                                "pixel_extreme_side": "min",
                                "role": "overall_max",
                                "position_px": 20.0,
                            },
                            {
                                "ref": "R1.BOTTOM",
                                "pixel_extreme_side": "max",
                                "role": "overall_min",
                                "position_px": 100.0,
                            },
                        ],
                        "basis": (
                            "independent_overall_dimension_plus_"
                            "unique_profile_extremes"
                        ),
                        "overall_fact_scope": "same_region_structural_evidence",
                        "engineering_coordinate_inferred_from_pixels": inferred,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": inferred,
            }
        ],
    )


def test_view_axis_boundary_prefers_edge_entity_over_vertices_sharing_edge_source():
    capture = _view_axis_boundary_capture()
    capture.entities.extend(
        [
            CaptureEntity(
                id="E_BOTTOM_VERTEX_MIN",
                view_id="VF",
                shape="profile",
                source_ids=[
                    "hybrid:profile-vertex:R1.BOTTOM.vertex.min",
                    "hybrid:profile-edge:R1.BOTTOM",
                ],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_BOTTOM_VERTEX_MAX",
                view_id="VF",
                shape="profile",
                source_ids=[
                    "hybrid:profile-vertex:R1.BOTTOM.vertex.max",
                    "hybrid:profile-edge:R1.BOTTOM",
                ],
                required_for_modeling=False,
            ),
        ]
    )

    linked = link_reader_capture(capture)

    assert "E_BOTTOM" in linked.entity_to_feature
    assert "E_BOTTOM_VERTEX_MIN" not in linked.entity_to_feature
    assert "E_BOTTOM_VERTEX_MAX" not in linked.entity_to_feature
    bottom_feature = linked.entity_to_feature["E_BOTTOM"]
    bottom_target = f"feature:{bottom_feature}.boundary.z"
    boundary_relations = [
        item
        for item in linked.evidence.relations
        if item.metadata.get("basis")
        == "independent_overall_dimension_plus_unique_profile_extremes"
    ]
    assert any(
        item.from_side == "min"
        and item.targets == [bottom_target]
        for item in boundary_relations
    )

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert resolution.values[bottom_target] == 0.0


def test_view_axis_boundary_ledger_materializes_profile_extremes_and_resolves_coordinates():
    capture = _view_axis_boundary_capture()

    linked = link_reader_capture(capture)

    assert linked.report["ignored_orphan_profiles"] == 0
    top_feature = linked.entity_to_feature["E_TOP"]
    bottom_feature = linked.entity_to_feature["E_BOTTOM"]
    top_target = f"feature:{top_feature}.boundary.z"
    bottom_target = f"feature:{bottom_feature}.boundary.z"

    boundary_relations = [
        item
        for item in linked.evidence.relations
        if item.metadata.get("basis")
        == "independent_overall_dimension_plus_unique_profile_extremes"
    ]
    assert len(boundary_relations) == 2
    assert {
        (item.from_side, item.value, item.targets[0])
        for item in boundary_relations
    } == {
        ("max", 0.0, top_target),
        ("min", 0.0, bottom_target),
    }
    assert all(
        item.metadata["engineering_coordinate_inferred_from_pixels"] is False
        for item in boundary_relations
    )

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert resolution.values[top_target] == 80.0
    assert resolution.values[bottom_target] == 0.0


def test_view_axis_boundary_ledger_fails_closed_on_metric_or_provenance_mismatch():
    for capture in (
        _view_axis_boundary_capture(overall_value=79.0),
        _view_axis_boundary_capture(inferred=True),
    ):
        linked = link_reader_capture(capture)

        assert linked.entity_to_feature == {}
        assert linked.report["ignored_orphan_profiles"] == 2
        assert not [
            item
            for item in linked.evidence.relations
            if item.metadata.get("basis")
            == "independent_overall_dimension_plus_unique_profile_extremes"
        ]



def test_rotational_topology_merges_crop_items_after_physical_identity_link():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[
            CaptureView(id="V_R1", kind="front"),
            CaptureView(id="V_R2", kind="front"),
        ],
        entities=[
            CaptureEntity(
                id="E_R1_SHARED",
                view_id="V_R1",
                shape="profile",
                cross_view_disposition="associated",
                source_ids=["hybrid:profile-edge:R1.SHARED"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_R2_SHARED",
                view_id="V_R2",
                shape="profile",
                cross_view_disposition="associated",
                source_ids=["hybrid:profile-edge:R2.SHARED"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_R1_LOCAL",
                view_id="V_R1",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["hybrid:profile-edge:R1.LOCAL"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_R2_LOCAL",
                view_id="V_R2",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["hybrid:profile-edge:R2.LOCAL"],
                required_for_modeling=False,
            ),
        ],
        associations=[
            AssociationClaim(
                id="A_SHARED",
                entity_ids=["E_R1_SHARED", "E_R2_SHARED"],
                basis=["shared_raster_profile_identity"],
                source_ids=["SRC_SHARED"],
                required_for_modeling=False,
            )
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "R1.SHARED",
                                "profile_entity_id": "E_R1_SHARED",
                                "source_orientation": "vertical",
                                "constant_axis": "X",
                            },
                            {
                                "ref": "R1.LOCAL",
                                "profile_entity_id": "E_R1_LOCAL",
                                "source_orientation": "horizontal",
                                "constant_axis": "Z",
                            },
                        ],
                        "junctions": [["R1.SHARED", "R1.LOCAL"]],
                        "source_ids": ["SRC_R1"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    },
                    {
                        "region_id": "R2",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "R2.SHARED",
                                "profile_entity_id": "E_R2_SHARED",
                                "source_orientation": "vertical",
                                "constant_axis": "X",
                            },
                            {
                                "ref": "R2.LOCAL",
                                "profile_entity_id": "E_R2_LOCAL",
                                "source_orientation": "horizontal",
                                "constant_axis": "Z",
                            },
                        ],
                        "junctions": [["R2.SHARED", "R2.LOCAL"]],
                        "source_ids": ["SRC_R2"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    },
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )

    linked = link_reader_capture(capture)

    ledger = next(
        item
        for item in linked.evidence.observations
        if item.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    assert len(ledger["items"]) == 1
    item = ledger["items"][0]
    assert item["region_ids"] == ["R1", "R2"]
    assert item["region_id"].startswith("PHYSICAL_")
    assert item["basis"] == "identity_linked_physical_rotational_profile_topology"

    shared_feature = linked.entity_to_feature["E_R1_SHARED"]
    assert shared_feature == linked.entity_to_feature["E_R2_SHARED"]
    physical_edges = {
        (edge["physical_feature_id"], edge["constant_axis"])
        for edge in item["edges"]
    }
    assert len(physical_edges) == 3
    assert (shared_feature, "X") in physical_edges
    assert len(item["junctions"]) == 2


def test_physical_oblique_profile_items_merge_crop_duplicates_by_identity():
    observations = [
        {
            "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
            "schema": "1.0",
            "items": [
                {
                    "id": "OBLIQUE_R1",
                    "region_id": "R1",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "supporting_profile_entity_ids": ["E_R1"],
                    "supporting_profile_constant_axes": ["X"],
                    "source_ids": [
                        "structural:R1",
                        "hybrid:oblique-line:46",
                    ],
                    "one_sided_boundary_candidate": True,
                },
                {
                    "id": "OBLIQUE_R2",
                    "region_id": "R2",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "supporting_profile_entity_ids": ["E_R2"],
                    "supporting_profile_constant_axes": ["X"],
                    "source_ids": [
                        "structural:R2",
                        "hybrid:oblique-line:46",
                    ],
                    "one_sided_boundary_candidate": True,
                },
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]

    items = identity_linker_module._physical_rotational_oblique_profile_items(
        observations,
        {
            "E_R1": "F_SHARED",
            "E_R2": "F_SHARED",
        },
    )

    assert len(items) == 1
    item = items[0]
    assert item["region_ids"] == ["R1", "R2"]
    assert item["supporting_physical_feature_ids"] == ["F_SHARED"]
    assert item["supporting_physical_edges"] == [
        {
            "physical_feature_id": "F_SHARED",
            "constant_axis": "X",
            "boundary_target": "feature:F_SHARED.boundary.x",
        }
    ]
    assert item["connection_kind"] == (
        "one_sided_non_orthogonal_boundary_continuation"
    )
    assert item["basis"] == (
        "identity_linked_physical_oblique_profile_topology"
    )
    assert item["engineering_coordinate_inferred_from_pixels"] is False
    assert item["pixel_geometry_used_for_topology_only"] is True
    assert "endpoints_px" not in repr(item)
    assert "angle_deg" not in repr(item)


def test_physical_oblique_profile_items_fail_closed_without_physical_identity():
    observations = [
        {
            "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
            "items": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "supporting_profile_entity_ids": ["E_UNKNOWN"],
                    "supporting_profile_constant_axes": ["X"],
                    "source_ids": ["hybrid:oblique-line:9"],
                    "one_sided_boundary_candidate": True,
                }
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]

    assert (
        identity_linker_module._physical_rotational_oblique_profile_items(
            observations,
            {},
        )
        == []
    )


def test_oblique_dimension_projection_aligns_extension_to_exterior_support():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=300,
            width_y=300,
            height_z=75,
        ),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_LEFT",
                view_id="V_FRONT",
                shape="profile",
                source_ids=["hybrid:profile-edge:LEFT"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_EXTENSION",
                view_id="V_FRONT",
                shape="profile",
                source_ids=["hybrid:profile-edge:EXT"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_OBLIQUE_SUPPORT",
                view_id="V_FRONT",
                shape="profile",
                source_ids=["hybrid:profile-edge:OBLIQUE_SUPPORT"],
                required_for_modeling=False,
            ),
        ],
        associations=[],
        values=[],
        dimensions=[
            CaptureDimension(
                id="D_SPAN",
                value=168.3,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_LEFT",
                        basis="profile_edge",
                        source_ids=["hybrid:DG3:whole"],
                    ),
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_EXTENSION",
                        basis="profile_edge",
                        source_ids=["hybrid:DG3:whole"],
                    ),
                ],
                direction=1,
                source_ids=["hybrid:DG3:whole", "hybrid:DG3:wide"],
            )
        ],
        required_targets=[],
        observations=[
            {
                "kind": "hybrid_dimension_anchor_ledger",
                "items": [
                    {
                        "candidate_id": "DG3",
                        "region_id": "R1",
                        "endpoint_candidate_evidence": {
                            "endpoints": [
                                {
                                    "endpoint_index": 0,
                                    "position_px": 40.0,
                                    "status": "unique_physical_candidate",
                                    "physical_candidates": [
                                        {
                                            "kind": "profile_edge_candidate",
                                            "ref": "LEFT",
                                        }
                                    ],
                                    "ownership_narrowing_basis": None,
                                    "ignored_nonownership_anchors": [],
                                },
                                {
                                    "endpoint_index": 1,
                                    "position_px": 100.0,
                                    "status": "unique_physical_candidate",
                                    "physical_candidates": [
                                        {
                                            "kind": "profile_edge_candidate",
                                            "ref": "EXT",
                                            "position_px": 100.0,
                                        }
                                    ],
                                    "ownership_narrowing_basis": (
                                        "exact_crossing_witness_profile_line_identity"
                                    ),
                                    "ignored_nonownership_anchors": [
                                        {
                                            "kind": "profile_edge_candidate",
                                            "ref": "OBLIQUE_SUPPORT",
                                            "position_px": 100.4,
                                            "axis_tolerance_px": 2.0,
                                            "ownership_rejection_reason": (
                                                "profile_not_connected_to_"
                                                "witness_terminal"
                                            ),
                                        }
                                    ],
                                },
                            ]
                        },
                    }
                ],
            },
            {
                "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "id": "OBLIQUE_R1",
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "supporting_profile_refs": ["OBLIQUE_SUPPORT"],
                        "supporting_profile_entity_ids": ["E_OBLIQUE_SUPPORT"],
                        "supporting_profile_constant_axes": ["X"],
                        "source_ids": [
                            "structural:R1",
                            "hybrid:oblique-line:0",
                        ],
                        "one_sided_boundary_candidate": True,
                        "exterior_boundary_candidate": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
        ],
    )

    relations = identity_linker_module._oblique_dimension_projection_relations(
        capture,
        {
            "E_LEFT": "F_LEFT",
            "E_EXTENSION": "F_EXTENSION",
            "E_OBLIQUE_SUPPORT": "F_OBLIQUE",
        },
    )

    assert len(relations) == 1
    relation = relations[0]
    assert relation.kind == "alignment"
    assert relation.axis == "X"
    assert relation.targets == [
        "feature:F_EXTENSION.boundary.x",
        "feature:F_OBLIQUE.boundary.x",
    ]
    assert relation.value is None
    assert relation.required_for_modeling is False
    assert relation.metadata["engineering_coordinate_inferred_from_pixels"] is False
    assert relation.metadata["pixel_geometry_used_for_identity_only"] is True
    assert relation.metadata["basis"] == (
        "accepted_dimension_extension_projection_to_exterior_oblique_profile"
    )


def test_oblique_dimension_projection_fails_closed_without_near_projection():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=300,
            width_y=300,
            height_z=75,
        ),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_EXTENSION",
                view_id="V_FRONT",
                shape="profile",
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="E_OBLIQUE_SUPPORT",
                view_id="V_FRONT",
                shape="profile",
                required_for_modeling=False,
            ),
        ],
        associations=[],
        values=[],
        dimensions=[
            CaptureDimension(
                id="D_SPAN",
                value=168.3,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_EXTENSION",
                        basis="profile_edge",
                    ),
                    CaptureDimensionEndpoint(
                        role="profile_boundary",
                        entity_id="E_EXTENSION",
                        basis="profile_edge",
                    ),
                ],
                direction=1,
                source_ids=["hybrid:DG3:whole", "hybrid:DG3:wide"],
            )
        ],
        required_targets=[],
        observations=[
            {
                "kind": "hybrid_dimension_anchor_ledger",
                "items": [
                    {
                        "candidate_id": "DG3",
                        "region_id": "R1",
                        "endpoint_candidate_evidence": {
                            "endpoints": [
                                {
                                    "endpoint_index": 0,
                                    "position_px": 40.0,
                                    "physical_candidates": [],
                                    "ignored_nonownership_anchors": [],
                                },
                                {
                                    "endpoint_index": 1,
                                    "position_px": 100.0,
                                    "physical_candidates": [
                                        {
                                            "kind": "profile_edge_candidate",
                                            "ref": "EXT",
                                        }
                                    ],
                                    "ownership_narrowing_basis": (
                                        "exact_crossing_witness_profile_line_identity"
                                    ),
                                    "ignored_nonownership_anchors": [
                                        {
                                            "kind": "profile_edge_candidate",
                                            "ref": "OBLIQUE_SUPPORT",
                                            "position_px": 112.0,
                                            "axis_tolerance_px": 2.0,
                                            "ownership_rejection_reason": (
                                                "profile_not_connected_to_"
                                                "witness_terminal"
                                            ),
                                        }
                                    ],
                                },
                            ]
                        },
                    }
                ],
            },
            {
                "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
                "items": [
                    {
                        "region_id": "R1",
                        "supporting_profile_refs": ["OBLIQUE_SUPPORT"],
                        "supporting_profile_entity_ids": ["E_OBLIQUE_SUPPORT"],
                        "supporting_profile_constant_axes": ["X"],
                        "source_ids": ["hybrid:oblique-line:0"],
                        "one_sided_boundary_candidate": True,
                        "exterior_boundary_candidate": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
        ],
    )

    assert (
        identity_linker_module._oblique_dimension_projection_relations(
            capture,
            {
                "E_EXTENSION": "F_EXTENSION",
                "E_OBLIQUE_SUPPORT": "F_OBLIQUE",
            },
        )
        == []
    )


def test_physical_oblique_profile_items_merge_supportless_exterior_crop_duplicates():
    observations = [
        {
            "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
            "schema": "1.0",
            "items": [
                {
                    "id": "OBLIQUE_R1",
                    "region_id": "R1",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "supporting_profile_entity_ids": [],
                    "supporting_profile_constant_axes": [],
                    "support_status": "unresolved",
                    "source_ids": ["structural:R1", "hybrid:oblique-line:0"],
                    "one_sided_boundary_candidate": True,
                    "exterior_boundary_candidate": True,
                },
                {
                    "id": "OBLIQUE_R2",
                    "region_id": "R2",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "supporting_profile_entity_ids": [],
                    "supporting_profile_constant_axes": [],
                    "support_status": "unresolved",
                    "source_ids": ["structural:R2", "hybrid:oblique-line:0"],
                    "one_sided_boundary_candidate": True,
                    "exterior_boundary_candidate": True,
                },
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]

    items = identity_linker_module._physical_rotational_oblique_profile_items(
        observations, {}
    )

    assert len(items) == 1
    item = items[0]
    assert item["region_ids"] == ["R1", "R2"]
    assert item["supporting_physical_feature_ids"] == []
    assert item["supporting_physical_edges"] == []
    assert item["connection_kind"] == (
        "exterior_non_orthogonal_boundary_fragment"
    )
    assert item["engineering_coordinate_inferred_from_pixels"] is False
    assert item["pixel_geometry_used_for_topology_only"] is True


def test_physical_oblique_fragment_attaches_to_one_matching_rotational_topology():
    topology = [
        {
            "region_id": "PHYSICAL_MAIN",
            "region_ids": ["R1", "R2"],
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "component_index": 0,
            "edges": [],
            "junctions": [],
        }
    ]
    fragment = {
        "id": "PHYSICAL_OBLIQUE_TEST",
        "region_ids": ["R1", "R2"],
        "view_kind": "front",
        "plane": "XZ",
        "rotation_axis": "Z",
        "supporting_physical_feature_ids": ["F_SUPPORT"],
        "supporting_physical_edges": [
            {
                "physical_feature_id": "F_SUPPORT",
                "constant_axis": "X",
                "boundary_target": "feature:F_SUPPORT.boundary.x",
            }
        ],
        "connection_kind": (
            "one_sided_non_orthogonal_boundary_continuation"
        ),
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }

    attached = identity_linker_module._attach_physical_oblique_fragments(
        topology,
        [fragment],
    )

    assert attached[0]["non_orthogonal_fragments"] == [fragment]
    assert "endpoints_px" not in repr(attached[0]["non_orthogonal_fragments"])
    assert "angle_deg" not in repr(attached[0]["non_orthogonal_fragments"])


def test_physical_oblique_fragment_fails_closed_on_ambiguous_topology_owner():
    topology = [
        {
            "region_id": "PHYSICAL_A",
            "region_ids": ["R1", "R2"],
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "component_index": 0,
        },
        {
            "region_id": "PHYSICAL_B",
            "region_ids": ["R2"],
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "component_index": 0,
        },
    ]
    fragment = {
        "id": "PHYSICAL_OBLIQUE_TEST",
        "region_ids": ["R2"],
        "view_kind": "front",
        "plane": "XZ",
        "rotation_axis": "Z",
    }

    attached = identity_linker_module._attach_physical_oblique_fragments(
        topology,
        [fragment],
    )

    assert all("non_orthogonal_fragments" not in item for item in attached)


def test_rotational_topology_keeps_disjoint_physical_items_separate():
    items = [
        {
            "region_id": "R1",
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "component_index": 0,
            "edges": [
                {
                    "ref": "R1.A",
                    "physical_feature_id": "F_A",
                    "constant_axis": "X",
                    "boundary_target": "feature:F_A.boundary.x",
                }
            ],
            "junctions": [],
        },
        {
            "region_id": "R2",
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "component_index": 0,
            "edges": [
                {
                    "ref": "R2.B",
                    "physical_feature_id": "F_B",
                    "constant_axis": "X",
                    "boundary_target": "feature:F_B.boundary.x",
                }
            ],
            "junctions": [],
        },
    ]

    merged = identity_linker_module._merge_physical_rotational_topology_items(items)

    assert [item["region_id"] for item in merged] == ["R1", "R2"]


def test_rotational_profile_topology_materializes_otherwise_orphan_profile_edge():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_ROT",
                view_id="VF",
                shape="profile",
                source_ids=["hybrid:profile-edge:R1.ROT"],
                required_for_modeling=False,
            )
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "R1.ROT",
                                "profile_entity_id": "E_ROT",
                                "source_orientation": "vertical",
                                "constant_axis": "X",
                            }
                        ],
                        "junctions": [],
                        "source_ids": ["SRC_ROTATIONAL_PROFILE"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )

    linked = link_reader_capture(capture)

    assert "E_ROT" in linked.entity_to_feature
    assert linked.report["ignored_orphan_profiles"] == 0
    ledger = next(
        item
        for item in linked.evidence.observations
        if item.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    edge = ledger["items"][0]["edges"][0]
    feature_id = linked.entity_to_feature["E_ROT"]
    assert edge["physical_feature_id"] == feature_id
    assert edge["boundary_target"] == f"feature:{feature_id}.boundary.x"


def test_rotational_profile_topology_does_not_materialize_edge_without_strict_contract():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=80,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_ROT",
                view_id="VF",
                shape="profile",
                source_ids=["hybrid:profile-edge:R1.ROT"],
                required_for_modeling=False,
            )
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "R1.ROT",
                                "profile_entity_id": "E_ROT",
                                "source_orientation": "vertical",
                                "constant_axis": "X",
                            }
                        ],
                        "junctions": [],
                        "source_ids": ["SRC_ROTATIONAL_PROFILE"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": False,
            }
        ],
    )

    linked = link_reader_capture(capture)

    assert "E_ROT" not in linked.entity_to_feature
    assert linked.report["ignored_orphan_profiles"] == 1


def test_rotational_profile_topology_maps_capture_edges_to_physical_boundary_targets():
    capture = _projected_profile_bridge_capture()
    capture.observations.append(
        {
            "kind": "hybrid_rotational_profile_topology_ledger",
            "schema": "1.0",
            "items": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "component_index": 0,
                    "edges": [
                        {
                            "ref": "R1.LEFT",
                            "profile_entity_id": "E_LEFT",
                            "source_orientation": "vertical",
                            "constant_axis": "X",
                        }
                    ],
                    "junctions": [],
                    "source_ids": ["SRC_ROTATIONAL_PROFILE"],
                    "basis": (
                        "established_rotational_symmetry_plus_"
                        "structural_profile_connectivity"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                }
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    )

    linked = link_reader_capture(capture)

    ledger = next(
        item
        for item in linked.evidence.observations
        if item.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    edge = ledger["items"][0]["edges"][0]
    feature_id = linked.entity_to_feature["E_LEFT"]
    assert edge["physical_feature_id"] == feature_id
    assert edge["boundary_target"] == f"feature:{feature_id}.boundary.x"
    assert edge["profile_entity_id"] == "E_LEFT"
    assert edge["constant_axis"] == "X"


def test_rotational_profile_topology_does_not_invent_target_without_physical_identity():
    capture = _projected_profile_bridge_capture()
    capture.observations.append(
        {
            "kind": "hybrid_rotational_profile_topology_ledger",
            "schema": "1.0",
            "items": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "component_index": 0,
                    "edges": [
                        {
                            "ref": "R1.UNKNOWN",
                            "profile_entity_id": "E_NOT_LINKED",
                            "source_orientation": "vertical",
                            "constant_axis": "X",
                        }
                    ],
                    "junctions": [],
                    "source_ids": ["SRC_ROTATIONAL_PROFILE"],
                    "basis": (
                        "established_rotational_symmetry_plus_"
                        "structural_profile_connectivity"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                }
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    )

    linked = link_reader_capture(capture)

    ledger = next(
        item
        for item in linked.evidence.observations
        if item.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    edge = ledger["items"][0]["edges"][0]
    assert "physical_feature_id" not in edge
    assert "boundary_target" not in edge


def test_projected_profile_bridge_resolves_overall_to_profile_level():
    capture = _projected_profile_bridge_capture()

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_PROJECTED"
    ]
    relation = next(
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    )
    assert relation.kind == "edge_offset"
    assert relation.from_side == "min"
    assert relation.value == 28
    assert relation.targets[0].endswith(".boundary.z")
    assert relation.metadata["basis"] == (
        "dimension_endpoint_resolved_by_projected_profile_level"
    )
    assert relation.metadata["engineering_coordinate_inferred_from_pixels"] is False

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert resolution.values[relation.targets[0]] == 28.0
    draft = build_semantic_draft(compiled, resolution)
    reference = next(
        item for item in draft["features"]
        if item.get("boundary", {}).get("z") == 28.0
    )
    assert reference["type"] == "reference_boundary"


def test_projected_profile_bridge_resolves_symmetric_profile_pair():
    capture = _projected_profile_bridge_capture(symmetric=True)

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_PROJECTED"
    ]
    distance = next(
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    )
    assert distance.kind == "coordinate_distance"
    assert distance.direction == 1
    assert distance.value == 60
    assert all(target.endswith(".boundary.x") for target in distance.targets)

    anchors = [
        item for item in linked.evidence.relations
        if item.id.startswith("R_PROJECTED_PROFILE_SYMMETRY_")
    ]
    assert {item.from_side for item in anchors} == {"min", "max"}
    assert {item.value for item in anchors} == {20.0}

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert resolution.values[distance.targets[0]] == 20.0
    assert resolution.values[distance.targets[1]] == 80.0
    assert resolution.ok


def test_projected_profile_bridge_mirrors_one_proven_profile_level_from_symmetry():
    capture = _projected_profile_bridge_capture(
        symmetric=True,
        one_sided=True,
    )

    linked = link_reader_capture(capture)

    assert not [
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("capture_dimension_id") == "D_PROJECTED"
    ]
    distance = next(
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    )
    assert distance.kind == "coordinate_distance"
    assert distance.direction == 1
    assert distance.value == 60
    assert distance.targets[0].endswith(".boundary.x")
    assert distance.targets[1].startswith(
        "constraints.symmetric_profile_levels."
    )
    assert distance.metadata["basis"] == (
        "overall_center_symmetric_projected_profile_level"
    )
    assert distance.metadata["matched_projected_profile_endpoint_index"] == 0

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    assert resolution.values[distance.targets[0]] == 20.0
    assert resolution.values[distance.targets[1]] == 80.0
    draft = build_semantic_draft(compiled, resolution)
    mirror_id = distance.targets[1].split(".")[2]
    assert (
        draft["constraints"]["symmetric_profile_levels"][mirror_id]["x"]
        == 30.0
    )
    assert resolution.ok


def test_projected_profile_bridge_keeps_one_sided_level_unresolved_without_symmetry():
    capture = _projected_profile_bridge_capture(
        symmetric=True,
        one_sided=True,
    )
    capture.observations = [
        observation
        for observation in capture.observations
        if observation.get("kind") != "hybrid_symmetric_dimension_pair_ledger"
    ]

    linked = link_reader_capture(capture)

    assert not [
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_PROJECTED"
        for item in linked.evidence.unresolved_evidence
    )


def test_projected_profile_bridge_rejects_multiple_physical_boundary_targets():
    capture = _projected_profile_bridge_capture(
        symmetric=True,
        ambiguous_profile_target=True,
    )

    linked = link_reader_capture(capture)

    assert not [
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_PROJECTED"
        for item in linked.evidence.unresolved_evidence
    )


def test_projected_profile_bridge_never_overrides_ambiguous_owner():
    capture = _projected_profile_bridge_capture(
        endpoint_kind="ambiguous_owner",
    )

    linked = link_reader_capture(capture)

    assert not [
        item for item in linked.evidence.relations
        if item.id == "D_PROJECTED"
    ]
    assert any(
        item.get("capture_dimension_id") == "D_PROJECTED"
        and "ambiguous_owner" in item.get("endpoint_unresolved_kinds", [])
        for item in linked.evidence.unresolved_evidence
    )
