from __future__ import annotations

import importlib.util
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    ViewEvidence,
    build_semantic_draft,
    compile_evidence_graph,
    resolve_evidence_graph,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
SPEC = importlib.util.spec_from_file_location("gate_a_runner_compiler", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def _overall_dimensions():
    return OverallDimensions(length_x=40, width_y=32, height_z=66)


def _overall_dimension_observations():
    return [
        DimensionObservation(
            id="D_OVERALL_X",
            value=40,
            axis="X",
            endpoints=[
                DimensionEndpoint(role="overall_min"),
                DimensionEndpoint(role="overall_max"),
            ],
        ),
        DimensionObservation(
            id="D_OVERALL_Y",
            value=32,
            axis="Y",
            endpoints=[
                DimensionEndpoint(role="overall_min"),
                DimensionEndpoint(role="overall_max"),
            ],
        ),
        DimensionObservation(
            id="D_OVERALL_Z",
            value=66,
            axis="Z",
            endpoints=[
                DimensionEndpoint(role="overall_min"),
                DimensionEndpoint(role="overall_max"),
            ],
        ),
    ]


def test_front_circle_compiles_to_axis_y():
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        views=[ViewEvidence(id="V_FRONT", kind="front")],
        projections=[
            ProjectionEvidence(
                id="P_MAIN",
                feature_id="F_MAIN",
                view_id="V_FRONT",
                shape="circle",
            )
        ],
    )

    compiled = compile_evidence_graph(graph)

    axis = next(
        item for item in compiled.direct_values
        if item.target == "feature:F_MAIN.axis"
    )
    assert axis.value == "Y"
    assert "P_MAIN" in axis.source_ids


def test_side_circle_compiles_to_axis_x():
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        views=[ViewEvidence(id="V_SIDE", kind="side")],
        projections=[
            ProjectionEvidence(
                id="P_M6",
                feature_id="F_M6",
                view_id="V_SIDE",
                shape="concentric_circles",
            )
        ],
    )

    compiled = compile_evidence_graph(graph)

    axis = next(
        item for item in compiled.direct_values
        if item.target == "feature:F_M6.axis"
    )
    assert axis.value == "X"


def test_conflicting_circular_views_do_not_choose_an_axis():
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        views=[
            ViewEvidence(id="V_FRONT", kind="front"),
            ViewEvidence(id="V_SIDE", kind="side"),
        ],
        projections=[
            ProjectionEvidence(
                id="P1",
                feature_id="F_BAD",
                view_id="V_FRONT",
                shape="circle",
            ),
            ProjectionEvidence(
                id="P2",
                feature_id="F_BAD",
                view_id="V_SIDE",
                shape="circle",
            ),
        ],
    )

    compiled = compile_evidence_graph(graph)

    assert not any(
        item.target == "feature:F_BAD.axis"
        for item in compiled.direct_values
    )
    assert any(
        item.get("target") == "feature:F_BAD.axis"
        for item in compiled.unresolved_evidence
    )


def test_max_edge_to_center_dimension_compiles_to_edge_offset_and_resolves_minus_8():
    target = "feature:F_MOUNT.centerline.y"
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        dimensions=[
            *_overall_dimension_observations(),
            DimensionObservation(
                id="D_MOUNT_Y24",
                value=24,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=target),
                ],
            ),
        ],
        required_targets=[target],
    )

    compiled = compile_evidence_graph(graph)
    relation = next(item for item in compiled.relations if item.id == "D_MOUNT_Y24")
    result = resolve_evidence_graph(compiled)

    assert relation.kind == "edge_offset"
    assert relation.from_side == "max"
    assert result.values[target] == -8


def test_same_feature_centers_compile_to_center_spacing():
    x0 = "feature:F_PAIR.explicit_centers.0.0"
    x1 = "feature:F_PAIR.explicit_centers.1.0"
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        dimensions=[
            DimensionObservation(
                id="D_PAIR_SPACING",
                value=20,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=x0),
                    DimensionEndpoint(role="feature_center", target=x1),
                ],
            )
        ],
    )

    compiled = compile_evidence_graph(graph)

    relation = compiled.relations[0]
    assert relation.kind == "center_spacing"
    assert relation.direction == 1


def test_different_feature_centers_compile_to_center_distance():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        dimensions=[
            DimensionObservation(
                id="D_AB",
                value=20,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=a),
                    DimensionEndpoint(role="feature_center", target=b),
                ],
            )
        ],
    )

    compiled = compile_evidence_graph(graph)

    assert compiled.relations[0].kind == "center_distance"


def test_raw_evidence_compiles_resolves_and_passes_existing_gate_a():
    z = "feature:F_MAIN.centerline.z"
    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        views=[ViewEvidence(id="V_FRONT", kind="front")],
        projections=[
            ProjectionEvidence(
                id="P_MAIN_CIRCLE",
                feature_id="F_MAIN",
                view_id="V_FRONT",
                shape="circle",
            )
        ],
        dimensions=[
            *_overall_dimension_observations(),
            DimensionObservation(
                id="D_MAIN_Z40",
                value=40,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="feature_center", target=z),
                ],
            ),
        ],
        direct_values=[
            DirectValueEvidence(
                id="S_MAIN_KIND",
                target="feature:F_MAIN.type",
                value="through_hole",
            ),
            DirectValueEvidence(
                id="S_MAIN_X",
                target="feature:F_MAIN.centerline.x",
                value=0,
            ),
            DirectValueEvidence(
                id="S_MAIN_D",
                target="feature:F_MAIN.diameter",
                value=20,
            ),
            DirectValueEvidence(
                id="S_MAIN_N",
                target="feature:F_MAIN.count",
                value=1,
            ),
        ],
        required_targets=[z],
    )

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, result)

    feature = draft["features"][0]
    assert feature["axis"] == "Y"
    assert feature["centerline"] == {"x": 0, "z": 40}
    assert result.ok
    assert R.check_drawing_json(draft) == []
