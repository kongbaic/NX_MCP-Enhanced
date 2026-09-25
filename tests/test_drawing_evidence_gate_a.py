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
