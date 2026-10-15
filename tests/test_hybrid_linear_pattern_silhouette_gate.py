"""Generic, topology-only rejection of off-body callout-to-hole candidates.

Uses raster pixel *membership*, not pixel-to-mm coordinate inference.
The numeric raster witnesses are a small, independent reproduction of a
real unresolved engineering callout, not a drawing-specific production rule.
"""

from __future__ import annotations

import nx_mcp.drawing_intelligence.hybrid_capture_adapter as adapter


def _bounds() -> list[dict]:
    return [
        {
            "status": "resolved",
            "region_id": "R1",
            "view_kind": "front",
            "axis": "Z",
            "engineering_coordinate_inferred_from_pixels": False,
            "anchors": [
                {
                    "role": "overall_max",
                    "ref": "R1.TOP",
                    "position_px": 199.88,
                },
                {
                    "role": "overall_min",
                    "ref": "R1.BOTTOM",
                    "position_px": 550.0,
                },
            ],
        }
    ]


def _profile() -> list[dict]:
    return [
        {"region_id": "R1", "ref": "R1.TOP", "axis_tolerance_px": 3.0},
        {"region_id": "R1", "ref": "R1.BOTTOM", "axis_tolerance_px": 3.0},
    ]


def _is_proven_inside(axis_position: float, bounds: list[dict]) -> bool:
    return adapter._linear_pattern_inside_verified_projection(
        {"orientation": "horizontal", "pattern_axis_px": axis_position},
        region_id="R1",
        view_kind="front",
        boundaries=bounds,
        profile_inventory=_profile(),
    )


def test_thread_leader_cannot_bind_to_raster_axis_above_verified_body():
    # The engineering callout leader can touch a dashed *annotation* above
    # the object; that is not proof that it owns a real material hole.
    assert not _is_proven_inside(159.9, _bounds())
    assert _is_proven_inside(216.6, _bounds())
    assert _is_proven_inside(200.0, _bounds())


def test_unverified_or_ambiguous_silhouette_cannot_invent_a_rejection():
    assert _is_proven_inside(159.9, [])
    duplicated = [*_bounds(), *_bounds()]
    assert _is_proven_inside(159.9, duplicated)
    unverified = _bounds()
    unverified[0]["engineering_coordinate_inferred_from_pixels"] = True
    assert _is_proven_inside(159.9, unverified)


def test_outside_profile_pattern_does_not_receive_m6_callout(monkeypatch):
    report = {
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 1,
                    "text": "M6深12",
                    "bbox": [
                        [109.0, 117.0],
                        [221.0, 117.0],
                        [221.0, 160.0],
                        [109.0, 160.0],
                    ],
                    "confidence": 0.99,
                }
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 600],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "annotation_line_candidates": [],
    }
    view_lookup = {
        "R1": adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:front"],
        )
    }
    monkeypatch.setattr(
        adapter,
        "bind_callout_to_circle_entity",
        lambda *args, **kwargs: {"status": "unresolved"},
    )
    monkeypatch.setattr(
        adapter,
        "bind_callout_to_linear_pattern",
        lambda *args, **kwargs: {
            "status": "bound",
            "entity_key": "R1.LINEAR_PATTERN.002",
            "region_id": "R1",
            "pattern_index": 1,
            "orientation": "horizontal",
            "axis": "X",
            "pattern_axis_px": 159.9,
        },
    )

    ledger, entities, values, unresolved = adapter._engineering_callout_routing(
        report,
        [],
        view_lookup,
        hidden_pattern_owner_by_index={},
        existing_entity_keys=set(),
        profile_inventory=_profile(),
        boundaries=_bounds(),
    )
    assert ledger[0]["binding"]["status"] != "pattern_backed"
    assert all(
        value.entity_key != "R1.LINEAR_PATTERN.002" for value in values
    )
    # Rejected owner cannot re-enter the model as an advisory callout carrier.
    assert entities == []
    assert values == []
    assert any(
        item.required_for_modeling
        and item.field == "engineering_callout_geometry_binding"
        and "outside" in item.reason
        for item in unresolved
    )


def test_inside_profile_pattern_keeps_existing_binding_behavior(monkeypatch):
    # The guard must not disable real patterned-hole callouts.
    monkeypatch.setattr(
        adapter,
        "bind_callout_to_circle_entity",
        lambda *args, **kwargs: {"status": "unresolved"},
    )
    monkeypatch.setattr(
        adapter,
        "bind_callout_to_linear_pattern",
        lambda *args, **kwargs: {
            "status": "bound",
            "entity_key": "R1.LINEAR_PATTERN.002",
            "region_id": "R1",
            "pattern_index": 1,
            "orientation": "horizontal",
            "axis": "X",
            "pattern_axis_px": 216.6,
        },
    )
    report = {
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 1,
                    "text": "M6深12",
                    "bbox": [[109, 117], [221, 117], [221, 160], [109, 160]],
                    "confidence": 0.99,
                }
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 600],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "annotation_line_candidates": [],
    }
    lookup = {
        "R1": adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["front"],
        )
    }
    _, _, values, unresolved = adapter._engineering_callout_routing(
        report,
        [],
        lookup,
        hidden_pattern_owner_by_index={},
        existing_entity_keys=set(),
        profile_inventory=_profile(),
        boundaries=_bounds(),
    )
    assert {
        (item.entity_key, item.field, item.value)
        for item in values
    } >= {
        ("R1.LINEAR_PATTERN.002", "thread_spec", "M6"),
        ("R1.LINEAR_PATTERN.002", "thread_depth", 12.0),
    }
    assert not any(item.required_for_modeling for item in unresolved)
