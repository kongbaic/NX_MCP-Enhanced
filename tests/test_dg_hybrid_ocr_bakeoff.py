from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np


def _load_module():
    from nx_mcp.drawing_intelligence import hybrid_ocr

    return hybrid_ocr


def test_stdout_json_is_safe_for_windows_legacy_encoding():
    module = _load_module()

    rendered = module._stdout_json(
        {
            "diameter": "Ø20",
            "ocr": "∅20",
            "tolerance": "40±0.02",
        }
    )

    rendered.encode("cp936")
    assert "\\u00d8" in rendered
    assert "\\u2205" in rendered


def test_production_hybrid_ocr_two_pass_flow(tmp_path: Path, monkeypatch):
    module = _load_module()

    source = tmp_path / "drawing.png"
    image = np.full((200, 200, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(source), image)

    visual_aid = {
        "schema": "reader-visual-aid-v1",
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 200, 200],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "candidate_buckets": [
            {
                "bucket_id": "R1.horizontal.middle",
                "region_id": "R1",
                "status": "bounded",
                "candidates": [
                    {
                        "candidate_id": "DG1",
                        "region_id": "R1",
                        "orientation": "horizontal",
                        "axis_px": 100.0,
                        "line_span_px": [20.0, 180.0],
                        "witness_positions_px": [50.0, 150.0],
                        "witness_anchor_evidence": [],
                        "witness_line_evidence": [],
                    }
                ],
            }
        ],
        "annotation_line_candidates": [],
        "structural_profile_inventory": [],
    }
    visual_path = tmp_path / "reader-visual-aid.json"
    visual_path.write_text(json.dumps(visual_aid), encoding="utf-8")

    reader_input = {
        "schema": "reader-input-v1",
        "source_raster_path": str(source),
        "reader_visual_aid_path": str(visual_path),
    }
    reader_input_path = tmp_path / "reader-input.json"
    reader_input_path.write_text(json.dumps(reader_input), encoding="utf-8")

    class FakeEngine:
        def __init__(self):
            self.calls = 0

        def __call__(self, _image):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    boxes=[
                        [[80, 90], [120, 90], [120, 110], [80, 110]],
                        [[10, 10], [50, 10], [50, 30], [10, 30]],
                    ],
                    txts=["24", "Ø20"],
                    scores=[0.99, 0.95],
                )
            return SimpleNamespace(
                boxes=[[[80, 50], [120, 50], [120, 70], [80, 70]]],
                txts=["24"],
                scores=[0.99],
            )

    engine = FakeEngine()

    class FakeRapidOcrModule:
        @staticmethod
        def RapidOCR(*, params):
            assert params["Global.use_cls"] is True
            assert params["Global.return_word_box"] is False
            return engine

    real_import = module.importlib.import_module

    def fake_import(name: str):
        if name == "rapidocr":
            return FakeRapidOcrModule
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)

    output = tmp_path / "hybrid-report.json"
    artifact_dir = tmp_path / "ocr-artifacts"
    exit_code = module.main(
        [
            str(reader_input_path),
            str(output),
            "--artifact-dir",
            str(artifact_dir),
        ]
    )

    assert exit_code == 0
    assert engine.calls == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "dg-hybrid-ocr-bakeoff-v2"
    assert report["candidate_count"] == 1
    assert report["accepted_count"] == 1
    assert report["unresolved_count"] == 0
    assert report["candidates"][0]["accepted_token"] == "24"
    assert report["coverage"]["observed_silent_drop_count"] == 0
    assert len(report["coverage"]["accepted_support_observations"]) == 1
    assert len(report["coverage"]["routed_elsewhere_or_unclassified_observations"]) == 1
    assert (artifact_dir / "dg-hybrid-wide.png").is_file()
    assert (artifact_dir / "crops" / "DG1-wide.png").is_file()


def test_linear_tokens_accept_strict_labeled_mm_scalars_without_open_text_extraction():
    module = _load_module()

    assert module._linear_tokens("D - 300 mm") == {"300"}
    assert module._linear_tokens("NI - 192 mm") == {"192"}
    assert module._linear_tokens("H2 - 75 mm") == {"75"}
    assert module._linear_tokens("D1 – 250 mm") == {"250"}
    assert module._linear_tokens("K=26mm") == {"26"}
    assert module._linear_tokens("28 mm") == {"28"}
    assert module._linear_tokens("4.5 mm") == {"4.5"}
    assert module._linear_tokens("A - 168,3 mm") == {"168.3"}

    # Existing non-linear engineering callouts stay outside the linear-DG path.
    assert module._linear_tokens("R10") == set()
    assert module._linear_tokens("Ø18") == set()
    assert module._linear_tokens("M10") == set()

    # Do not mine arbitrary prose or long labels for embedded numbers.
    assert module._linear_tokens("NOTE - 300 mm") == set()
    assert module._linear_tokens("LENGTH - 300 mm") == set()
    assert module._linear_tokens("NOTE 28 mm") == set()


def test_collect_candidates_deduplicates_exact_cross_region_geometry_with_provenance():
    module = _load_module()

    shared_geometry = {
        "orientation": "horizontal",
        "axis_px": 96.0,
        "line_span_px": [445.0, 1010.0],
        "witness_positions_px": [434.8, 1020.0],
        "witness_anchor_evidence": [],
        "witness_line_evidence": [],
    }
    visual_aid = {
        "candidate_buckets": [
            {
                "status": "bounded",
                "candidates": [
                    {
                        **shared_geometry,
                        "candidate_id": "DG1",
                        "region_id": "R2",
                    }
                ],
            },
            {
                "status": "bounded",
                "candidates": [
                    {
                        **shared_geometry,
                        "candidate_id": "DG2",
                        "region_id": "R3",
                    },
                    {
                        "candidate_id": "DG3",
                        "region_id": "R3",
                        "orientation": "horizontal",
                        "axis_px": 146.0,
                        "line_span_px": [470.0, 974.0],
                        "witness_positions_px": [434.8, 472.1, 984.0],
                        "witness_anchor_evidence": [],
                        "witness_line_evidence": [],
                    },
                ],
            },
        ]
    }

    candidates = module._collect_candidates(visual_aid)

    assert [item["candidate_id"] for item in candidates] == ["DG1", "DG3"]
    assert candidates[0]["source_candidate_ids"] == ["DG1", "DG2"]
    assert candidates[0]["source_region_ids"] == ["R2", "R3"]
    assert [
        item["candidate_id"]
        for item in candidates[0]["source_candidate_variants"]
    ] == ["DG1", "DG2"]



def test_collect_candidates_keeps_cross_region_witness_evidence_separate():
    module = _load_module()

    shared_geometry = {
        "orientation": "horizontal",
        "axis_px": 146.0,
        "line_span_px": [470.0, 974.0],
        "witness_positions_px": [472.1, 984.0],
    }
    visual_aid = {
        "candidate_buckets": [
            {
                "status": "bounded",
                "candidates": [
                    {
                        **shared_geometry,
                        "candidate_id": "DG3",
                        "region_id": "R2",
                        "witness_anchor_evidence": [
                            {
                                "witness_index": 0,
                                "position_px": 472.1,
                                "axis": "x",
                                "nearest_anchors": [
                                    {
                                        "kind": "linear_pattern_axis",
                                        "ref": "R2.linear_pattern.001",
                                    }
                                ],
                            }
                        ],
                        "witness_line_evidence": [],
                    }
                ],
            },
            {
                "status": "bounded",
                "candidates": [
                    {
                        **shared_geometry,
                        "candidate_id": "DG4",
                        "region_id": "R3",
                        "witness_anchor_evidence": [
                            {
                                "witness_index": 0,
                                "position_px": 472.1,
                                "axis": "x",
                                "nearest_anchors": [
                                    {
                                        "kind": "profile_edge_candidate",
                                        "ref": "R3.structural.vertical.001",
                                    }
                                ],
                            }
                        ],
                        "witness_line_evidence": [],
                    }
                ],
            },
        ]
    }

    candidates = module._collect_candidates(visual_aid)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_candidate_ids"] == ["DG3", "DG4"]
    assert candidate["source_region_ids"] == ["R2", "R3"]
    assert [
        item["candidate_id"]
        for item in candidate["source_candidate_variants"]
    ] == ["DG3", "DG4"]

    canonical_refs = {
        item["ref"]
        for record in candidate["witness_anchor_evidence"]
        for item in record["nearest_anchors"]
    }
    assert canonical_refs == {"R2.linear_pattern.001"}

    variant_refs = [
        {
            item["ref"]
            for record in variant["witness_anchor_evidence"]
            for item in record["nearest_anchors"]
        }
        for variant in candidate["source_candidate_variants"]
    ]
    assert variant_refs == [
        {"R2.linear_pattern.001"},
        {"R3.structural.vertical.001"},
    ]


def test_dedup_group_ocr_extent_covers_largest_source_region():
    from nx_mcp.drawing_intelligence import ocr_runtime

    candidate = {
        "candidate_id": "DG1",
        "region_id": "R2",
        "source_region_ids": ["R2", "R3"],
    }
    region_lookup = {
        "R2": [100, 50, 800, 500],
        "R3": [400, 80, 600, 240],
    }

    bbox = ocr_runtime._candidate_region_bbox(candidate, region_lookup)

    assert bbox[2:] == [800, 500]


def test_structured_scalar_can_bind_vertical_candidate_with_horizontal_text():
    module = _load_module()
    candidate = {
        "orientation": "vertical",
        "axis_px": 472.0,
        "wide": {"source_roi_bbox_px": [418, 115, 108, 200]},
    }
    item = {
        "text": "S - 4.5 mm",
        "bbox": [[416, 162], [538, 162], [538, 192], [416, 192]],
    }
    bare = {
        "text": "4",
        "bbox": [[468, 138], [486, 138], [486, 154], [468, 154]],
    }

    assert module._candidate_matches_item(candidate, item) is True
    assert module._candidate_matches_item(candidate, bare) is False


def test_ambiguous_bare_dimension_text_keeps_geometry_matching():
    module = _load_module()
    # Synthetic orientation-neutral OCR glyphs: text-box aspect ratio
    # below 1.25 gives 'ambiguous', which is NOT a mismatched direction.
    roi = {"source_roi_bbox_px": [0, 0, 240, 240]}
    cases = (
        ("24", 46, 40, "horizontal"),
        ("40", 48, 45, "horizontal"),
        ("18", 39, 39, "vertical"),
    )
    for token, width, height, direction in cases:
        bbox = [[80, 80], [80 + width, 80],
                [80 + width, 80 + height], [80, 80 + height]]
        item = {"text": token, "bbox": bbox}
        assert module._item_orientation(item) == "ambiguous"
        axis = (80 + height / 2) if direction == "horizontal" else (80 + width / 2)
        candidate = {
            "candidate_id": "DG_unique",
            "orientation": direction, "axis_px": axis, "wide": roi,
        }
        assert module._candidate_matches_item(candidate, item)
        assigned = module._assign_global_items([candidate], [item])
        assert [a["token"] for a in assigned["DG_unique"]] == [token]


def test_ambiguous_dimension_still_requires_unique_distance_margin():
    module = _load_module()
    item = {"text": "24", "bbox": [[80, 80], [126, 80],
                                    [126, 120], [80, 120]]}
    roi = {"source_roi_bbox_px": [0, 0, 240, 240]}
    # The same ambiguous OCR glyph is near two dimension axes;
    # the unchanged geometric margin gate MUST keep both unassigned.
    candidates = [
        {"candidate_id": "DG_a", "orientation": "horizontal",
         "axis_px": 99, "wide": roi},
        {"candidate_id": "DG_b", "orientation": "horizontal",
         "axis_px": 102, "wide": roi},
    ]
    assigned = module._assign_global_items(candidates, [item])
    assert assigned == {"DG_a": [], "DG_b": []}

    # A truly perpendicular bare number is still rejected; structured
    # scalar direction handling is covered by the existing test above.
    clearly_vertical_item = {
        "text": "24",
        "bbox": [[90, 50], [110, 50], [110, 130], [90, 130]],
    }
    assert module._item_orientation(clearly_vertical_item) == "vertical"
    assert module._candidate_matches_item(candidates[0], clearly_vertical_item) is False

    # Preserve the existing structured-scalar safety contract: a single
    # ambiguous bare glyph must not bind to an otherwise plausible line.
    one_digit = {
        "text": "4",
        "bbox": [[80, 80], [98, 80], [98, 96], [80, 96]],
    }
    assert module._item_orientation(one_digit) == "ambiguous"
    for orientation in ("horizontal", "vertical"):
        line = {
            "candidate_id": "noise",
            "orientation": orientation,
            "axis_px": 90,
            "wide": roi,
        }
        assert module._candidate_matches_item(line, one_digit) is False
        assert module._assign_global_items([line], [one_digit]) == {"noise": []}


def test_global_proposal_prefers_structured_scalar_over_bare_glyph():
    module = _load_module()
    candidate = {
        "orientation": "horizontal",
        "wide": {"source_roi_bbox_px": [385, 101, 649, 90]},
    }
    proposal, reason = module._global_proposal(
        candidate,
        [
            {
                "source_item_index": 1,
                "text": "A - 168,3 mm",
                "token": "168.3",
                "perpendicular_distance_px": 19.25,
            },
            {
                "source_item_index": 3,
                "text": "4",
                "token": "4",
                "perpendicular_distance_px": 0.0,
            },
            {
                "source_item_index": 4,
                "text": "S - 4.5 mm",
                "token": "4.5",
                "perpendicular_distance_px": 31.0,
            },
        ],
    )

    assert proposal == "168.3"
    assert reason == "strongest_unique_global_linear_token"



def test_coverage_classifies_only_bare_glyphs_covering_accepted_dimension_endpoints():
    module = _load_module()
    accepted = {
        "candidate_id": "DG3",
        "accepted_token": "168.3",
        "orientation": "horizontal",
        "axis_px": 146.0,
        "line_span_px": [470.0, 974.0],
        "global_assignments": [
            {
                "source_item_index": 0,
                "text": "A - 168,3 mm",
                "token": "168.3",
                "perpendicular_distance_px": 19.25,
            }
        ],
        "global_proposal_token": "168.3",
        "decision_reason": "global_geometry_assignment_confirmed_by_local_roi",
        "wide_local_linear_tokens": ["168.3"],
    }
    whole_items = [
        {
            "text": "A - 168,3 mm",
            "bbox": [[654, 110], [802, 113], [801, 143], [653, 141]],
        },
        {
            "text": "4",
            "bbox": [[468, 138], [486, 138], [486, 154], [468, 154]],
        },
        {
            "text": "4",
            "bbox": [[970, 137], [987, 137], [987, 155], [970, 155]],
        },
        {
            "text": "4",
            "bbox": [[700, 138], [718, 138], [718, 154], [700, 154]],
        },
    ]

    coverage = module._coverage_ledger(whole_items, [accepted])

    endpoint_glyphs = coverage[
        "non_modeling_dimension_arrow_glyph_observations"
    ]
    assert [item["source_item_index"] for item in endpoint_glyphs] == [1, 2]
    assert all(
        item["reason"] == "covers_accepted_dimension_line_endpoint"
        for item in endpoint_glyphs
    )
    assert [
        item["source_item_index"]
        for item in coverage["unassigned_linear_observations"]
    ] == [3]


def test_bare_glyph_endpoint_classifier_is_orientation_generic_and_fail_closed():
    module = _load_module()
    accepted_vertical = {
        "candidate_id": "DGV",
        "accepted_token": "12",
        "orientation": "vertical",
        "axis_px": 220.0,
        "line_span_px": [100.0, 300.0],
    }

    endpoint_glyph = {
        "text": "4",
        "bbox": [[212, 94], [228, 94], [228, 106], [212, 106]],
    }
    midline_glyph = {
        "text": "4",
        "bbox": [[212, 190], [228, 190], [228, 202], [212, 202]],
    }

    owner = module._bare_glyph_dimension_endpoint_owner(
        endpoint_glyph,
        [accepted_vertical],
    )
    assert owner is not None
    assert owner["candidate_id"] == "DGV"
    assert owner["line_endpoint_px"] == 100.0
    assert (
        module._bare_glyph_dimension_endpoint_owner(
            midline_glyph,
            [accepted_vertical],
        )
        is None
    )


def test_dimension_role_conflict_gate_rejects_extension_line_candidate():
    module = _load_module()
    strong = {
        "candidate_id": "DG_STRONG",
        "accepted_token": "168.3",
        "orientation": "horizontal",
        "axis_px": 50.0,
        "line_span_px": [20.0, 200.0],
        "witness_positions_px": [10.0, 210.0],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [0.0, 300.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
        "decision_reason": "accepted",
    }
    weak = {
        "candidate_id": "DG_WEAK",
        "accepted_token": "4.5",
        "orientation": "vertical",
        "axis_px": 100.0,
        "line_span_px": [0.0, 300.0],
        "witness_positions_px": [10.0, 120.0],
        "witness_line_evidence": [],
        "decision_reason": "accepted",
    }

    results = [strong, weak]
    module._apply_dimension_role_conflict_gate(results)

    assert strong["accepted_token"] == "168.3"
    assert weak["accepted_token"] is None
    assert weak["decision_reason"] == (
        "candidate_line_is_extension_witness_of_accepted_dimension"
    )
    assert weak["dimension_role_conflict"]["witness_owner_candidate_ids"] == [
        "DG_STRONG"
    ]


def test_dimension_role_conflict_gate_keeps_bounded_crossing_dimension():
    module = _load_module()
    first = {
        "candidate_id": "DG_FIRST",
        "accepted_token": "100",
        "orientation": "horizontal",
        "axis_px": 50.0,
        "line_span_px": [20.0, 200.0],
        "witness_positions_px": [10.0, 210.0],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [20.0, 180.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
        "decision_reason": "accepted",
    }
    second = {
        "candidate_id": "DG_SECOND",
        "accepted_token": "80",
        "orientation": "vertical",
        "axis_px": 100.0,
        "line_span_px": [20.0, 180.0],
        "witness_positions_px": [10.0, 190.0],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "horizontal",
                        "axis_px": 50.0,
                        "span_px": [20.0, 200.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
        "decision_reason": "accepted",
    }

    results = [first, second]
    module._apply_dimension_role_conflict_gate(results)

    assert first["accepted_token"] == "100"
    assert second["accepted_token"] == "80"


def test_hybrid_decision_accepts_decimal_split_by_local_rotation():
    module = _load_module()

    assert module._hybrid_decision("4.5", {"4", "5"}) == (
        "4.5",
        "global_decimal_confirmed_by_local_fragments",
    )


def test_hybrid_decision_accepts_structured_decimal_with_extra_bare_local_noise():
    module = _load_module()

    assert module._hybrid_decision(
        "4.5",
        {"1", "4", "5"},
        global_text_strength=3,
        local_strong_tokens=set(),
    ) == (
        "4.5",
        "structured_global_decimal_confirmed_by_local_fragment_subset",
    )

    assert module._hybrid_decision(
        "4.5",
        {"1", "4", "5"},
        global_text_strength=1,
        local_strong_tokens=set(),
    ) == (None, "global_local_token_disagreement")

    assert module._hybrid_decision(
        "4.5",
        {"1", "4", "5"},
        global_text_strength=3,
        local_strong_tokens={"1"},
    ) == (None, "global_local_token_disagreement")


def test_hybrid_decision_fails_closed_on_disagreement():
    module = _load_module()

    assert module._hybrid_decision("6", {"66"}) == (
        None,
        "global_local_token_disagreement",
    )
    assert module._hybrid_decision(None, {"66"}) == (
        None,
        "no_global_proposal",
    )



def test_exterior_single_digit_only_binds_unique_physical_witness_pair():
    module = _load_module()

    candidate = {
        "candidate_id": "DG_OUTSIDE",
        "orientation": "horizontal",
        "axis_px": 160.0,
        "line_span_px": [737, 795],
        "witness_positions_px": [703.7, 744.0, 785.8],
        "witness_line_evidence": [
            {"witness_index": 0, "source_lines": []},
            {"witness_index": 1, "source_lines": [
                {"orientation": "vertical", "axis_px": 744.0,
                 "crosses_dimension_axis": True},
            ]},
            {"witness_index": 2, "source_lines": [
                {"orientation": "vertical", "axis_px": 785.8,
                 "crosses_dimension_axis": True},
            ]},
        ],
        "witness_anchor_evidence": [
            {"witness_index": 0, "nearest_anchors": []},
            {"witness_index": 1, "nearest_anchors": [
                {"kind": "circle_center_axis", "ref": "R.C1.center_x"},
            ]},
            {"witness_index": 2, "nearest_anchors": [
                {"kind": "profile_edge_candidate", "ref": "R.profile.max"},
            ]},
        ],
        "wide": {"source_roi_bbox_px": [690, 110, 112, 100]},
    }
    exterior = {
        "text": "8",
        "bbox": [[812, 120], [838, 120], [838, 156], [812, 156]],
    }
    assert module._exterior_single_digit_witness_proof(candidate, exterior)
    assigned = module._assign_global_items([candidate], [exterior])
    assert [row["token"] for row in assigned["DG_OUTSIDE"]] == ["8"]
    assert assigned["DG_OUTSIDE"][0]["exterior_single_digit_witness_proven"] is True

    # No-geometry, one-witness, duplicate owner, and distant text must stay
    # unassigned (no general relaxation of bare OCR glyph policy).
    broken = {**candidate, "witness_line_evidence": []}
    assert not module._candidate_matches_item(broken, exterior)
    broken = {**candidate, "witness_anchor_evidence": []}
    assert not module._candidate_matches_item(broken, exterior)
    broken = {**candidate, "witness_anchor_evidence": [
        candidate["witness_anchor_evidence"][0],
        candidate["witness_anchor_evidence"][1],
        {"witness_index": 2, "nearest_anchors": [
            {"kind": "circle_center_axis", "ref": "R.C1.center_x"},
        ]},
    ]}
    assert not module._candidate_matches_item(broken, exterior)
    distant = {"text": "8", "bbox": [
        [845, 120], [870, 120], [870, 156], [845, 156],
    ]}
    assert not module._candidate_matches_item(candidate, distant)



def test_overflow_is_hidden_from_reader_but_preserved_for_machine_ocr():
    """Reader 4-item display caps must never silently drop OCR candidates."""
    module = _load_module()
    from nx_mcp.drawing_intelligence.reader_visual_aid import build_reader_visual_aid

    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1000, "height": 600},
        "regions": [
            {
                "region_id": "R",
                "bbox_px": [100, 50, 400, 300],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            },
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": f"DG{i}",
                "region_id": "R",
                "orientation": "horizontal",
                "axis_px": 80.0 + i * 8,
                "axis_local_norm": (80.0 + i * 8 - 50.0) / 300.0,
                "line_span_px": [140, 330],
                "witness_positions_px": [140 + 12 * i, 330 - 12 * i],
                "witness_positions_local_norm": [
                    (40 + 12 * i) / 400, (230 - 12 * i) / 400
                ],
                "witness_line_evidence": [],
            }
            for i in range(5)
        ],
        "annotation_line_candidates": [],
    }
    aid = build_reader_visual_aid(raw)
    assert aid["summary"]["overflow_bucket_count"] == 1
    overflow_bucket = next(
        b for b in aid["candidate_buckets"] if b["status"] == "overflow"
    )
    assert overflow_bucket["candidates"] == []
    assert overflow_bucket["candidate_count"] == 5

    recovered = module._collect_candidates(aid, raw)
    assert len(recovered) == 5
    assert {c["candidate_id"] for c in recovered} == {
        f"DG{i}" for i in range(5)
    }
    assert all("witness_anchor_evidence" in c for c in recovered)
    # Candidate content sent to Reader remains bounded/unchanged.
    assert overflow_bucket["candidates"] == []

    corrupted = {**aid, "candidate_buckets": [
        {**b, "candidate_count": 6} if b["status"] == "overflow" else b
        for b in aid["candidate_buckets"]
    ]}
    import pytest
    with pytest.raises(ValueError, match="count mismatch"):
        module._collect_candidates(corrupted, raw)


def test_overflow_recovery_keeps_existing_bounded_candidate_geometry():
    module = _load_module()
    raw = {
        "schema": "raw-evidence-v1",
        "regions": [
            {
                "region_id": "R", "bbox_px": [0, 0, 300, 300],
                "circle_groups": [], "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_OV",
                "region_id": "R", "orientation": "horizontal",
                "axis_local_norm": 0.10, "axis_px": 30,
                "line_span_px": [30, 200],
                "witness_positions_px": [50, 180],
                "witness_positions_local_norm": [0.167, 0.6],
                "witness_line_evidence": [],
            },
        ],
    }
    aid = {
        "candidate_buckets": [
            {
                "region_id": "R", "orientation": "horizontal",
                "band": "top", "status": "bounded",
                "candidate_count": 1,
                "candidates": [{
                    "candidate_id": "DG_KEEP",
                    "region_id": "R", "orientation": "horizontal",
                    "axis_px": 90.0,
                    "line_span_px": [20, 200],
                    "witness_positions_px": [20, 200],
                    "witness_anchor_evidence": [],
                }],
            },
        ]
    }
    # No overflow -> original visible/accepted OCR candidates are untouched.
    actual = module._collect_candidates(aid, raw)
    assert [item["candidate_id"] for item in actual] == ["DG_KEEP"]
