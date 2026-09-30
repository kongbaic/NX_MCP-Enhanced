from __future__ import annotations

import importlib.util
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
    build_semantic_draft,
    resolve_evidence_graph,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
SPEC = importlib.util.spec_from_file_location("gate_a_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def _overall_values(length_x=40, width_y=32, height_z=66):
    return [
        DirectValueEvidence(
            id="S_OVERALL_X",
            target="overall_dimensions.length_x",
            value=length_x,
            source_ids=["ANN_OVERALL_X"],
        ),
        DirectValueEvidence(
            id="S_OVERALL_Y",
            target="overall_dimensions.width_y",
            value=width_y,
            source_ids=["ANN_OVERALL_Y"],
        ),
        DirectValueEvidence(
            id="S_OVERALL_Z",
            target="overall_dimensions.height_z",
            value=height_z,
            source_ids=["ANN_OVERALL_Z"],
        ),
    ]


def test_resolver_to_semantic_draft_passes_existing_gate_a_for_bottom_offset():
    target = "feature:F_MAIN_HOLE.centerline.z"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_MAIN_KIND",
                target="feature:F_MAIN_HOLE.type",
                value="through_hole",
            ),
            DirectValueEvidence(
                id="S_MAIN_AXIS",
                target="feature:F_MAIN_HOLE.axis",
                value="Y",
            ),
            DirectValueEvidence(
                id="S_MAIN_X",
                target="feature:F_MAIN_HOLE.centerline.x",
                value=0,
            ),
            DirectValueEvidence(
                id="S_MAIN_D",
                target="feature:F_MAIN_HOLE.diameter",
                value=20,
            ),
            DirectValueEvidence(
                id="S_MAIN_COUNT",
                target="feature:F_MAIN_HOLE.count",
                value=1,
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_MAIN_Z40",
                kind="edge_offset",
                axis="Z",
                from_side="min",
                value=40,
                targets=[target],
                source_ids=["ANN_BOTTOM_TO_CENTER_40"],
            )
        ],
        required_targets=[target],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["features"][0]["centerline"]["z"] == 40
    assert draft["dimension_closure"] == {"status": "closed"}
    assert R.check_drawing_json(draft) == []


def test_mount_pair_resolves_edge_offsets_and_signed_spacing_then_passes_gate_a():
    x0 = "feature:F_PAIR.explicit_centers.0.0"
    x1 = "feature:F_PAIR.explicit_centers.1.0"
    y0 = "feature:F_PAIR.explicit_centers.0.1"
    y1 = "feature:F_PAIR.explicit_centers.1.1"

    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_PAIR_KIND",
                target="feature:F_PAIR.type",
                value="through_hole",
            ),
            DirectValueEvidence(
                id="S_PAIR_AXIS",
                target="feature:F_PAIR.axis",
                value="Z",
            ),
            DirectValueEvidence(
                id="S_PAIR_D",
                target="feature:F_PAIR.diameter",
                value=6.6,
            ),
            DirectValueEvidence(
                id="S_PAIR_COUNT",
                target="feature:F_PAIR.count",
                value=2,
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_PAIR_X0",
                kind="edge_offset",
                axis="X",
                from_side="min",
                value=10,
                targets=[x0],
            ),
            RelationEvidence(
                id="S_PAIR_SPACING",
                kind="center_spacing",
                axis="X",
                value=20,
                direction=1,
                targets=[x0, x1],
            ),
            RelationEvidence(
                id="S_PAIR_Y",
                kind="edge_offset",
                axis="Y",
                from_side="max",
                value=24,
                targets=[y0, y1],
            ),
        ],
        required_targets=[x0, x1, y0, y1],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    pair = draft["features"][0]
    assert pair["explicit_centers"] == [[-10, -8], [10, -8]]
    assert result.ok
    assert any(item["target"] == x1 for item in draft["derived"])
    assert R.check_drawing_json(draft) == []


def test_alignment_propagation_is_serialized_as_derived_with_relation_ref():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(id="A_KIND", target="feature:F_A.type", value="through_hole"),
            DirectValueEvidence(id="A_AXIS", target="feature:F_A.axis", value="Z"),
            DirectValueEvidence(id="A_X", target=a, value=20),
            DirectValueEvidence(id="A_Y", target="feature:F_A.centerline.y", value=16),
            DirectValueEvidence(id="A_D", target="feature:F_A.diameter", value=5),
            DirectValueEvidence(id="A_N", target="feature:F_A.count", value=1),
            DirectValueEvidence(id="B_KIND", target="feature:F_B.type", value="through_hole"),
            DirectValueEvidence(id="B_AXIS", target="feature:F_B.axis", value="Z"),
            DirectValueEvidence(id="B_Y", target="feature:F_B.centerline.y", value=16),
            DirectValueEvidence(id="B_D", target="feature:F_B.diameter", value=5),
            DirectValueEvidence(id="B_N", target="feature:F_B.count", value=1),
        ],
        relations=[
            RelationEvidence(
                id="R_ALIGN_X",
                kind="alignment",
                axis="X",
                targets=[a, b],
                source_ids=["CENTERLINE_EVIDENCE"],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert next(item for item in draft["features"] if item["id"] == "F_B")["centerline"]["x"] == 0
    derived = next(item for item in draft["derived"] if item["target"] == b)
    assert derived["expr"] == {"target": a}
    assert derived["relation_refs"] == ["R_ALIGN_X"]
    assert R.check_drawing_json(draft) == []


def test_unsigned_spacing_stays_incomplete_and_existing_gate_a_rejects_it():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(id="A_KIND", target="feature:F_A.type", value="through_hole"),
            DirectValueEvidence(id="A_AXIS", target="feature:F_A.axis", value="Z"),
            DirectValueEvidence(id="A_X", target=a, value=-10),
            DirectValueEvidence(id="A_Y", target="feature:F_A.centerline.y", value=0),
            DirectValueEvidence(id="A_D", target="feature:F_A.diameter", value=5),
            DirectValueEvidence(id="A_N", target="feature:F_A.count", value=1),
            DirectValueEvidence(id="B_KIND", target="feature:F_B.type", value="through_hole"),
            DirectValueEvidence(id="B_AXIS", target="feature:F_B.axis", value="Z"),
            DirectValueEvidence(id="B_Y", target="feature:F_B.centerline.y", value=0),
            DirectValueEvidence(id="B_D", target="feature:F_B.diameter", value=5),
            DirectValueEvidence(id="B_N", target="feature:F_B.count", value=1),
        ],
        relations=[
            RelationEvidence(
                id="R_UNSIGNED",
                kind="center_spacing",
                axis="X",
                value=20,
                targets=[a, b],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)
    errors = R.check_drawing_json(draft)

    assert not result.ok
    assert draft["dimension_closure"] == {"status": "incomplete"}
    assert any(item.get("target") == b for item in draft["unresolved"])
    assert errors
    assert any("unresolved" in error or "dimension_closure" in error for error in errors)

def test_inferred_feature_types_emit_gate_a_provenance_writers():
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_HOLE_AXIS",
                target="feature:F_HOLE.axis",
                value="Y",
                source_ids=["ANN_HOLE_AXIS"],
            ),
            DirectValueEvidence(
                id="S_HOLE_D",
                target="feature:F_HOLE.diameter",
                value=20,
                source_ids=["ANN_HOLE_D"],
            ),
            DirectValueEvidence(
                id="S_HOLE_Z",
                target="feature:F_HOLE.centerline.z",
                value=40,
                source_ids=["ANN_HOLE_Z"],
            ),
            DirectValueEvidence(
                id="S_THREAD_AXIS",
                target="feature:F_THREAD.axis",
                value="X",
                source_ids=["ANN_THREAD_AXIS"],
            ),
            DirectValueEvidence(
                id="S_THREAD_SPEC",
                target="feature:F_THREAD.thread_spec",
                value="M6",
                source_ids=["ANN_THREAD_SPEC"],
            ),
            DirectValueEvidence(
                id="S_THREAD_DEPTH",
                target="feature:F_THREAD.thread_depth",
                value=12,
                source_ids=["ANN_THREAD_DEPTH"],
            ),
            DirectValueEvidence(
                id="S_THREAD_Z",
                target="feature:F_THREAD.centerline.z",
                value=58,
                source_ids=["ANN_THREAD_Z"],
            ),
            DirectValueEvidence(
                id="S_RECESS_AXIS",
                target="feature:F_RECESS.axis",
                value="X",
                source_ids=["ANN_RECESS_AXIS"],
            ),
            DirectValueEvidence(
                id="S_RECESS_D",
                target="feature:F_RECESS.diameter",
                value=6.6,
                source_ids=["ANN_RECESS_D"],
            ),
            DirectValueEvidence(
                id="S_RECESS_FLAG",
                target="feature:F_RECESS.recessed_hole",
                value=True,
                source_ids=["ANN_RECESS_FLAG"],
            ),
            DirectValueEvidence(
                id="S_RECESS_D2",
                target="feature:F_RECESS.recess_diameter",
                value=11,
                source_ids=["ANN_RECESS_D2"],
            ),
            DirectValueEvidence(
                id="S_RECESS_DEPTH",
                target="feature:F_RECESS.recess_depth",
                value=6.5,
                source_ids=["ANN_RECESS_DEPTH"],
            ),
            DirectValueEvidence(
                id="S_RECESS_Y",
                target="feature:F_RECESS.centerline.y",
                value=24,
                source_ids=["ANN_RECESS_Y"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_BOUNDARY_Y",
                kind="edge_offset",
                axis="Y",
                from_side="max",
                value=24,
                targets=["feature:F_BOUNDARY.boundary.y"],
                source_ids=["ANN_BOUNDARY_Y"],
            ),
        ],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    inferred = {item["id"]: item["type"] for item in draft["features"]}
    assert inferred == {
        "F_BOUNDARY": "reference_boundary",
        "F_HOLE": "hole",
        "F_RECESS": "recessed_hole",
        "F_THREAD": "threaded_hole",
    }

    type_sources = {
        item.get("target"): item
        for item in draft["source_ledger"]
        if item.get("semantic") == "feature_kind"
    }
    assert set(type_sources) == {
        "feature:F_BOUNDARY.type",
        "feature:F_HOLE.type",
        "feature:F_RECESS.type",
        "feature:F_THREAD.type",
    }
    assert all(item.get("evidence") for item in type_sources.values())
    assert all(item.get("inference_basis_targets") for item in type_sources.values())
    assert all(item.get("inference_basis_sources") for item in type_sources.values())

    errors = R.check_drawing_json(draft)
    assert not any(
        error.startswith("required geometry field lacks evidence: feature:")
        and error.endswith(".type")
        for error in errors
    )



def test_midpoint_constraint_round_trips_through_draft_and_gate_a():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_GENERIC.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="LEFT_BOUNDARY",
                target=left,
                value=20,
                source_ids=["LEFT_PROFILE"],
            ),
            DirectValueEvidence(
                id="RIGHT_BOUNDARY",
                target=right,
                value=60,
                source_ids=["RIGHT_PROFILE"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_MID_GENERIC",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
                source_ids=["SPAN_PROFILE"],
                required_for_modeling=False,
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[center] == 40.0
    assert draft["constraints"]["span_centers"]["C_GENERIC"]["x"] == -10.0
    relation = next(
        item for item in draft["source_ledger"]
        if item["id"] == "R_MID_GENERIC"
    )
    assert relation["semantic"] == "midpoint"
    assert relation["links"] == [left, center, right]
    derived = next(item for item in draft["derived"] if item["target"] == center)
    assert derived["relation_refs"] == ["R_MID_GENERIC"]
    assert R.check_drawing_json(draft) == []


def test_centered_span_constraint_round_trips_through_gate_a():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_GENERIC.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
        ],
        relations=[
            RelationEvidence(
                id="R_CENTER",
                kind="edge_offset",
                axis="X",
                from_side="min",
                value=50,
                targets=[center],
                source_ids=["CENTER_ANCHOR"],
                required_for_modeling=True,
            ),
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                direction=1,
                targets=[left, center, right],
                source_ids=["SPAN_DIMENSION"],
                required_for_modeling=False,
            ),
        ],
        required_targets=[left, right],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert result.values[left] == 40.0
    assert result.values[center] == 50.0
    assert result.values[right] == 60.0
    assert draft["constraints"]["span_centers"]["C_GENERIC"]["x"] == 0.0

    left_feature = next(
        item for item in draft["features"] if item["id"] == "F_LEFT"
    )
    right_feature = next(
        item for item in draft["features"] if item["id"] == "F_RIGHT"
    )
    assert left_feature["boundary"]["x"] == -10.0
    assert right_feature["boundary"]["x"] == 10.0

    source = next(
        item for item in draft["source_ledger"]
        if item["id"] == "R_CENTERED_SPAN"
    )
    assert source["semantic"] == "centered_span"
    assert source["value"] == 20
    assert source["direction"] == 1
    assert source["links"] == [left, center, right]
    assert R.check_drawing_json(draft) == []


def test_coordinate_distance_is_audited_as_formal_relation():
    left = "feature:F_LEFT.boundary.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="LEFT_BOUNDARY",
                target=left,
                value=20,
                source_ids=["LEFT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_COORD_DISTANCE",
                kind="coordinate_distance",
                axis="X",
                value=30,
                direction=1,
                targets=[left, right],
                source_ids=["DIMENSION"],
                required_for_modeling=True,
            )
        ],
        required_targets=[right],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[right] == 50.0
    source = next(
        item
        for item in draft["source_ledger"]
        if item["id"] == "R_COORD_DISTANCE"
    )
    assert source["semantic"] == "coordinate_distance"
    assert source["between"] == [left, right]
    assert R.check_drawing_json(draft) == []


def test_center_distance_accepts_profile_span_constraint_center():
    span_center = "constraints.span_centers.C_GENERIC.x"
    feature_center = "feature:F_HOLE.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="F_HOLE_TYPE",
                target="feature:F_HOLE.type",
                value="reference_point",
                source_ids=["REFERENCE_POINT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_SPAN_CENTER",
                kind="edge_offset",
                axis="X",
                value=30,
                from_side="min",
                targets=[span_center],
                source_ids=["SPAN_CENTER"],
                required_for_modeling=True,
            ),
            RelationEvidence(
                id="R_CENTER_DISTANCE",
                kind="center_distance",
                axis="X",
                value=20,
                direction=1,
                targets=[span_center, feature_center],
                source_ids=["CENTER_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[feature_center],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[span_center] == 30.0
    assert result.values[feature_center] == 50.0
    assert R.check_drawing_json(draft) == []


def test_symmetric_profile_level_constraint_round_trips_through_gate_a():
    profile_boundary = "feature:F_PROFILE.boundary.x"
    mirror_level = "constraints.symmetric_profile_levels.C_MIRROR.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
        ],
        relations=[
            RelationEvidence(
                id="R_PROFILE_LEFT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="min",
                targets=[profile_boundary],
                source_ids=["PROFILE_LEVEL"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_PROFILE_RIGHT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="max",
                targets=[mirror_level],
                source_ids=["MIRROR_LEVEL"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_PROFILE_DISTANCE",
                kind="coordinate_distance",
                axis="X",
                value=60,
                direction=1,
                targets=[profile_boundary, mirror_level],
                source_ids=["SYMMETRIC_PROFILE_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[profile_boundary, mirror_level],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[profile_boundary] == 20.0
    assert result.values[mirror_level] == 80.0
    assert draft["features"][0]["boundary"]["x"] == -30.0
    assert draft["features"][0]["type"] == "reference_boundary"
    assert draft["constraints"]["symmetric_profile_levels"]["C_MIRROR"]["x"] == 30.0
    assert R.check_drawing_json(draft) == []


def test_symmetric_center_constraint_round_trips_through_gate_a():
    span_center = "constraints.span_centers.C_LEFT.x"
    mirror_center = "constraints.symmetric_centers.C_RIGHT.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="F_REFERENCE_TYPE",
                target="feature:F_REFERENCE.type",
                value="reference_point",
                source_ids=["REFERENCE_POINT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_LEFT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="min",
                targets=[span_center],
                source_ids=["LEFT_CENTER"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_RIGHT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="max",
                targets=[mirror_center],
                source_ids=["RIGHT_CENTER"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_DISTANCE",
                kind="center_distance",
                axis="X",
                value=60,
                direction=1,
                targets=[span_center, mirror_center],
                source_ids=["CENTER_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[span_center, mirror_center],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[span_center] == 20.0
    assert result.values[mirror_center] == 80.0
    assert draft["constraints"]["span_centers"]["C_LEFT"]["x"] == -30.0
    assert draft["constraints"]["symmetric_centers"]["C_RIGHT"]["x"] == 30.0
    assert R.check_drawing_json(draft) == []
