from __future__ import annotations

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.metric_profile_solver import (
    MetricProfileSpec,
    solve_metric_profile,
)


def test_l_profile_max_side_solves_shkss_body_without_pixel_metric() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            coordinate_mode="overall_min",
        )
    )

    assert solution.vertices == [
        {"y": 0.0, "z": 0.0},
        {"y": 32.0, "z": 0.0},
        {"y": 32.0, "z": 66.0},
        {"y": 16.0, "z": 66.0},
        {"y": 16.0, "z": 8.0},
        {"y": 0.0, "z": 8.0},
    ]
    assert len(solution.segments) == 6
    assert solution.segments[-1] == {
        "type": "line",
        "y1": 0.0,
        "z1": 8.0,
        "y2": 0.0,
        "z2": 0.0,
    }
    assert solution.engineering_coordinate_inferred_from_pixels is False


def test_l_profile_can_emit_planner_centered_u_coordinates() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            coordinate_mode="centered_u_bottom_v",
        )
    )

    assert solution.vertices == [
        {"y": -16.0, "z": 0.0},
        {"y": 16.0, "z": 0.0},
        {"y": 16.0, "z": 66.0},
        {"y": 0.0, "z": 66.0},
        {"y": 0.0, "z": 8.0},
        {"y": -16.0, "z": 8.0},
    ]


def test_l_profile_supports_min_side_without_special_case_coordinates() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=30,
            overall_v=50,
            upright_width=10,
            base_height=5,
            upright_side="min",
        )
    )

    assert solution.vertices == [
        {"y": 0.0, "z": 0.0},
        {"y": 30.0, "z": 0.0},
        {"y": 30.0, "z": 5.0},
        {"y": 10.0, "z": 5.0},
        {"y": 10.0, "z": 50.0},
        {"y": 0.0, "z": 50.0},
    ]


@pytest.mark.parametrize(
    ("upright_width", "base_height"),
    [(32, 8), (16, 66), (40, 80)],
)
def test_invalid_l_profile_constraints_fail_closed(
    upright_width: float,
    base_height: float,
) -> None:
    with pytest.raises(ValidationError):
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=upright_width,
            base_height=base_height,
            upright_side="max",
        )


def test_build_semantic_draft_materializes_metric_profile_with_provenance() -> None:
    from nx_mcp.drawing_intelligence.draft import build_semantic_draft
    from nx_mcp.drawing_intelligence.evidence import EvidenceGraph, OverallDimensions
    from nx_mcp.drawing_intelligence.resolver import ResolutionResult

    graph = EvidenceGraph(
        schema_version="1.0",
        coordinate_system="overall_min_xyz",
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[],
        projections=[],
        dimensions=[],
        datum_alignments=[],
        direct_values=[],
        relations=[],
        required_targets=[],
        observations=[],
        unresolved_evidence=[],
    )
    resolution = ResolutionResult(
        values={},
        derivations={},
        unresolved=[],
        conflicts=[],
    )
    draft = build_semantic_draft(
        graph,
        resolution,
        metric_profile=MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            source_ids=["engineering:overall-y32-z66-upright16-base8"],
        ),
    )

    assert draft["profile"]["plane"] == "YZ"
    assert draft["profile"]["topology"] == "L"
    assert draft["profile"]["segments"][0] == {
        "type": "line",
        "y1": -16.0,
        "z1": 0.0,
        "y2": 16.0,
        "z2": 0.0,
    }
    assert draft["profile"]["segments"][3] == {
        "type": "line",
        "y1": 0.0,
        "z1": 66.0,
        "y2": 0.0,
        "z2": 8.0,
    }

    by_target = {
        item["target"]: item
        for item in draft["source_ledger"]
        if item.get("target")
    }
    assert by_target["profile.segments.0.y1"]["value"] == -16.0
    assert by_target["profile.segments.0.y1"]["solver"] == "metric_profile_solver"
    assert by_target["profile.segments.0.y1"]["evidence"] == [
        "engineering:overall-y32-z66-upright16-base8"
    ]


def test_build_semantic_draft_rejects_metric_profile_overall_mismatch() -> None:
    from nx_mcp.drawing_intelligence.draft import DraftAssemblyError, build_semantic_draft
    from nx_mcp.drawing_intelligence.evidence import EvidenceGraph, OverallDimensions
    from nx_mcp.drawing_intelligence.resolver import ResolutionResult

    graph = EvidenceGraph(
        schema_version="1.0",
        coordinate_system="overall_min_xyz",
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[],
        projections=[],
        dimensions=[],
        datum_alignments=[],
        direct_values=[],
        relations=[],
        required_targets=[],
        observations=[],
        unresolved_evidence=[],
    )
    resolution = ResolutionResult(
        values={},
        derivations={},
        unresolved=[],
        conflicts=[],
    )

    with pytest.raises(DraftAssemblyError):
        build_semantic_draft(
            graph,
            resolution,
            metric_profile=MetricProfileSpec(
                plane="YZ",
                overall_u=30,
                overall_v=66,
                upright_width=16,
                base_height=8,
                upright_side="max",
            ),
        )


def test_l_profile_supports_max_base_side() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            base_side="max",
        )
    )

    assert solution.vertices == [
        {"y": 0.0, "z": 66.0},
        {"y": 32.0, "z": 66.0},
        {"y": 32.0, "z": 0.0},
        {"y": 16.0, "z": 0.0},
        {"y": 16.0, "z": 58.0},
        {"y": 0.0, "z": 58.0},
    ]


def test_build_semantic_draft_auto_derives_metric_profile_from_topology_and_resolution() -> None:
    from nx_mcp.drawing_intelligence.draft import build_semantic_draft
    from nx_mcp.drawing_intelligence.evidence import EvidenceGraph, OverallDimensions
    from nx_mcp.drawing_intelligence.resolver import ResolutionResult

    graph = EvidenceGraph(
        schema_version="1.0",
        coordinate_system="overall_min_xyz",
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[],
        projections=[],
        dimensions=[],
        datum_alignments=[],
        direct_values=[],
        relations=[],
        required_targets=[],
        observations=[
            {
                "kind": "hybrid_profile_topology_ledger",
                "items": [
                    {
                        "region_id": "R2",
                        "plane": "YZ",
                        "topology": "L",
                        "upright_side": "max",
                        "base_side": "min",
                        "internal_u_entity_id": "E001",
                        "internal_v_entity_id": "E002",
                        "internal_u_ref": "R2.structural.vertical.002",
                        "internal_v_ref": "R2.structural.horizontal.002",
                        "outer_refs": {
                            "u_min": "R2.structural.vertical.001",
                            "u_max": "R2.structural.vertical.003",
                            "v_min": "R2.structural.horizontal.001",
                            "v_max": "R2.structural.horizontal.003",
                        },
                    }
                ],
            },
            {
                "kind": "identity_linker_v2",
                "entity_to_feature": {
                    "E001": "PF_U",
                    "E002": "PF_V",
                },
                "ignored_orphan_profiles": [],
            },
        ],
        unresolved_evidence=[],
    )
    resolution = ResolutionResult(
        values={
            "feature:PF_U.boundary.y": 16.0,
            "feature:PF_V.boundary.z": 8.0,
        },
        traces={
            "feature:PF_U.boundary.y": ["D_UPRIGHT_16"],
            "feature:PF_V.boundary.z": ["D_BASE_8"],
        },
        derivations={},
        unresolved=[],
        conflicts=[],
    )

    draft = build_semantic_draft(graph, resolution)

    assert draft["profile"]["plane"] == "YZ"
    assert draft["profile"]["topology"] == "L"
    assert draft["profile"]["segments"][0] == {
        "type": "line",
        "y1": -16.0,
        "z1": 0.0,
        "y2": 16.0,
        "z2": 0.0,
    }
    metric_sources = [
        item
        for item in draft["source_ledger"]
        if item.get("solver") == "metric_profile_solver"
    ]
    assert metric_sources
    assert "D_UPRIGHT_16" in metric_sources[0]["evidence"]
    assert "D_BASE_8" in metric_sources[0]["evidence"]


def test_build_semantic_draft_reuses_unique_cross_view_profile_boundary_coordinate() -> None:
    from nx_mcp.drawing_intelligence.draft import build_semantic_draft
    from nx_mcp.drawing_intelligence.evidence import (
        EvidenceGraph,
        OverallDimensions,
        RelationEvidence,
    )
    from nx_mcp.drawing_intelligence.resolver import ResolutionResult

    graph = EvidenceGraph(
        schema_version="1.0",
        coordinate_system="overall_min_xyz",
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[],
        projections=[],
        dimensions=[],
        datum_alignments=[],
        direct_values=[],
        relations=[
            RelationEvidence(
                id="D_BASE_8",
                kind="edge_offset",
                axis="Z",
                targets=["feature:PF_V_CROSS.boundary.z"],
                value=8.0,
                from_side="min",
                source_ids=[
                    "hybrid:whole:14",
                    "hybrid:DG18:unassigned-profile-offset-recovery",
                ],
                required_for_modeling=True,
            )
        ],
        required_targets=[],
        observations=[
            {
                "kind": "hybrid_profile_topology_ledger",
                "items": [
                    {
                        "region_id": "R2",
                        "plane": "YZ",
                        "topology": "L",
                        "upright_side": "max",
                        "base_side": "min",
                        "internal_u_entity_id": "E_U",
                        "internal_v_entity_id": "E_V_UNMATERIALIZED",
                        "internal_u_ref": "R2.structural.vertical.003",
                        "internal_v_ref": "R2.structural.horizontal.003",
                        "outer_refs": {
                            "u_min": "R2.structural.vertical.001",
                            "u_max": "R2.structural.vertical.004",
                            "v_min": "R2.structural.horizontal.004",
                            "v_max": "R2.structural.horizontal.001",
                        },
                    }
                ],
            },
            {
                "kind": "identity_linker_v2",
                "entity_to_feature": {
                    "E_U": "PF_U",
                    "E_CROSS_VIEW": "PF_V_CROSS",
                },
                "ignored_orphan_profiles": ["E_V_UNMATERIALIZED"],
            },
        ],
        unresolved_evidence=[],
    )
    resolution = ResolutionResult(
        values={
            "feature:PF_U.boundary.y": 16.0,
            "feature:PF_V_CROSS.boundary.z": 8.0,
        },
        traces={
            "feature:PF_U.boundary.y": ["D_UPRIGHT_16"],
            "feature:PF_V_CROSS.boundary.z": ["D_BASE_8"],
        },
        derivations={},
        unresolved=[],
        conflicts=[],
    )

    draft = build_semantic_draft(graph, resolution)

    assert draft["profile"]["plane"] == "YZ"
    assert draft["profile"]["topology"] == "L"
    assert draft["profile"]["segments"] == [
        {"type": "line", "y1": -16.0, "z1": 0.0, "y2": 16.0, "z2": 0.0},
        {"type": "line", "y1": 16.0, "z1": 0.0, "y2": 16.0, "z2": 66.0},
        {"type": "line", "y1": 16.0, "z1": 66.0, "y2": 0.0, "z2": 66.0},
        {"type": "line", "y1": 0.0, "z1": 66.0, "y2": 0.0, "z2": 8.0},
        {"type": "line", "y1": 0.0, "z1": 8.0, "y2": -16.0, "z2": 8.0},
        {"type": "line", "y1": -16.0, "z1": 8.0, "y2": -16.0, "z2": 0.0},
    ]


def test_build_semantic_draft_rejects_ambiguous_cross_view_profile_boundary_coordinates() -> None:
    from nx_mcp.drawing_intelligence.draft import build_semantic_draft
    from nx_mcp.drawing_intelligence.evidence import (
        EvidenceGraph,
        OverallDimensions,
        RelationEvidence,
    )
    from nx_mcp.drawing_intelligence.resolver import ResolutionResult

    graph = EvidenceGraph(
        schema_version="1.0",
        coordinate_system="overall_min_xyz",
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[],
        projections=[],
        dimensions=[],
        datum_alignments=[],
        direct_values=[],
        relations=[
            RelationEvidence(
                id="D_Z8",
                kind="edge_offset",
                axis="Z",
                targets=["feature:PF_Z8.boundary.z"],
                value=8.0,
                from_side="min",
                source_ids=["hybrid:A:unassigned-profile-offset-recovery"],
                required_for_modeling=True,
            ),
            RelationEvidence(
                id="D_Z12",
                kind="edge_offset",
                axis="Z",
                targets=["feature:PF_Z12.boundary.z"],
                value=12.0,
                from_side="min",
                source_ids=["hybrid:B:unassigned-profile-offset-recovery"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[],
        observations=[
            {
                "kind": "hybrid_profile_topology_ledger",
                "items": [
                    {
                        "region_id": "R2",
                        "plane": "YZ",
                        "topology": "L",
                        "upright_side": "max",
                        "base_side": "min",
                        "internal_u_entity_id": "E_U",
                        "internal_v_entity_id": "E_V_UNMATERIALIZED",
                        "internal_u_ref": "R2.structural.vertical.003",
                        "internal_v_ref": "R2.structural.horizontal.003",
                        "outer_refs": {},
                    }
                ],
            },
            {
                "kind": "identity_linker_v2",
                "entity_to_feature": {"E_U": "PF_U"},
                "ignored_orphan_profiles": ["E_V_UNMATERIALIZED"],
            },
        ],
        unresolved_evidence=[],
    )
    resolution = ResolutionResult(
        values={
            "feature:PF_U.boundary.y": 16.0,
            "feature:PF_Z8.boundary.z": 8.0,
            "feature:PF_Z12.boundary.z": 12.0,
        },
        traces={
            "feature:PF_U.boundary.y": ["D_UPRIGHT_16"],
            "feature:PF_Z8.boundary.z": ["D_Z8"],
            "feature:PF_Z12.boundary.z": ["D_Z12"],
        },
        derivations={},
        unresolved=[],
        conflicts=[],
    )

    draft = build_semantic_draft(graph, resolution)

    assert "profile" not in draft
