from __future__ import annotations

import importlib.util
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    DatumAlignmentEvidence,
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


def test_real_shkss20_40_first_pass_resolves_only_evidence_backed_geometry():
    """Regression from the real SHKSS20-40 drawing.

    The drawing explicitly supports:
    - front circular main bore -> axis Y
    - side concentric clamp projection -> axis X
    - bottom datum -> main-bore center Z = 40
    - main-bore center -> clamp center Z spacing = 18 upward
    - overall max Y -> clamp center = 8
    - overall max Y -> mounting-hole projected center = 24
    - mounting-hole X center-to-center spacing = 24

    It does NOT, by those dimensions alone, anchor the pair's absolute X
    coordinates. The resolver must leave those X coordinates unresolved rather
    than silently choosing +/-12.
    """

    main_z = "feature:F_MAIN_HOLE.centerline.z"
    clamp_z = "feature:F_CLAMP.centerline.z"
    clamp_y = "feature:F_CLAMP.centerline.y"
    mount_y = "feature:F_MOUNT_PAIR.explicit_centers.0.1"
    mount_x0 = "feature:F_MOUNT_PAIR.explicit_centers.0.0"
    mount_x1 = "feature:F_MOUNT_PAIR.explicit_centers.1.0"

    graph = EvidenceGraph(
        overall_dimensions=_overall_dimensions(),
        views=[
            ViewEvidence(id="V_FRONT_REAL", kind="front"),
            ViewEvidence(id="V_SIDE_REAL", kind="side"),
        ],
        projections=[
            ProjectionEvidence(
                id="P_MAIN_FRONT_REAL",
                feature_id="F_MAIN_HOLE",
                view_id="V_FRONT_REAL",
                shape="circle",
                source_ids=["REAL_SHKSS_MAIN_CIRCLE"],
            ),
            ProjectionEvidence(
                id="P_CLAMP_SIDE_REAL",
                feature_id="F_CLAMP",
                view_id="V_SIDE_REAL",
                shape="concentric_circles",
                source_ids=["REAL_SHKSS_CLAMP_CONCENTRIC"],
            ),
        ],
        dimensions=[
            *_overall_dimension_observations(),
            DimensionObservation(
                id="D_REAL_MAIN_Z40",
                value=40,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="feature_center", target=main_z),
                ],
                source_ids=["REAL_SHKSS_40_PLUS_MINUS_002"],
            ),
            DimensionObservation(
                id="D_REAL_CLAMP_Z18",
                value=18,
                axis="Z",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=main_z),
                    DimensionEndpoint(role="feature_center", target=clamp_z),
                ],
                source_ids=["REAL_SHKSS_18_CENTER_DISTANCE"],
            ),
            DimensionObservation(
                id="D_REAL_CLAMP_Y8",
                value=8,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=clamp_y),
                ],
                source_ids=["REAL_SHKSS_8_FROM_RIGHT_EDGE"],
            ),
            DimensionObservation(
                id="D_REAL_MOUNT_Y24",
                value=24,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=mount_y),
                ],
                source_ids=["REAL_SHKSS_24_FROM_RIGHT_EDGE"],
            ),
            DimensionObservation(
                id="D_REAL_MOUNT_X24",
                value=24,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=mount_x0),
                    DimensionEndpoint(role="feature_center", target=mount_x1),
                ],
                source_ids=["REAL_SHKSS_24_CENTER_SPACING"],
            ),
        ],
        required_targets=[
            main_z,
            clamp_z,
            clamp_y,
            mount_y,
            mount_x0,
            mount_x1,
        ],
    )

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)

    main_axis = next(
        item
        for item in compiled.direct_values
        if item.target == "feature:F_MAIN_HOLE.axis"
    )
    clamp_axis = next(
        item
        for item in compiled.direct_values
        if item.target == "feature:F_CLAMP.axis"
    )

    assert main_axis.value == "Y"
    assert clamp_axis.value == "X"
    assert result.values[main_z] == 40
    assert result.values[clamp_z] == 58
    assert result.values[clamp_y] == 8
    assert result.values[mount_y] == -8

    assert mount_x0 not in result.values
    assert mount_x1 not in result.values
    assert not result.ok
    unresolved_targets = {
        target
        for item in result.unresolved
        for target in item.get("targets", [])
    }
    assert mount_x0 in unresolved_targets
    assert mount_x1 in unresolved_targets


def test_real_shwts20_40_first_pass_resolves_supported_geometry_and_blocks_unanchored_x():
    """Regression from the real SHWTS20-40 external-dimension drawing."""

    main_z = "feature:F_MAIN_HOLE.centerline.z"
    mount_x0 = "feature:F_MOUNT_PAIR.explicit_centers.0.0"
    mount_x1 = "feature:F_MOUNT_PAIR.explicit_centers.1.0"
    mount_y0 = "feature:F_MOUNT_PAIR.explicit_centers.0.1"
    mount_y1 = "feature:F_MOUNT_PAIR.explicit_centers.1.1"

    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=75, width_y=32, height_z=55),
        views=[
            ViewEvidence(id="V_SHWTS_FRONT", kind="front"),
            ViewEvidence(id="V_SHWTS_SIDE", kind="side"),
            ViewEvidence(id="V_SHWTS_TOP", kind="top"),
        ],
        projections=[
            ProjectionEvidence(
                id="P_SHWTS_MAIN_FRONT",
                feature_id="F_MAIN_HOLE",
                view_id="V_SHWTS_FRONT",
                shape="circle",
                source_ids=["REAL_SHWTS_MAIN_BORE"],
            ),
            ProjectionEvidence(
                id="P_SHWTS_M6_SIDE",
                feature_id="F_M6",
                view_id="V_SHWTS_SIDE",
                shape="concentric_circles",
                source_ids=["REAL_SHWTS_M6_END_VIEW"],
            ),
            ProjectionEvidence(
                id="P_SHWTS_MOUNT_TOP",
                feature_id="F_MOUNT_PAIR",
                view_id="V_SHWTS_TOP",
                shape="concentric_circles",
                source_ids=["REAL_SHWTS_COUNTERBORE_TOP"],
            ),
        ],
        dimensions=[
            DimensionObservation(
                id="D_SHWTS_OVERALL_X75",
                value=75,
                axis="X",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="D_SHWTS_OVERALL_Y32",
                value=32,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="D_SHWTS_OVERALL_Z55",
                value=55,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="D_SHWTS_MAIN_Z40",
                value=40,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="feature_center", target=main_z),
                ],
                source_ids=["REAL_SHWTS_BOTTOM_TO_MAIN_CENTER_40"],
            ),
            DimensionObservation(
                id="D_SHWTS_MOUNT_Y17_A",
                value=17,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=mount_y0),
                ],
                source_ids=["REAL_SHWTS_TOP_EDGE_TO_MOUNT_ROW_17"],
            ),
            DimensionObservation(
                id="D_SHWTS_MOUNT_Y17_B",
                value=17,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=mount_y1),
                ],
                source_ids=["REAL_SHWTS_TOP_EDGE_TO_MOUNT_ROW_17"],
            ),
            DimensionObservation(
                id="D_SHWTS_MOUNT_X62",
                value=62,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=mount_x0),
                    DimensionEndpoint(role="feature_center", target=mount_x1),
                ],
                source_ids=["REAL_SHWTS_MOUNT_CENTER_SPACING_62"],
            ),
        ],
        direct_values=[
            DirectValueEvidence(
                id="S_SHWTS_MAIN_D",
                target="feature:F_MAIN_HOLE.diameter",
                value=20,
                source_ids=["REAL_SHWTS_D20_H7"],
            ),
            DirectValueEvidence(
                id="S_SHWTS_M6_SPEC",
                target="feature:F_M6.spec",
                value="M6",
                source_ids=["REAL_SHWTS_M6_DEPTH12"],
            ),
            DirectValueEvidence(
                id="S_SHWTS_M6_DEPTH",
                target="feature:F_M6.depth",
                value=12,
                source_ids=["REAL_SHWTS_M6_DEPTH12"],
            ),
            DirectValueEvidence(
                id="S_SHWTS_MOUNT_D",
                target="feature:F_MOUNT_PAIR.diameter",
                value=6.5,
                source_ids=["REAL_SHWTS_2_D6_5_THRU"],
            ),
            DirectValueEvidence(
                id="S_SHWTS_CB_D",
                target="feature:F_MOUNT_PAIR.counterbore_diameter",
                value=11,
                source_ids=["REAL_SHWTS_CB_D11_DEPTH6_5"],
            ),
            DirectValueEvidence(
                id="S_SHWTS_CB_DEPTH",
                target="feature:F_MOUNT_PAIR.counterbore_depth",
                value=6.5,
                source_ids=["REAL_SHWTS_CB_D11_DEPTH6_5"],
            ),
        ],
        required_targets=[
            main_z,
            mount_x0,
            mount_x1,
            mount_y0,
            mount_y1,
        ],
    )

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)

    axes = {item.target: item.value for item in compiled.direct_values if item.target.endswith(".axis")}
    assert axes["feature:F_MAIN_HOLE.axis"] == "Y"
    assert axes["feature:F_M6.axis"] == "X"
    assert axes["feature:F_MOUNT_PAIR.axis"] == "Z"

    assert result.values[main_z] == 40
    assert result.values[mount_y0] == -1
    assert result.values[mount_y1] == -1

    assert mount_x0 not in result.values
    assert mount_x1 not in result.values
    assert not result.ok
    unresolved_targets = {
        target
        for item in result.unresolved
        for target in item.get("targets", [])
    }
    assert mount_x0 in unresolved_targets
    assert mount_x1 in unresolved_targets


def test_real_mounting_plate_first_pass_solves_edge_anchored_x_but_keeps_y_unresolved():
    """Regression from the mounting-plate drawing.

    The 120 overall X dimension plus explicit 10 mm edge-to-hole-center
    dimensions uniquely anchors the two side-hole X coordinates. The drawing
    evidence supplied here intentionally does not claim a Y ordinate, so Y
    must remain unresolved instead of being inferred from visual symmetry.
    """

    left_x = "feature:F_SIDE_HOLES.explicit_centers.0.0"
    right_x = "feature:F_SIDE_HOLES.explicit_centers.1.0"
    left_y = "feature:F_SIDE_HOLES.explicit_centers.0.1"
    right_y = "feature:F_SIDE_HOLES.explicit_centers.1.1"

    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=120, width_y=80, height_z=32),
        views=[ViewEvidence(id="V_PLATE_TOP", kind="top")],
        projections=[
            ProjectionEvidence(
                id="P_PLATE_SIDE_HOLES",
                feature_id="F_SIDE_HOLES",
                view_id="V_PLATE_TOP",
                shape="circle",
                source_ids=["REAL_PLATE_TWO_D10_CIRCLES"],
            ),
            ProjectionEvidence(
                id="P_PLATE_CENTER_HOLE",
                feature_id="F_CENTER_HOLE",
                view_id="V_PLATE_TOP",
                shape="circle",
                source_ids=["REAL_PLATE_CENTER_D12"],
            ),
        ],
        datum_alignments=[
            DatumAlignmentEvidence(
                id="A_PLATE_LEFT_Y_CENTER",
                target=left_y,
                axis="Y",
                source_ids=["REAL_PLATE_HORIZONTAL_OVERALL_CENTERLINE"],
            ),
            DatumAlignmentEvidence(
                id="A_PLATE_RIGHT_Y_CENTER",
                target=right_y,
                axis="Y",
                source_ids=["REAL_PLATE_HORIZONTAL_OVERALL_CENTERLINE"],
            ),
        ],
        dimensions=[
            DimensionObservation(
                id="D_PLATE_X120",
                value=120,
                axis="X",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="D_PLATE_Y80",
                value=80,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="D_PLATE_LEFT_X10",
                value=10,
                axis="X",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="feature_center", target=left_x),
                ],
                source_ids=["REAL_PLATE_LEFT_EDGE_TO_HOLE_10"],
            ),
            DimensionObservation(
                id="D_PLATE_RIGHT_X10",
                value=10,
                axis="X",
                endpoints=[
                    DimensionEndpoint(role="overall_max"),
                    DimensionEndpoint(role="feature_center", target=right_x),
                ],
                source_ids=["REAL_PLATE_RIGHT_EDGE_TO_HOLE_10"],
            ),
            DimensionObservation(
                id="D_PLATE_HOLE_SPACING100",
                value=100,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="feature_center", target=left_x),
                    DimensionEndpoint(role="feature_center", target=right_x),
                ],
                source_ids=["REAL_PLATE_HOLE_CENTER_SPACING_100"],
            ),
        ],
        direct_values=[
            DirectValueEvidence(
                id="S_PLATE_SIDE_D",
                target="feature:F_SIDE_HOLES.diameter",
                value=10,
                source_ids=["REAL_PLATE_2_D10"],
            ),
            DirectValueEvidence(
                id="S_PLATE_SIDE_COUNT",
                target="feature:F_SIDE_HOLES.count",
                value=2,
                source_ids=["REAL_PLATE_2_D10"],
            ),
            DirectValueEvidence(
                id="S_PLATE_BOSS_D",
                target="feature:F_BOSS.diameter",
                value=30,
                source_ids=["REAL_PLATE_BOSS_D30"],
            ),
            DirectValueEvidence(
                id="S_PLATE_CENTER_D",
                target="feature:F_CENTER_HOLE.diameter",
                value=12,
                source_ids=["REAL_PLATE_CENTER_D12"],
            ),
            DirectValueEvidence(
                id="S_PLATE_BASE_T",
                target="feature:F_BASE.thickness",
                value=12,
                source_ids=["REAL_PLATE_BASE_T12"],
            ),
            DirectValueEvidence(
                id="S_PLATE_BOSS_H",
                target="feature:F_BOSS.height",
                value=20,
                source_ids=["REAL_PLATE_BOSS_H20"],
            ),
            DirectValueEvidence(
                id="S_PLATE_SLOT_L",
                target="feature:F_SLOT.length",
                value=40,
                source_ids=["REAL_PLATE_SLOT_L40"],
            ),
            DirectValueEvidence(
                id="S_PLATE_SLOT_W",
                target="feature:F_SLOT.width",
                value=12,
                source_ids=["REAL_PLATE_SLOT_W12"],
            ),
        ],
        required_targets=[left_x, right_x, left_y, right_y],
    )

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)

    axis = next(
        item.value
        for item in compiled.direct_values
        if item.target == "feature:F_SIDE_HOLES.axis"
    )
    assert axis == "Z"
    assert result.values[left_x] == -50
    assert result.values[right_x] == 50

    assert result.values[left_y] == 0
    assert result.values[right_y] == 0
    assert result.ok


def test_overall_center_datum_alignment_compiles_xy_to_zero_and_z_to_half_height():
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=120, width_y=80, height_z=32),
        datum_alignments=[
            DatumAlignmentEvidence(
                id="A_CENTER_X",
                target="feature:F_A.centerline.x",
                axis="X",
                source_ids=["CENTERLINE_X"],
            ),
            DatumAlignmentEvidence(
                id="A_CENTER_Y",
                target="feature:F_A.centerline.y",
                axis="Y",
                source_ids=["CENTERLINE_Y"],
            ),
            DatumAlignmentEvidence(
                id="A_CENTER_Z",
                target="feature:F_A.centerline.z",
                axis="Z",
                source_ids=["CENTER_PLANE_Z"],
            ),
        ],
    )

    compiled = compile_evidence_graph(graph)
    values = {item.target: item.value for item in compiled.direct_values}

    assert values["feature:F_A.centerline.x"] == 0
    assert values["feature:F_A.centerline.y"] == 0
    assert values["feature:F_A.centerline.z"] == 16


def test_datum_alignment_axis_mismatch_is_unresolved_not_silently_reinterpreted():
    target = "feature:F_A.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=120, width_y=80, height_z=32),
        datum_alignments=[
            DatumAlignmentEvidence(
                id="A_BAD_AXIS",
                target=target,
                axis="Y",
                source_ids=["BAD_CENTERLINE"],
            )
        ],
        required_targets=[target],
    )

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)

    assert not any(item.target == target for item in compiled.direct_values)
    assert not result.ok
    assert any(item.get("target") == target for item in compiled.unresolved_evidence)
