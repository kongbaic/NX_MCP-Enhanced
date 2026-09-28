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


def test_hybrid_decision_accepts_decimal_split_by_local_rotation():
    module = _load_module()

    assert module._hybrid_decision("4.5", {"4", "5"}) == (
        "4.5",
        "global_decimal_confirmed_by_local_fragments",
    )


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
