from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observation_finalizer import (
    ReaderObservationFinalizationError,
    finalize_partial_reader_observations,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservationAssemblyError,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.reader_visual_aid import build_reader_visual_aid


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


def replay_hybrid_constraint_bridge(
    *,
    raw_evidence: dict[str, Any],
    hybrid_report: dict[str, Any],
    context_payload: dict[str, Any],
) -> dict[str, Any]:
    """Replay current Reader bridge without re-running OCR.

    The stable Hybrid OCR text decisions are preserved. Geometry-only fields
    that may evolve with production code are rebuilt from the supplied raw
    evidence before running Adapter -> Capture -> Linker -> Compiler -> Resolver.
    """

    visual_aid = build_reader_visual_aid(raw_evidence)
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

    result: dict[str, Any] = {
        "schema": "hybrid-constraint-bridge-replay-v1",
        "ocr_reexecuted": False,
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
        "unresolved": [
            item.model_dump(mode="json") for item in partial.unresolved
        ],
        "ledgers": {
            kind: _ledger(observations, kind)
            for kind in (
                "hybrid_view_axis_boundary_ledger",
                "hybrid_circle_datum_alignment_ledger",
                "hybrid_engineering_callout_ledger",
                "hybrid_view_metric_calibration_ledger",
                "hybrid_metric_profile_edge_ledger",
                "hybrid_metric_profile_segment_ledger",
                "hybrid_metric_circle_primitive_ledger",
            )
        },
        "pipeline": {
            "finalized": False,
            "capture_assembled": False,
            "linked": False,
            "compiled": False,
            "resolved": False,
        },
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
        result["resolution"] = resolution.to_dict()
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
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    raw_path = Path(args.raw).resolve()
    hybrid_path = Path(args.hybrid).resolve()
    context_path = Path(args.context).resolve()
    out_path = Path(args.out).resolve()

    try:
        result = replay_hybrid_constraint_bridge(
            raw_evidence=_load(raw_path),
            hybrid_report=_load(hybrid_path),
            context_payload=_load(context_path),
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

    blocking = [
        item
        for item in result["unresolved"]
        if item.get("required_for_modeling", True)
    ]
    print(
        json.dumps(
            {
                "written": True,
                "out": str(out_path),
                "ocr_reexecuted": False,
                "accepted_dimension_count": len(
                    result["accepted_dimension_keys"]
                ),
                "association_count": result["association_count"],
                "blocking_unresolved_count": len(blocking),
                "pipeline": result["pipeline"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
