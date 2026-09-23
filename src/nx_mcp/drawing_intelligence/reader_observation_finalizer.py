from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .evidence import Axis, OverallDimensions
from .reader_observations import ReaderObservations
from .reader_semantic_answers import PartialOverallDimensionFact, PartialReaderObservations


class ReaderObservationFinalizationError(ValueError):
    """Raised when partial Reader observations cannot be finalized without inference."""


_OVERALL_FIELD_BY_AXIS: dict[Axis, str] = {
    "X": "length_x",
    "Y": "width_y",
    "Z": "height_z",
}


def _overall_dimensions(
    facts: list[PartialOverallDimensionFact],
) -> OverallDimensions:
    by_axis: dict[Axis, list[PartialOverallDimensionFact]] = {
        "X": [],
        "Y": [],
        "Z": [],
    }
    for fact in facts:
        by_axis[fact.axis].append(fact)

    values: dict[str, float] = {}
    for axis in ("X", "Y", "Z"):
        axis_facts = by_axis[axis]
        if not axis_facts:
            raise ReaderObservationFinalizationError(
                f"missing overall dimension fact for axis {axis}"
            )

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

        values[_OVERALL_FIELD_BY_AXIS[axis]] = reference

    return OverallDimensions.model_validate(values)


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

    overall = _overall_dimensions(partial.overall_dimension_facts)
    overall_ledger: dict[str, Any] = {
        "kind": "overall_dimension_fact_ledger",
        "facts": [
            fact.model_dump(mode="json")
            for fact in partial.overall_dimension_facts
        ],
    }

    return ReaderObservations(
        overall_dimensions=overall,
        views=partial.views,
        entities=partial.entities,
        values=partial.values,
        dimensions=partial.dimensions,
        datum_alignments=partial.datum_alignments,
        observations=[
            *partial.observations,
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
