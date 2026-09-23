from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .capture import ReaderCapture, validate_reader_capture_contract
from .compiler import EvidenceCompileError, compile_evidence_graph
from .confirmation import (
    ConfirmationAnswers,
    ConfirmationError,
    apply_confirmation_answers,
    build_confirmation_request,
)
from .dimension_candidate_reducer import (
    DimensionCandidateQuery,
    reduce_dimension_candidates,
)
from .dimension_witness_anchors import enrich_reduced_dimension_candidates
from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import EvidenceGraph
from .gate0 import Gate0Error, write_strict_evidence
from .identity_linker import IdentityLinkError, link_reader_capture
from .raster_evidence import extract_raw_evidence
from .reader_candidate_answers import (
    CandidateRegionAnswer,
    ReaderCandidateAnswerError,
    assemble_candidate_regions,
)
from .reader_candidate_queries import (
    ReaderCandidateQueryError,
    ReaderCandidateQueryPlan,
    build_reader_candidate_queries,
)
from .reader_candidate_values import (
    CandidateValueRegionAnswer,
    ReaderCandidateValueError,
    assemble_candidate_value_regions,
)
from .reader_input_prep import prepare_reader_input
from .reader_observations import (
    ReaderObservationAssemblyError,
    ReaderObservations,
    assemble_reader_capture,
)
from .reader_semantic_answers import (
    ReaderSemanticAnswerError,
    ReaderSemanticAnswers,
    merge_region_semantic_answers,
)
from .reader_semantic_compact import (
    CompactRegionSemanticAnswer,
    ReaderSemanticCompactError,
    assemble_compact_regions,
)
from .reader_semantic_queries import (
    ReaderSemanticQueryError,
    ReaderSemanticQueryPlan,
    build_reader_semantic_queries,
)
from .reader_visual_aid import build_reader_visual_aid
from .resolver import resolve_evidence_graph
from .stability import compare_evidence_runs


def _load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("evidence JSON root must be an object")
    return data


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".semantic-draft-",
        suffix=".tmp",
        dir=str(output.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _cmd_prepare_reader_input(args: argparse.Namespace) -> int:
    image_path = str(Path(args.image).resolve())
    workspace_root = str(Path(args.workspace_root).resolve())
    report: dict[str, Any] = {
        "image": image_path,
        "workspace_root": workspace_root,
        "written": False,
        "reader_input": None,
        "summary": {},
        "timing_ms": {},
        "errors": [],
    }

    try:
        result = prepare_reader_input(image_path, workspace_root)
    except (OSError, RuntimeError, ValueError) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report.update(result)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_extract_raster_evidence(args: argparse.Namespace) -> int:
    image_path = str(Path(args.image).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "image": image_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "region_count": 0,
        "dimension_geometry_candidate_count": 0,
        "errors": [],
    }

    try:
        output = extract_raw_evidence(image_path)
        _atomic_write_json(output_path, output)
    except (OSError, RuntimeError, ValueError) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = output.get("schema")
    summary = output.get("summary", {})
    report["region_count"] = summary.get("region_count", 0)
    report["dimension_geometry_candidate_count"] = summary.get(
        "dimension_geometry_candidate_count",
        0,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_build_reader_visual_aid(args: argparse.Namespace) -> int:
    raw_path = str(Path(args.raw_evidence).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "raw_evidence": raw_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "bucket_count": 0,
        "overflow_bucket_count": 0,
        "max_bucket_candidate_count": 0,
        "errors": [],
    }

    try:
        raw = _load_json(raw_path)
        output = build_reader_visual_aid(raw)
        _atomic_write_json(output_path, output)
    except (
        OSError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
        ValidationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = output.get("schema")
    summary = output.get("summary", {})
    report["bucket_count"] = summary.get("bucket_count", 0)
    report["overflow_bucket_count"] = summary.get(
        "overflow_bucket_count",
        0,
    )
    report["max_bucket_candidate_count"] = summary.get(
        "max_bucket_candidate_count",
        0,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_build_reader_candidate_queries(args: argparse.Namespace) -> int:
    reader_input_path = str(Path(args.reader_input).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "reader_input": reader_input_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "query_count": 0,
        "target_count": 0,
        "overflow_bucket_count": 0,
        "errors": [],
    }

    try:
        reader_input = _load_json(reader_input_path)
        visual_aid_path = reader_input.get("reader_visual_aid_path")
        if not isinstance(visual_aid_path, str) or not visual_aid_path:
            raise ValueError("reader input requires reader_visual_aid_path")
        visual_aid = _load_json(visual_aid_path)
        plan = build_reader_candidate_queries(reader_input, visual_aid)
        _atomic_write_json(
            output_path,
            plan.model_dump(mode="json", by_alias=True),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderCandidateQueryError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = plan.schema_version
    report["query_count"] = len(plan.queries)
    report["target_count"] = sum(len(query.dimension_targets) for query in plan.queries)
    report["overflow_bucket_count"] = sum(len(query.overflow_buckets) for query in plan.queries)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_assemble_reader_candidate_regions(args: argparse.Namespace) -> int:
    query_plan_path = str(Path(args.query_plan).resolve())
    regions_dir = Path(args.regions_dir).resolve()
    partial_path = str(Path(args.partial_out).resolve())
    report: dict[str, Any] = {
        "query_plan": query_plan_path,
        "regions_dir": str(regions_dir),
        "partial": partial_path,
        "written": False,
        "schema": None,
        "query_count": 0,
        "entity_count": 0,
        "dimension_count": 0,
        "unresolved_count": 0,
        "errors": [],
    }

    try:
        plan = ReaderCandidateQueryPlan.model_validate(_load_json(query_plan_path))
        region_answers: list[CandidateRegionAnswer] = []
        for query in plan.queries:
            region_path = regions_dir / f"reader-candidate-{query.query_id}.json"
            region_answers.append(
                CandidateRegionAnswer.model_validate(_load_json(str(region_path)))
            )
        partial = assemble_candidate_regions(plan, region_answers)
        _atomic_write_json(
            partial_path,
            partial.model_dump(mode="json", by_alias=True),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderCandidateAnswerError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = partial.schema_version
    report["query_count"] = len(plan.queries)
    report["entity_count"] = len(partial.entities)
    report["dimension_count"] = len(partial.dimensions)
    report["unresolved_count"] = len(partial.unresolved)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_assemble_reader_candidate_values(args: argparse.Namespace) -> int:
    query_plan_path = str(Path(args.query_plan).resolve())
    regions_dir = Path(args.regions_dir).resolve()
    partial_path = str(Path(args.partial_out).resolve())
    report: dict[str, Any] = {
        "query_plan": query_plan_path,
        "regions_dir": str(regions_dir),
        "partial": partial_path,
        "written": False,
        "schema": None,
        "query_count": 0,
        "entity_count": 0,
        "dimension_count": 0,
        "unresolved_count": 0,
        "errors": [],
    }

    try:
        plan = ReaderCandidateQueryPlan.model_validate(_load_json(query_plan_path))
        region_answers: list[CandidateValueRegionAnswer] = []
        for query in plan.queries:
            region_path = regions_dir / f"reader-candidate-value-{query.query_id}.json"
            region_answers.append(
                CandidateValueRegionAnswer.model_validate(_load_json(str(region_path)))
            )
        partial = assemble_candidate_value_regions(plan, region_answers)
        _atomic_write_json(
            partial_path,
            partial.model_dump(mode="json", by_alias=True),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderCandidateValueError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = partial.schema_version
    report["query_count"] = len(plan.queries)
    report["entity_count"] = len(partial.entities)
    report["dimension_count"] = len(partial.dimensions)
    report["unresolved_count"] = len(partial.unresolved)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_build_reader_semantic_queries(args: argparse.Namespace) -> int:
    reader_input_path = str(Path(args.reader_input).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "reader_input": reader_input_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "query_count": 0,
        "errors": [],
    }

    try:
        reader_input = _load_json(reader_input_path)
        plan = build_reader_semantic_queries(reader_input)
        payload = plan.model_dump(mode="json", by_alias=True)
        _atomic_write_json(output_path, payload)
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderSemanticQueryError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = plan.schema_version
    report["query_count"] = len(plan.queries)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_merge_reader_semantic_answers(args: argparse.Namespace) -> int:
    query_plan_path = str(Path(args.query_plan).resolve())
    answers_path = str(Path(args.answers).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "query_plan": query_plan_path,
        "answers": answers_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "view_count": 0,
        "entity_count": 0,
        "dimension_count": 0,
        "errors": [],
    }

    try:
        plan = ReaderSemanticQueryPlan.model_validate(_load_json(query_plan_path))
        answers = ReaderSemanticAnswers.model_validate(_load_json(answers_path))
        partial = merge_region_semantic_answers(plan, answers)
        payload = partial.model_dump(mode="json", by_alias=True)
        _atomic_write_json(output_path, payload)
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderSemanticAnswerError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = partial.schema_version
    report["view_count"] = len(partial.views)
    report["entity_count"] = len(partial.entities)
    report["dimension_count"] = len(partial.dimensions)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_assemble_reader_semantic_regions(args: argparse.Namespace) -> int:
    query_plan_path = str(Path(args.query_plan).resolve())
    regions_dir = Path(args.regions_dir).resolve()
    answers_path = str(Path(args.answers_out).resolve())
    partial_path = str(Path(args.partial_out).resolve())
    report: dict[str, Any] = {
        "query_plan": query_plan_path,
        "regions_dir": str(regions_dir),
        "answers": answers_path,
        "partial": partial_path,
        "written": False,
        "schema": None,
        "query_count": 0,
        "entity_count": 0,
        "dimension_count": 0,
        "errors": [],
    }

    try:
        plan = ReaderSemanticQueryPlan.model_validate(_load_json(query_plan_path))
        region_answers: list[CompactRegionSemanticAnswer] = []
        for query in plan.queries:
            region_path = regions_dir / f"reader-semantic-{query.query_id}.json"
            region_answers.append(
                CompactRegionSemanticAnswer.model_validate(
                    _load_json(str(region_path))
                )
            )

        strict, partial = assemble_compact_regions(plan, region_answers)
        _atomic_write_json(
            answers_path,
            strict.model_dump(mode="json", by_alias=True),
        )
        _atomic_write_json(
            partial_path,
            partial.model_dump(mode="json", by_alias=True),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderSemanticCompactError,
        ReaderSemanticAnswerError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = partial.schema_version
    report["query_count"] = len(plan.queries)
    report["entity_count"] = len(partial.entities)
    report["dimension_count"] = len(partial.dimensions)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_assemble_reader_capture(args: argparse.Namespace) -> int:
    observations_path = str(Path(args.observations).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "observations": observations_path,
        "output": output_path,
        "written": False,
        "schema": None,
        "capture_schema_version": None,
        "view_count": 0,
        "entity_count": 0,
        "dimension_count": 0,
        "unresolved_count": 0,
        "errors": [],
    }

    try:
        raw = _load_json(observations_path)
        observations = ReaderObservations.model_validate(raw)
        capture = assemble_reader_capture(observations)
        _atomic_write_json(output_path, capture.model_dump(mode="json"))
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ReaderObservationAssemblyError,
        ValueError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["schema"] = observations.schema_version
    report["capture_schema_version"] = capture.schema_version
    report["view_count"] = len(capture.views)
    report["entity_count"] = len(capture.entities)
    report["dimension_count"] = len(capture.dimensions)
    report["unresolved_count"] = len(capture.unresolved_evidence)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_check_capture(args: argparse.Namespace) -> int:
    capture_path = str(Path(args.capture).resolve())
    report: dict[str, Any] = {
        "capture": capture_path,
        "schema_valid": False,
        "contract_valid": False,
        "errors": [],
    }

    try:
        raw = _load_json(capture_path)
        capture = ReaderCapture.model_validate(raw)
        report["schema_valid"] = True
        contract_errors = validate_reader_capture_contract(capture)
        if contract_errors:
            report["errors"].extend(contract_errors)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["contract_valid"] = True
        report.update(
            {
                "views": len(capture.views),
                "entities": len(capture.entities),
                "associations": len(capture.associations),
                "values": len(capture.values),
                "dimensions": len(capture.dimensions),
                "datum_alignments": len(capture.datum_alignments),
                "required_targets": len(capture.required_targets),
                "unresolved_evidence": len(capture.unresolved_evidence),
            }
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_link_capture(args: argparse.Namespace) -> int:
    capture_path = str(Path(args.capture).resolve())
    evidence_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "capture": capture_path,
        "drawing_evidence": evidence_path,
        "written": False,
        "schema_valid": False,
        "contract_valid": False,
        "errors": [],
    }

    if os.path.normcase(capture_path) == os.path.normcase(evidence_path):
        report["errors"].append(
            "reader capture input and drawing evidence output must differ"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        raw = _load_json(capture_path)
        capture = ReaderCapture.model_validate(raw)
        report["schema_valid"] = True

        contract_errors = validate_reader_capture_contract(capture)
        if contract_errors:
            report["errors"].extend(contract_errors)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["contract_valid"] = True

        linked = link_reader_capture(capture)

        gate0 = write_strict_evidence(
            linked.evidence.model_dump(mode="json")
        )
        output = gate0.evidence.model_dump(mode="json")
        _atomic_write_json(evidence_path, output)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        IdentityLinkError,
        Gate0Error,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report.update(
        {
            "written": True,
            "schema_valid": True,
            "contract_valid": True,
            "capture_entities": linked.report["capture_entities"],
            "physical_components": linked.report["physical_components"],
            "association_claims": linked.report["association_claims"],
            "rejected_associations": linked.report["rejected_associations"],
            "identity_collisions": linked.report["identity_collisions"],
            "linker_blocking_unresolved": linked.report["blocking_unresolved"],
            "gate0_added_blocking_unresolved": gate0.report[
                "added_blocking_unresolved"
            ],
            "total_unresolved": gate0.report["total_unresolved"],
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0

def _cmd_gate0(args: argparse.Namespace) -> int:
    capture_path = str(Path(args.capture).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "capture": capture_path,
        "drawing_evidence": output_path,
        "written": False,
        "schema_valid": False,
        "errors": [],
    }

    if os.path.normcase(capture_path) == os.path.normcase(output_path):
        report["errors"].append("reader capture input and strict evidence output must differ")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        raw = _load_json(capture_path)
        result = write_strict_evidence(raw)
        output = result.evidence.model_dump(mode="json")
        _atomic_write_json(output_path, output)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        Gate0Error,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report.update(result.report)
    report["written"] = True
    report["schema_valid"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    evidence_path = str(Path(args.evidence).resolve())
    draft_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "evidence": evidence_path,
        "semantic_draft": draft_path,
        "written": False,
        "ok": False,
        "errors": [],
    }

    if os.path.normcase(evidence_path) == os.path.normcase(draft_path):
        report["errors"].append("evidence input and semantic draft output must differ")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        raw = _load_json(evidence_path)
        graph = EvidenceGraph.model_validate(raw)
        compiled = compile_evidence_graph(graph)
        resolution = resolve_evidence_graph(compiled)
        draft = build_semantic_draft(compiled, resolution)
        _atomic_write_json(draft_path, draft)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        EvidenceCompileError,
        DraftAssemblyError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report.update(
        {
            "written": True,
            "ok": resolution.ok,
            "compiled_direct_values": len(compiled.direct_values),
            "compiled_relations": len(compiled.relations),
            "resolved_values": len(resolution.values),
            "derived_values": len(resolution.derivations),
            "blocking_unresolved": sum(
                1
                for item in resolution.unresolved
                if item.get("required_for_modeling", True)
            ),
            "conflicts": len(resolution.conflicts),
            "dimension_closure": draft["dimension_closure"]["status"],
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if resolution.ok else 2


def _cmd_reduce_dimension_candidates(args: argparse.Namespace) -> int:
    raw_path = str(Path(args.raw_evidence).resolve())
    hints_path = str(Path(args.hints).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "raw_evidence": raw_path,
        "hints": hints_path,
        "output": output_path,
        "written": False,
        "dimension_count": 0,
        "errors": [],
    }

    try:
        raw = _load_json(raw_path)
        hints_payload = _load_json(hints_path)
        hints = hints_payload.get("dimensions", [])
        if not isinstance(hints, list):
            raise ValueError("hints.dimensions must be a list")

        reduced: list[dict[str, Any]] = []
        for item in hints:
            if not isinstance(item, dict):
                raise ValueError("each dimension hint must be an object")
            dimension_id = item.get("dimension_id")
            label = item.get("label")
            query = DimensionCandidateQuery.model_validate(
                {
                    "region_id": item.get("region_id"),
                    "orientation": item.get("orientation"),
                    "band": item.get("band"),
                    "max_candidates": item.get("max_candidates", 4),
                }
            )
            result = reduce_dimension_candidates(raw, query)
            reduced.append(
                {
                    "dimension_id": dimension_id,
                    "label": label,
                    **result,
                }
            )

        payload = {
            "schema_version": "1.0",
            "dimension_count": len(reduced),
            "dimensions": reduced,
        }
        _atomic_write_json(output_path, payload)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["dimension_count"] = len(reduced)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_anchor_dimension_candidates(args: argparse.Namespace) -> int:
    raw_path = str(Path(args.raw_evidence).resolve())
    reduced_path = str(Path(args.reduced).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "raw_evidence": raw_path,
        "reduced": reduced_path,
        "output": output_path,
        "written": False,
        "candidate_count": 0,
        "witness_count": 0,
        "errors": [],
    }

    try:
        raw = _load_json(raw_path)
        reduced = _load_json(reduced_path)
        output = enrich_reduced_dimension_candidates(
            raw,
            reduced,
            nearest_count=args.nearest_count,
            max_distance_local_norm=args.max_distance_local_norm,
        )
        _atomic_write_json(output_path, output)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["candidate_count"] = output["anchor_summary"]["candidate_count"]
    report["witness_count"] = output["anchor_summary"]["witness_count"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_request_confirmations(args: argparse.Namespace) -> int:
    evidence_path = str(Path(args.evidence).resolve())
    request_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "evidence": evidence_path,
        "confirmation_request": request_path,
        "written": False,
        "question_count": 0,
        "eligible_for_user_confirmation": False,
        "unconfirmable_blocking_ids": [],
        "errors": [],
    }

    if os.path.normcase(evidence_path) == os.path.normcase(request_path):
        report["errors"].append(
            "evidence input and confirmation request output must differ"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        graph = EvidenceGraph.model_validate(_load_json(evidence_path))
        request = build_confirmation_request(graph)
        _atomic_write_json(request_path, request)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        ConfirmationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["question_count"] = request["question_count"]
    report["eligible_for_user_confirmation"] = request[
        "eligible_for_user_confirmation"
    ]
    report["unconfirmable_blocking_ids"] = request[
        "unconfirmable_blocking_ids"
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_apply_confirmations(args: argparse.Namespace) -> int:
    evidence_path = str(Path(args.evidence).resolve())
    answers_path = str(Path(args.answers).resolve())
    output_path = str(Path(args.out).resolve())
    report: dict[str, Any] = {
        "evidence": evidence_path,
        "answers": answers_path,
        "confirmed_evidence": output_path,
        "written": False,
        "applied_confirmations": 0,
        "remaining_confirmation_questions": 0,
        "errors": [],
    }

    if os.path.normcase(evidence_path) == os.path.normcase(output_path):
        report["errors"].append(
            "evidence input and confirmed evidence output must differ"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    try:
        graph = EvidenceGraph.model_validate(_load_json(evidence_path))
        answers = ConfirmationAnswers.model_validate(_load_json(answers_path))
        confirmed = apply_confirmation_answers(graph, answers)
        _atomic_write_json(
            output_path,
            confirmed.model_dump(mode="json"),
        )
        before = build_confirmation_request(graph)["question_count"]
        after = build_confirmation_request(confirmed)["question_count"]
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        ConfirmationError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["written"] = True
    report["applied_confirmations"] = max(0, before - after)
    report["remaining_confirmation_questions"] = after
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_stability(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {
        "stable": False,
        "run_count": 0,
        "unique_fingerprints": 0,
        "errors": [],
    }
    try:
        if len(args.evidence) < 2:
            raise ValueError("stability comparison requires at least two evidence files")
        graphs = [
            EvidenceGraph.model_validate(_load_json(str(Path(path).resolve())))
            for path in args.evidence
        ]
        result = compare_evidence_runs(graphs)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        EvidenceCompileError,
        DraftAssemblyError,
    ) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        if args.report:
            try:
                _atomic_write_json(args.report, report)
            except OSError as write_exc:
                report["errors"].append(
                    f"report write failed: {type(write_exc).__name__}: {write_exc}"
                )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = result.to_dict()
    if not args.include_snapshots:
        report.pop("snapshots", None)

    if args.report:
        _atomic_write_json(args.report, report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.stable else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nx_mcp.drawing_intelligence",
        description="Deterministic drawing-evidence compiler and resolver",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_reader = sub.add_parser(
        "prepare-reader-input",
        help="prepare deterministic Reader JSON and crops from the current raster",
    )
    prepare_reader.add_argument("image")
    prepare_reader.add_argument("workspace_root")
    prepare_reader.set_defaults(func=_cmd_prepare_reader_input)

    extract_raster = sub.add_parser(
        "extract-raster-evidence",
        help="extract geometry-only RawEvidence v1 from a raster engineering drawing",
    )
    extract_raster.add_argument("image")
    extract_raster.add_argument("out")
    extract_raster.set_defaults(func=_cmd_extract_raster_evidence)

    build_visual_aid = sub.add_parser(
        "build-reader-visual-aid",
        help="build bounded geometry-only Reader aid from RawEvidence v1",
    )
    build_visual_aid.add_argument("raw_evidence")
    build_visual_aid.add_argument("out")
    build_visual_aid.set_defaults(func=_cmd_build_reader_visual_aid)

    candidate_queries = sub.add_parser(
        "build-reader-candidate-queries",
        help="build candidate-addressed dimension semantic questions",
    )
    candidate_queries.add_argument("reader_input")
    candidate_queries.add_argument("out")
    candidate_queries.set_defaults(func=_cmd_build_reader_candidate_queries)

    assemble_candidate_regions = sub.add_parser(
        "assemble-reader-candidate-regions",
        help="assemble per-region candidate answers into partial Reader observations",
    )
    assemble_candidate_regions.add_argument("query_plan")
    assemble_candidate_regions.add_argument("regions_dir")
    assemble_candidate_regions.add_argument("partial_out")
    assemble_candidate_regions.set_defaults(func=_cmd_assemble_reader_candidate_regions)

    assemble_candidate_values = sub.add_parser(
        "assemble-reader-candidate-values",
        help="assemble value-only candidate answers into partial Reader observations",
    )
    assemble_candidate_values.add_argument("query_plan")
    assemble_candidate_values.add_argument("regions_dir")
    assemble_candidate_values.add_argument("partial_out")
    assemble_candidate_values.set_defaults(func=_cmd_assemble_reader_candidate_values)

    semantic_queries = sub.add_parser(
        "build-reader-semantic-queries",
        help="build bounded region-local semantic questions from reader-input-v1",
    )
    semantic_queries.add_argument("reader_input")
    semantic_queries.add_argument("out")
    semantic_queries.set_defaults(func=_cmd_build_reader_semantic_queries)

    merge_semantic_answers = sub.add_parser(
        "merge-reader-semantic-answers",
        help="merge bounded region answers into partial Reader observations",
    )
    merge_semantic_answers.add_argument("query_plan")
    merge_semantic_answers.add_argument("answers")
    merge_semantic_answers.add_argument("out")
    merge_semantic_answers.set_defaults(func=_cmd_merge_reader_semantic_answers)

    assemble_semantic_regions = sub.add_parser(
        "assemble-reader-semantic-regions",
        help="assemble compact per-region semantic files into strict answers and partial observations",
    )
    assemble_semantic_regions.add_argument("query_plan")
    assemble_semantic_regions.add_argument("regions_dir")
    assemble_semantic_regions.add_argument("answers_out")
    assemble_semantic_regions.add_argument("partial_out")
    assemble_semantic_regions.set_defaults(func=_cmd_assemble_reader_semantic_regions)

    assemble_capture = sub.add_parser(
        "assemble-reader-capture",
        help="compile compact Reader observations into validated ReaderCapture v2",
    )
    assemble_capture.add_argument("observations")
    assemble_capture.add_argument("out")
    assemble_capture.set_defaults(func=_cmd_assemble_reader_capture)

    check_capture = sub.add_parser(
        "check-capture",
        help="validate Reader Capture v2 schema and current production contract",
    )
    check_capture.add_argument("capture")
    check_capture.set_defaults(func=_cmd_check_capture)

    link_capture = sub.add_parser(
        "link-capture",
        help=(
            "compile Reader Capture v2 view-local observations into strict "
            "drawing evidence"
        ),
    )
    link_capture.add_argument("capture")
    link_capture.add_argument("out")
    link_capture.set_defaults(func=_cmd_link_capture)

    gate0 = sub.add_parser(
        "gate0",
        help="convert loose Reader capture into strict schema-valid drawing evidence",
    )
    gate0.add_argument("capture")
    gate0.add_argument("out")
    gate0.set_defaults(func=_cmd_gate0)

    resolve = sub.add_parser(
        "resolve",
        help="compile/resolve drawing-evidence.json into semantic-draft.json",
    )
    resolve.add_argument("evidence")
    resolve.add_argument("out")
    resolve.set_defaults(func=_cmd_resolve)

    reduce_candidates = sub.add_parser(
        "reduce-dimension-candidates",
        help="reduce raw raster dimension candidates using bounded geometry hints",
    )
    reduce_candidates.add_argument("raw_evidence")
    reduce_candidates.add_argument("hints")
    reduce_candidates.add_argument("out")
    reduce_candidates.set_defaults(func=_cmd_reduce_dimension_candidates)

    anchor_candidates = sub.add_parser(
        "anchor-dimension-candidates",
        help="attach geometry-only nearest anchors to reduced dimension candidates",
    )
    anchor_candidates.add_argument("raw_evidence")
    anchor_candidates.add_argument("reduced")
    anchor_candidates.add_argument("out")
    anchor_candidates.add_argument(
        "--nearest-count",
        type=int,
        default=3,
        help="number of nearest geometry anchors per witness (1..5)",
    )
    anchor_candidates.add_argument(
        "--max-distance-local-norm",
        type=float,
        default=0.04,
        help="maximum normalized witness-to-anchor distance (0, 0.25]",
    )
    anchor_candidates.set_defaults(func=_cmd_anchor_dimension_candidates)

    request_confirmations = sub.add_parser(
        "request-confirmations",
        help="write bounded human questions for unresolved dimension endpoints",
    )
    request_confirmations.add_argument("evidence")
    request_confirmations.add_argument("out")
    request_confirmations.set_defaults(func=_cmd_request_confirmations)

    apply_confirmations = sub.add_parser(
        "apply-confirmations",
        help="apply validated human endpoint choices to evidence",
    )
    apply_confirmations.add_argument("evidence")
    apply_confirmations.add_argument("answers")
    apply_confirmations.add_argument("out")
    apply_confirmations.set_defaults(func=_cmd_apply_confirmations)

    stability = sub.add_parser(
        "stability",
        help="compare independent drawing-evidence runs for semantic drift",
    )
    stability.add_argument(
        "evidence",
        nargs="+",
        help="two or more independent drawing-evidence JSON files",
    )
    stability.add_argument(
        "--report",
        help="optional JSON path for the stability report",
    )
    stability.add_argument(
        "--include-snapshots",
        action="store_true",
        help="include normalized logical snapshots in stdout/report",
    )
    stability.set_defaults(func=_cmd_stability)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
