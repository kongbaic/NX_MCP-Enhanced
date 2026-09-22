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
from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import EvidenceGraph
from .gate0 import Gate0Error, write_strict_evidence
from .identity_linker import IdentityLinkError, link_reader_capture
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
