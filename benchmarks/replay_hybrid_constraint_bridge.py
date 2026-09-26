from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.draft import build_semantic_draft
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.raster_evidence import extract_raw_evidence
from nx_mcp.drawing_intelligence.reader_observation_finalizer import (
    ReaderObservationFinalizationError,
    finalize_partial_reader_observations,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservationAssemblyError,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.reader_visual_aid import build_reader_visual_aid


def _load_gate_a_runner() -> Any:
    root = Path(__file__).resolve().parents[1]
    runner_path = root / "agent" / "nx-mcp-plan-runner" / "runner.py"
    spec = importlib.util.spec_from_file_location(
        "hybrid_constraint_bridge_gate_a",
        runner_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Gate A runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _ledger(
    observations: list[dict[str, Any]],
    kind: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in observations
            if isinstance(item, dict) and item.get("kind") == kind
        ),
        None,
    )


def _blocking_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(item)
        for item in items
        if item.get("required_for_modeling", True)
    ]


def _blocking_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": item.get("kind"),
            "field": item.get("field"),
            "dimension_key": item.get("dimension_key"),
            "entity_keys": list(item.get("entity_keys") or []),
            "feature_ids": list(item.get("feature_ids") or []),
            "reason": item.get("reason"),
        }
        for item in items
        if item.get("required_for_modeling", True)
    ]


def _set_final_blocking_status(
    result: dict[str, Any],
    unresolved: list[dict[str, Any]],
) -> None:
    result["blocking_unresolved"] = _blocking_records(unresolved)
    result["blocking_summary"] = _blocking_summary(unresolved)


def replay_hybrid_constraint_bridge(
    *,
    raw_evidence: dict[str, Any],
    hybrid_report: dict[str, Any],
    context_payload: dict[str, Any],
    raster_path: Path | None = None,
) -> dict[str, Any]:
    """Replay current Reader bridge without re-running OCR.

    The stable Hybrid OCR text decisions are preserved. Geometry-only fields
    that may evolve with production code are rebuilt from the supplied raw
    evidence before running Adapter -> Capture -> Linker -> Compiler -> Resolver.
    """

    replay_raw = copy.deepcopy(raw_evidence)
    annotation_geometry_rebuilt = False
    current_annotation_count = len(
        replay_raw.get("annotation_line_candidates", [])
        if isinstance(replay_raw.get("annotation_line_candidates"), list)
        else []
    )
    if raster_path is not None:
        current_geometry = extract_raw_evidence(raster_path)
        stable_image = replay_raw.get("image", {})
        current_image = current_geometry.get("image", {})
        if (
            isinstance(stable_image, dict)
            and isinstance(current_image, dict)
            and (
                stable_image.get("width") != current_image.get("width")
                or stable_image.get("height") != current_image.get("height")
            )
        ):
            raise ValueError(
                "raster dimensions do not match the stable raw-evidence source"
            )
        replay_raw["annotation_line_candidates"] = copy.deepcopy(
            current_geometry.get("annotation_line_candidates", [])
        )
        current_annotation_count = len(
            replay_raw["annotation_line_candidates"]
        )
        annotation_geometry_rebuilt = True

    visual_aid = build_reader_visual_aid(replay_raw)
    report = copy.deepcopy(hybrid_report)
    report["regions"] = copy.deepcopy(visual_aid.get("regions", []))
    report["annotation_line_candidates"] = copy.deepcopy(
        visual_aid.get("annotation_line_candidates", [])
    )
    report["structural_profile_inventory"] = copy.deepcopy(
        visual_aid.get("structural_profile_inventory", [])
    )

    context = HybridAdapterContext.model_validate(context_payload)
    partial = adapt_hybrid_ocr_report(report, context)
    observations = [
        item for item in partial.observations if isinstance(item, dict)
    ]
    reader_unresolved = [
        item.model_dump(mode="json") for item in partial.unresolved
    ]
    reader_blocking_unresolved = _blocking_records(reader_unresolved)

    result: dict[str, Any] = {
        "schema": "hybrid-constraint-bridge-replay-v1",
        "ocr_reexecuted": False,
        "annotation_geometry_rebuilt_from_raster": annotation_geometry_rebuilt,
        "annotation_line_candidate_count": current_annotation_count,
        "hybrid_schema": report.get("schema"),
        "candidate_count": len(report.get("candidates", [])),
        "accepted_dimension_keys": sorted(item.key for item in partial.dimensions),
        "entity_keys": sorted(item.key for item in partial.entities),
        "association_count": len(partial.associations),
        "associations": [
            item.model_dump(mode="json") for item in partial.associations
        ],
        "values": [item.model_dump(mode="json") for item in partial.values],
        "dimensions": [
            item.model_dump(mode="json") for item in partial.dimensions
        ],
        "datum_alignments": [
            item.model_dump(mode="json") for item in partial.datum_alignments
        ],
        "unresolved": reader_unresolved,
        "reader_blocking_unresolved": reader_blocking_unresolved,
        "reader_blocking_summary": _blocking_summary(reader_unresolved),
        "ledgers": {
            kind: _ledger(observations, kind)
            for kind in (
                "hybrid_view_axis_boundary_ledger",
                "hybrid_circle_datum_alignment_ledger",
                "hybrid_engineering_callout_ledger",
                "hybrid_symmetric_dimension_recovery_ledger",
                "hybrid_view_metric_calibration_ledger",
                "hybrid_metric_profile_edge_ledger",
                "hybrid_metric_profile_segment_ledger",
                "hybrid_metric_circle_primitive_ledger",
            )
        },
        "blocking_unresolved": copy.deepcopy(reader_blocking_unresolved),
        "blocking_summary": _blocking_summary(reader_unresolved),
        "pipeline": {
            "finalized": False,
            "capture_assembled": False,
            "linked": False,
            "compiled": False,
            "resolved": False,
            "drafted": False,
            "gate_a_checked": False,
        },
        "gate_a_pass": False,
        "gate_a_errors": [],
    }

    try:
        full = finalize_partial_reader_observations(partial)
        result["pipeline"]["finalized"] = True
        capture = assemble_reader_capture(full)
        result["pipeline"]["capture_assembled"] = True
        linked = link_reader_capture(capture)
        result["pipeline"]["linked"] = True
        compiled = compile_evidence_graph(linked.evidence)
        result["pipeline"]["compiled"] = True
        resolution = resolve_evidence_graph(compiled)
        result["pipeline"]["resolved"] = True
        result["capture"] = capture.model_dump(mode="json")
        result["entity_to_feature"] = dict(sorted(linked.entity_to_feature.items()))
        result["compiled"] = compiled.model_dump(mode="json")
        resolution_payload = resolution.to_dict()
        result["resolution"] = resolution_payload
        final_unresolved = [
            item
            for item in resolution_payload.get("unresolved", [])
            if isinstance(item, dict)
        ]
        _set_final_blocking_status(result, final_unresolved)

        draft = build_semantic_draft(compiled, resolution)
        result["pipeline"]["drafted"] = True
        result["draft"] = draft
        gate_a_runner = _load_gate_a_runner()
        gate_a_errors = gate_a_runner.check_drawing_json(draft)
        result["pipeline"]["gate_a_checked"] = True
        result["gate_a_errors"] = list(gate_a_errors)
        result["gate_a_pass"] = not gate_a_errors
    except (
        ReaderObservationFinalizationError,
        ReaderObservationAssemblyError,
        ValueError,
    ) as exc:
        result["pipeline_error"] = f"{type(exc).__name__}: {exc}"

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--hybrid", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--raster")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    raw_path = Path(args.raw).resolve()
    hybrid_path = Path(args.hybrid).resolve()
    context_path = Path(args.context).resolve()
    out_path = Path(args.out).resolve()
    raster_path = Path(args.raster).resolve() if args.raster else None

    try:
        result = replay_hybrid_constraint_bridge(
            raw_evidence=_load(raw_path),
            hybrid_report=_load(hybrid_path),
            context_payload=_load(context_path),
            raster_path=raster_path,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "written": False,
                    "out": str(out_path),
                    "errors": [f"{type(exc).__name__}: {exc}"],
                },
                ensure_ascii=False,
            )
        )
        return 1

    blocking = result["blocking_unresolved"]
    print(
        json.dumps(
            {
                "written": True,
                "out": str(out_path),
                "ocr_reexecuted": False,
                "annotation_geometry_rebuilt_from_raster": result[
                    "annotation_geometry_rebuilt_from_raster"
                ],
                "annotation_line_candidate_count": result[
                    "annotation_line_candidate_count"
                ],
                "accepted_dimension_count": len(
                    result["accepted_dimension_keys"]
                ),
                "association_count": result["association_count"],
                "blocking_unresolved_count": len(blocking),
                "pipeline": result["pipeline"],
                "gate_a_pass": result["gate_a_pass"],
                "gate_a_error_count": len(result["gate_a_errors"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
