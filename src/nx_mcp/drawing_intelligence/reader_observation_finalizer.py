from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .evidence import Axis, OverallDimensions
from .reader_observations import ReaderObservations
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialReaderObservations,
    PartialRotationalSymmetryFact,
)


class ReaderObservationFinalizationError(ValueError):
    """Raised when partial Reader observations cannot be finalized without inference."""


_OVERALL_FIELD_BY_AXIS: dict[Axis, str] = {
    "X": "length_x",
    "Y": "width_y",
    "Z": "height_z",
}


_PIXEL_DERIVED_METRIC_OBSERVATION_KINDS = frozenset(
    {
        "hybrid_view_metric_calibration_ledger",
        "hybrid_metric_profile_edge_ledger",
        "hybrid_metric_profile_segment_ledger",
        "hybrid_metric_circle_primitive_ledger",
    }
)


def _reject_pixel_derived_metric_observations(
    observations: list[dict[str, Any]],
) -> None:
    """Keep pixel-derived millimeter estimates out of canonical Reader output."""

    forbidden = sorted(
        {
            str(item.get("kind") or "")
            for item in observations
            if isinstance(item, dict)
            and str(item.get("kind") or "")
            in _PIXEL_DERIVED_METRIC_OBSERVATION_KINDS
        }
    )
    if forbidden:
        raise ReaderObservationFinalizationError(
            "pixel-derived metric observations are diagnostic-only and cannot "
            "enter canonical ReaderObservations: "
            + ", ".join(forbidden)
        )


def _overall_dimensions(
    facts: list[PartialOverallDimensionFact],
    rotational_symmetry_facts: list[PartialRotationalSymmetryFact],
) -> tuple[OverallDimensions, list[dict[str, Any]]]:
    by_axis: dict[Axis, list[PartialOverallDimensionFact]] = {
        "X": [],
        "Y": [],
        "Z": [],
    }
    for fact in facts:
        by_axis[fact.axis].append(fact)

    direct_values: dict[Axis, float] = {}
    direct_evidence: dict[Axis, list[str]] = {}
    for axis in ("X", "Y", "Z"):
        axis_facts = by_axis[axis]
        if not axis_facts:
            continue

        reference = axis_facts[0].value
        conflicting = [
            fact.value
            for fact in axis_facts[1:]
            if not math.isclose(
                fact.value,
                reference,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ]
        if conflicting:
            all_values = [fact.value for fact in axis_facts]
            raise ReaderObservationFinalizationError(
                f"conflicting overall dimension facts for axis {axis}: {all_values}"
            )

        direct_values[axis] = reference
        direct_evidence[axis] = list(
            dict.fromkeys(
                label
                for fact in axis_facts
                for label in fact.evidence
            )
        )

    symmetry_axes = {item.axis for item in rotational_symmetry_facts}
    if len(symmetry_axes) > 1:
        raise ReaderObservationFinalizationError(
            f"conflicting rotational symmetry axes: {sorted(symmetry_axes)}"
        )

    derivations: list[dict[str, Any]] = []
    rotation_axis = next(iter(symmetry_axes), None)
    symmetry_evidence = list(
        dict.fromkeys(
            label
            for item in rotational_symmetry_facts
            for label in item.evidence
        )
    )

    if rotation_axis is not None:
        transverse_axes = [
            axis for axis in ("X", "Y", "Z") if axis != rotation_axis
        ]
        left, right = transverse_axes
        if left in direct_values and right in direct_values:
            if not math.isclose(
                direct_values[left],
                direct_values[right],
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ReaderObservationFinalizationError(
                    "rotational symmetry conflicts with direct transverse overall "
                    f"facts: {left}={direct_values[left]}, "
                    f"{right}={direct_values[right]}"
                )
        elif left in direct_values or right in direct_values:
            source_axis = left if left in direct_values else right
            target_axis = right if source_axis == left else left
            value = direct_values[source_axis]
            direct_values[target_axis] = value
            evidence = list(
                dict.fromkeys(
                    [*direct_evidence[source_axis], *symmetry_evidence]
                )
            )
            derivations.append(
                {
                    "axis": target_axis,
                    "value": value,
                    "basis": "rotational_symmetry_equal_transverse_extents",
                    "source_axis": source_axis,
                    "rotation_axis": rotation_axis,
                    "evidence": evidence,
                }
            )

    for axis in ("X", "Y", "Z"):
        if axis not in direct_values:
            raise ReaderObservationFinalizationError(
                f"missing overall dimension fact for axis {axis}"
            )

    values = {
        _OVERALL_FIELD_BY_AXIS[axis]: direct_values[axis]
        for axis in ("X", "Y", "Z")
    }
    return OverallDimensions.model_validate(values), derivations


def finalize_partial_reader_observations(
    partial: PartialReaderObservations,
) -> ReaderObservations:
    """Finalize only explicitly complete partial observations.

    This function performs no view classification, axis inference, endpoint
    ownership inference, or overall-dimension guessing.
    """

    if not partial.views:
        raise ReaderObservationFinalizationError(
            "partial Reader observations require at least one explicit view"
        )

    _reject_pixel_derived_metric_observations(
        [
            item
            for item in partial.observations
            if isinstance(item, dict)
        ]
    )

    overall, overall_derivations = _overall_dimensions(
        partial.overall_dimension_facts,
        partial.rotational_symmetry_facts,
    )
    rotational_symmetry_ledger: dict[str, Any] = {
        "kind": "rotational_symmetry_fact_ledger",
        "facts": [
            fact.model_dump(mode="json")
            for fact in partial.rotational_symmetry_facts
        ],
    }
    overall_derivation_ledger: dict[str, Any] = {
        "kind": "overall_dimension_derivation_ledger",
        "facts": overall_derivations,
    }
    overall_ledger: dict[str, Any] = {
        "kind": "overall_dimension_fact_ledger",
        "facts": [fact.model_dump(mode="json") for fact in partial.overall_dimension_facts],
    }

    return ReaderObservations(
        overall_dimensions=overall,
        views=partial.views,
        entities=partial.entities,
        associations=partial.associations,
        values=partial.values,
        dimensions=partial.dimensions,
        datum_alignments=partial.datum_alignments,
        centerline_alignments=partial.centerline_alignments,
        observations=[
            *partial.observations,
            *(
                [rotational_symmetry_ledger]
                if partial.rotational_symmetry_facts
                else []
            ),
            *(
                [overall_derivation_ledger]
                if overall_derivations
                else []
            ),
            overall_ledger,
        ],
        unresolved=partial.unresolved,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("partial")
    parser.add_argument("out")
    args = parser.parse_args(argv)

    partial_path = Path(args.partial).resolve()
    output_path = Path(args.out).resolve()

    try:
        payload = json.loads(partial_path.read_text(encoding="utf-8"))
        partial = PartialReaderObservations.model_validate(payload)
        full = finalize_partial_reader_observations(partial)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                full.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "written": False,
                    "partial": str(partial_path),
                    "out": str(output_path),
                    "errors": [f"{type(exc).__name__}: {exc}"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "written": True,
                "partial": str(partial_path),
                "out": str(output_path),
                "dimension_count": len(full.dimensions),
                "unresolved_count": len(full.unresolved),
                "errors": [],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
