from __future__ import annotations

import math
import re
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Axis, ViewKind
from .hybrid_capture_adapter import (
    HybridAdapterContext,
    HybridLabeledDimensionFact,
    HybridRegionView,
)
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialRotationalSymmetryFact,
)
from .short_dimension_orientation import (
    infer_labeled_dimension_axis_span,
    infer_short_dimension_visual_direction,
    infer_short_dimension_visual_topology,
)


class StructuralContextError(ValueError):
    """Raised when minimal structural context cannot be assembled safely."""


_REGION_LOCAL_DEFERRED_UNRESOLVED = {
    "rotational_symmetry_not_visible_in_region",
}
_NON_GEOMETRIC_REFERENCE_REGION = "non_geometric_reference_region"


class _StrictStructuralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _clean_evidence(value: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ValueError("evidence must contain at least one non-empty label")
    return cleaned


class StructuralLabeledDimensionTarget(_StrictStructuralModel):
    """One OCR-read labeled linear value needing only visual relation semantics."""

    target_id: str = Field(min_length=1)
    source_item_index: int = Field(ge=0)
    source_text: str = Field(min_length=1)
    value: float = Field(gt=0)
    deterministic_visual_direction: Literal["horizontal", "vertical"] | None = None
    deterministic_relation_seed: Literal[
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    ] | None = None


_LABELED_MM_DIMENSION_RE = re.compile(
    r"(?i)(?P<label>[a-z][a-z0-9_]*)\s*[-=:]\s*"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*mm[a-z]?(?:\b|$)"
)
_FRAGMENT_LABEL_RE = re.compile(r"(?i)^\s*(?P<label>[a-z][a-z0-9_]*)\s*$")
_FRAGMENT_VALUE_WITH_UNIT_RE = re.compile(
    r"(?i)^\s*(?P<value>\d+(?:[.,]\d+)?)\s*mm[a-z]?\s*$"
)


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _ocr_bbox_rect(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, list):
        return None
    points = [
        point
        for point in raw
        if (
            isinstance(point, list)
            and len(point) >= 2
            and not isinstance(point[0], bool)
            and not isinstance(point[1], bool)
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        )
    ]
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def _bbox_vertical_overlap_fraction(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    _first_x, first_y, _first_width, first_height = first
    _second_x, second_y, _second_width, second_height = second
    overlap = min(
        first_y + first_height,
        second_y + second_height,
    ) - max(first_y, second_y)
    if overlap <= 0.0:
        return 0.0
    return overlap / max(1.0, min(first_height, second_height))


def _fragmented_labeled_dimension_items(
    raw_items: list[object],
) -> list[dict[str, object]]:
    """Recover only unambiguous label + complete value-with-unit OCR splits.

    The engineering value must already be complete in one OCR item, such as
    "28 mm". This helper never reconstructs missing digits, decimal points,
    or units from multiple fragments.
    """

    labels: list[tuple[str, int, tuple[float, float, float, float]]] = []
    values: list[
        tuple[dict[str, object], float, tuple[float, float, float, float]]
    ] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        text = item.get("text")
        bbox = _ocr_bbox_rect(item.get("bbox"))
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index < 0
            or not isinstance(text, str)
            or bbox is None
        ):
            continue

        label_match = _FRAGMENT_LABEL_RE.fullmatch(text)
        if label_match is not None:
            labels.append((label_match.group("label"), source_index, bbox))
            continue

        value_match = _FRAGMENT_VALUE_WITH_UNIT_RE.fullmatch(text)
        if value_match is None:
            continue
        parsed_value = _positive_number(value_match.group("value"))
        token_value = _positive_number(item.get("token"))
        if (
            parsed_value is None
            or token_value is None
            or not math.isclose(
                parsed_value,
                token_value,
                abs_tol=max(abs(token_value) * 1e-6, 1e-9),
            )
        ):
            continue
        values.append((item, parsed_value, bbox))

    output: list[dict[str, object]] = []
    for value_item, value, value_bbox in values:
        value_x, value_y, value_width, value_height = value_bbox
        candidates: list[
            tuple[float, str, int, tuple[float, float, float, float]]
        ] = []
        for label, label_source_index, label_bbox in labels:
            label_x, _label_y, label_width, label_height = label_bbox
            gap = value_x - (label_x + label_width)
            if gap < -2.0:
                continue
            max_gap = max(24.0, min(label_height, value_height) * 1.5)
            if gap > max_gap:
                continue
            overlap = _bbox_vertical_overlap_fraction(label_bbox, value_bbox)
            if overlap < 0.60:
                continue
            candidates.append((gap, label, label_source_index, label_bbox))

        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        if len(candidates) != 1:
            continue

        _gap, label, label_source_index, label_bbox = candidates[0]
        label_x, label_y, label_width, label_height = label_bbox
        left = min(label_x, value_x)
        top = min(label_y, value_y)
        right = max(label_x + label_width, value_x + value_width)
        bottom = max(label_y + label_height, value_y + value_height)
        output.append(
            {
                **value_item,
                "text": f"{label} - {value:g} mm",
                "bbox": [
                    [left, top],
                    [right, top],
                    [right, bottom],
                    [left, bottom],
                ],
                "fragment_label_source_item_index": label_source_index,
                "fragmented_labeled_dimension": True,
            }
        )

    return output


def _region_source_bbox(region: dict) -> tuple[float, float, float, float] | None:
    raw = region.get("source_bbox_px")
    if not (
        isinstance(raw, list)
        and len(raw) == 4
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in raw
        )
    ):
        return None
    x, y, width, height = (float(value) for value in raw)
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _rect_rect_distance(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    first_right = first_x + first_width
    first_bottom = first_y + first_height
    second_right = second_x + second_width
    second_bottom = second_y + second_height
    dx = max(
        second_x - first_right,
        first_x - second_right,
        0.0,
    )
    dy = max(
        second_y - first_bottom,
        first_y - second_bottom,
        0.0,
    )
    return math.hypot(dx, dy)


def _deterministic_labeled_relation_seed(
    *,
    source_raster_path: str | None,
    raw_bbox: object,
    region_id: str,
    deterministic_visual_direction: Literal["horizontal", "vertical"] | None,
    profile_inventory: list[object],
) -> Literal[
    "overall_extent",
    "overall_min_to_profile_transition",
    "overall_max_to_profile_transition",
    "between_profile_boundaries",
] | None:
    """Resolve only topology-provable short labeled-dimension relations.

    Raster positions are identity/topology evidence only. No pixel distance is
    converted into an engineering value. The seed is intentionally conservative:
    every plausible witness pair must map uniquely to the same pair of supported
    structural profile boundaries and therefore to the same relation family.
    """

    if (
        source_raster_path is None
        or deterministic_visual_direction is None
        or not profile_inventory
    ):
        return None

    topology = infer_short_dimension_visual_topology(
        source_raster_path,
        raw_bbox,
    )
    if topology is None or topology[0] != deterministic_visual_direction:
        return None

    expected_profile_orientation = (
        "vertical"
        if deterministic_visual_direction == "horizontal"
        else "horizontal"
    )
    candidates: list[
        tuple[float, float, str | None, str]
    ] = []
    for item in profile_inventory:
        if (
            not isinstance(item, dict)
            or item.get("kind") != "profile_edge_candidate"
            or str(item.get("region_id") or "") != region_id
            or str(item.get("source_orientation") or "")
            != expected_profile_orientation
        ):
            continue
        position = item.get("position_px")
        if (
            not isinstance(position, (int, float))
            or isinstance(position, bool)
        ):
            continue
        non_dimension_support = item.get(
            "non_dimension_crossing_source_count"
        )
        independent_support = item.get(
            "independent_geometry_source_count",
            0,
        )
        if not (
            (
                isinstance(non_dimension_support, int)
                and not isinstance(non_dimension_support, bool)
                and non_dimension_support > 0
            )
            or (
                isinstance(independent_support, int)
                and not isinstance(independent_support, bool)
                and independent_support >= 2
            )
        ):
            continue
        axis_tolerance = item.get("axis_tolerance_px")
        tolerance = max(
            5.0,
            float(axis_tolerance)
            if (
                isinstance(axis_tolerance, (int, float))
                and not isinstance(axis_tolerance, bool)
            )
            else 0.0,
        )
        extreme = item.get("relative_extreme_side")
        candidates.append(
            (
                float(position),
                tolerance,
                str(extreme) if extreme in {"min", "max"} else None,
                str(item.get("ref") or ""),
            )
        )

    if not candidates:
        return None

    def _match_profile(
        position: float,
    ) -> tuple[float, float, str | None, str] | None:
        matches = [
            candidate
            for candidate in candidates
            if abs(candidate[0] - float(position)) <= candidate[1]
        ]
        unique_refs = {
            candidate[3]
            for candidate in matches
            if candidate[3]
        }
        if len(matches) != 1 or len(unique_refs) != 1:
            return None
        return matches[0]

    resolved_relations: list[
        Literal[
            "overall_extent",
            "overall_min_to_profile_transition",
            "overall_max_to_profile_transition",
            "between_profile_boundaries",
        ]
    ] = []
    for pair in topology[1]:
        first = _match_profile(float(pair[0]))
        second = _match_profile(float(pair[1]))
        if first is None or second is None or first[3] == second[3]:
            return None

        first_extreme = first[2]
        second_extreme = second[2]
        extremes = {
            item
            for item in (first_extreme, second_extreme)
            if item is not None
        }

        # These physical edge candidates are region-relative, not a proven
        # whole-part overall. Do not turn region extrema into overall
        # dimensions or overall-contact relations before the assembler/adapter
        # has global view ownership evidence. Only two uniquely identified
        # *internal* profile boundaries can establish this local relation.
        if extremes:
            return None
        resolved_relations.append("between_profile_boundaries")

    if not resolved_relations or len(set(resolved_relations)) != 1:
        return None
    return resolved_relations[0]


def _proven_labeled_vertical_overall(
    *,
    source_raster_path: str | None,
    raw_bbox: object,
    region_id: str,
    regions: list[object],
    profile_inventory: list[object],
) -> bool:
    """Require a labeled dimension line to span two proven material surfaces.

    This checks *identity* of the drawn arrow endpoints against a unique
    geometry-bearing region with two opposite one-sided material boundaries.
    It does not measure millimeters, infer a numeric dimension, or derive
    geometric coordinates from image pixels. The OCR target owns the value.
    Missing/ambiguous topology remains a visual-query responsibility.
    """

    if not source_raster_path:
        return False
    label_rect = _ocr_bbox_rect(raw_bbox)
    if label_rect is None:
        return False
    span = infer_labeled_dimension_axis_span(
        source_raster_path, raw_bbox, expected_direction="vertical"
    )
    if span is None:
        return False
    low, high = span
    if low >= high:
        return False

    labeled_region = next(
        (
            item for item in regions
            if isinstance(item, dict) and item.get("region_id") == region_id
        ),
        None,
    )
    if labeled_region is None:
        return False
    label_region_box = _region_source_bbox(labeled_region)
    if label_region_box is None:
        return False

    lx, ly, lw, lh = label_region_box
    text_x, _text_y, text_w, _text_h = label_rect
    owner_candidates: list[str] = []
    for other in regions:
        if not isinstance(other, dict):
            continue
        owner_id = other.get("region_id")
        if not isinstance(owner_id, str) or owner_id == region_id:
            continue
        owner_box = _region_source_bbox(other)
        if owner_box is None:
            continue
        ox, oy, ow, oh = owner_box
        # Label is outside a larger body-view region, not an inside-span
        # label. Region adjacency is only evidence identity, never mm truth.
        if (
            ow <= lw * 2
            or oh <= lh * 1.25
            or not (oy <= low < high <= oy + oh)
            or min(abs(lx - (ox + ow)), abs(ox - (lx + lw)))
            > max(160.0, ow * 0.15)
            or text_x < ox + ow - 8.0
            and text_x + text_w > ox + 8.0
        ):
            continue

        horizontal_surfaces: list[dict] = []
        for edge in profile_inventory:
            if (
                not isinstance(edge, dict)
                or edge.get("kind") != "profile_edge_candidate"
                or edge.get("region_id") != owner_id
                or edge.get("source_orientation") != "horizontal"
                or edge.get("one_sided_boundary_candidate") is not True
                or not isinstance(edge.get("position_px"), (int, float))
                or isinstance(edge.get("position_px"), bool)
                or not isinstance(edge.get("span_px"), list)
                or len(edge["span_px"]) != 2
                or not all(isinstance(v, (int, float)) for v in edge["span_px"])
                or abs(edge["span_px"][1] - edge["span_px"][0]) < ow * 0.20
                or not isinstance(edge.get("independent_geometry_source_count"), int)
                or edge["independent_geometry_source_count"] < 2
            ):
                continue
            horizontal_surfaces.append(edge)

        def matching_surface(
            terminal: float,
            material_side: int,
            surfaces: list[dict] = horizontal_surfaces,
        ) -> list[dict]:
            return [
                edge for edge in surfaces
                if edge.get("material_side_index") == material_side
                and edge.get("background_side_index") == 1 - material_side
                and abs(float(edge["position_px"]) - terminal)
                <= max(
                    14.0,
                    float(edge.get("junction_tolerance_px") or 0.0),
                )
            ]

        upper = matching_surface(low, 1)
        lower = matching_surface(high, 0)
        if (
            len(upper) == 1
            and len(lower) == 1
            and upper[0].get("ref") != lower[0].get("ref")
        ):
            owner_candidates.append(owner_id)
    return len(owner_candidates) == 1


def _labeled_dimension_targets_by_region(
    regions: list[object],
    hybrid_report: dict | None,
) -> dict[str, list[StructuralLabeledDimensionTarget]]:
    """Route only explicit labeled-mm OCR items to one unique nearby region.

    Raster positions are used solely to choose which bounded structural query may
    inspect the already OCR-read label.  They never define an engineering value
    or coordinate.
    """

    if hybrid_report is None:
        return {}
    if hybrid_report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise StructuralContextError(
            "labeled dimension targets require dg-hybrid-ocr-bakeoff-v2"
        )
    coverage = hybrid_report.get("coverage")
    if not isinstance(coverage, dict):
        return {}
    raw_items: list[object] = []
    for bucket_name in (
        "unassigned_linear_observations",
        "unconfirmed_proposal_observations",
        "routed_elsewhere_or_unclassified_observations",
    ):
        bucket = coverage.get(bucket_name)
        if isinstance(bucket, list):
            raw_items.extend(bucket)
    raw_items.extend(_fragmented_labeled_dimension_items(raw_items))

    region_boxes: list[
        tuple[str, tuple[float, float, float, float]]
    ] = []
    valid_region_ids: set[str] = set()
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        if region_id:
            valid_region_ids.add(region_id)
        bbox = _region_source_bbox(region)
        if region_id and bbox is not None:
            region_boxes.append((region_id, bbox))

    candidate_region_by_id: dict[str, str] = {}
    candidates = hybrid_report.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_id = candidate.get("candidate_id")
            candidate_region_id = candidate.get("region_id")
            if (
                not isinstance(candidate_id, str)
                or not candidate_id
                or not isinstance(candidate_region_id, str)
                or candidate_region_id not in valid_region_ids
            ):
                continue
            source_regions = candidate.get("source_region_ids")
            if isinstance(source_regions, list) and source_regions:
                unique_source_regions = {
                    str(item)
                    for item in source_regions
                    if isinstance(item, str) and item
                }
                if unique_source_regions != {candidate_region_id}:
                    continue
            previous = candidate_region_by_id.get(candidate_id)
            if previous is not None and previous != candidate_region_id:
                candidate_region_by_id.pop(candidate_id, None)
                continue
            candidate_region_by_id[candidate_id] = candidate_region_id

    source_raster = hybrid_report.get("source_raster")
    source_raster_path = (
        source_raster
        if isinstance(source_raster, str) and source_raster
        else None
    )
    profile_inventory = hybrid_report.get("structural_profile_inventory")
    if not isinstance(profile_inventory, list):
        profile_inventory = []

    output: dict[str, list[StructuralLabeledDimensionTarget]] = {}
    seen_sources: set[int] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        text = item.get("text")
        token_value = _positive_number(item.get("token"))
        if token_value is None:
            primary_tokens = item.get("primary_tokens")
            if isinstance(primary_tokens, list) and len(primary_tokens) == 1:
                token_value = _positive_number(primary_tokens[0])
        item_bbox = _ocr_bbox_rect(item.get("bbox"))
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index < 0
            or source_index in seen_sources
            or not isinstance(text, str)
            or not text.strip()
            or token_value is None
            or item_bbox is None
        ):
            continue

        match = _LABELED_MM_DIMENSION_RE.search(text)
        if match is None:
            continue
        text_value = _positive_number(match.group("value"))
        if text_value is None or not math.isclose(
            text_value,
            token_value,
            abs_tol=max(abs(token_value) * 1e-6, 1e-9),
        ):
            continue

        hinted_region_id: str | None = None
        candidate_id = item.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id:
            hinted_region_id = candidate_region_by_id.get(candidate_id)

        if hinted_region_id is not None:
            region_id = hinted_region_id
        else:
            distances: list[
                tuple[float, str, tuple[float, float, float, float]]
            ] = [
                (_rect_rect_distance(item_bbox, bbox), region_id, bbox)
                for region_id, bbox in region_boxes
            ]
            distances.sort(key=lambda item: (item[0], item[1]))
            if not distances:
                continue

            nearest_distance, region_id, nearest_bbox = distances[0]
            region_scale = min(nearest_bbox[2], nearest_bbox[3])
            if nearest_distance > max(32.0, region_scale * 0.50):
                continue
            if len(distances) > 1:
                second_distance = distances[1][0]
                if second_distance - nearest_distance < max(
                    8.0,
                    region_scale * 0.03,
                ):
                    continue

        deterministic_visual_direction = (
            infer_short_dimension_visual_direction(
                source_raster_path,
                item.get("bbox"),
            )
            if source_raster_path is not None
            else None
        )
        deterministic_relation_seed = _deterministic_labeled_relation_seed(
            source_raster_path=source_raster_path,
            raw_bbox=item.get("bbox"),
            region_id=region_id,
            deterministic_visual_direction=deterministic_visual_direction,
            profile_inventory=profile_inventory,
        )
        if (
            deterministic_relation_seed is None
            and _proven_labeled_vertical_overall(
                source_raster_path=source_raster_path,
                raw_bbox=item.get("bbox"),
                region_id=region_id,
                regions=regions,
                profile_inventory=profile_inventory,
            )
        ):
            deterministic_visual_direction = "vertical"
            deterministic_relation_seed = "overall_extent"
        output.setdefault(region_id, []).append(
            StructuralLabeledDimensionTarget(
                target_id=f"LD_{source_index:04d}",
                source_item_index=source_index,
                source_text=text.strip(),
                value=token_value,
                deterministic_visual_direction=deterministic_visual_direction,
                deterministic_relation_seed=deterministic_relation_seed,
            )
        )
        seen_sources.add(source_index)

    for values in output.values():
        values.sort(key=lambda item: (item.source_item_index, item.target_id))
    return output


class StructuralAcceptedLinearSpanLowerBound(_StrictStructuralModel):
    """OCR-confirmed same-direction span that any claimed overall must cover."""

    visual_direction: Literal["horizontal", "vertical"]
    minimum_value: float = Field(gt=0)
    candidate_ids: list[str] = Field(min_length=1)

    @field_validator("candidate_ids")
    @classmethod
    def _unique_candidate_ids(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(item for item in value if item))
        if not cleaned:
            raise ValueError("candidate_ids must contain at least one non-empty id")
        return cleaned


def _accepted_linear_span_lower_bounds_by_region(
    hybrid_report: dict | None,
) -> dict[str, list[StructuralAcceptedLinearSpanLowerBound]]:
    """Return the largest OCR-confirmed linear span per region/direction.

    The bound is engineering-value evidence from accepted OCR dimensions only.
    It does not infer an overall dimension and uses no pixel-to-mm conversion.
    """

    if hybrid_report is None:
        return {}
    candidates = hybrid_report.get("candidates")
    if not isinstance(candidates, list):
        return {}

    grouped: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        region_id = str(candidate.get("region_id") or "")
        candidate_id = str(candidate.get("candidate_id") or "")
        visual_direction = str(candidate.get("orientation") or "")
        accepted_token = candidate.get("accepted_token")
        if (
            not region_id
            or not candidate_id
            or visual_direction not in {"horizontal", "vertical"}
            or accepted_token is None
        ):
            continue

        if isinstance(accepted_token, str):
            nominal_token = accepted_token.split("±", 1)[0]
        else:
            nominal_token = accepted_token
        value = _positive_number(nominal_token)
        if value is None:
            continue

        witnesses = candidate.get("witness_positions_px")
        if not (
            isinstance(witnesses, list)
            and len(witnesses) == 2
            and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in witnesses
            )
        ):
            continue
        grouped.setdefault(
            (region_id, visual_direction),
            [],
        ).append((value, candidate_id))

    output: dict[str, list[StructuralAcceptedLinearSpanLowerBound]] = {}
    for (region_id, visual_direction), records in sorted(grouped.items()):
        maximum = max(value for value, _candidate_id in records)
        candidate_ids = sorted(
            candidate_id
            for value, candidate_id in records
            if math.isclose(value, maximum, abs_tol=1e-9)
        )
        output.setdefault(region_id, []).append(
            StructuralAcceptedLinearSpanLowerBound(
                visual_direction=cast(
                    Literal["horizontal", "vertical"],
                    visual_direction,
                ),
                minimum_value=maximum,
                candidate_ids=candidate_ids,
            )
        )

    for bounds in output.values():
        bounds.sort(
            key=lambda item: (
                item.visual_direction,
                item.minimum_value,
                item.candidate_ids,
            )
        )
    return output



def _tabular_grid_reference_region(
    region: dict,
    other_regions: list[object],
    report: dict,
) -> bool:
    """Recognize a measured table grid, not merely axis-aligned ink.

    Two OCR-aligned header/data rows and independent grid lines are required.
    Candidate edges from table borders do not establish solid geometry.
    Coordinates here only prove region identity, never engineering values.
    """
    bounds = _region_source_bbox(region)
    region_id = region.get("region_id")
    if bounds is None or not isinstance(region_id, str):
        return False
    if region.get("circle_group_count") != 0:
        return False
    items = report.get("whole_drawing_items")
    inventory = report.get("structural_profile_inventory")
    candidates = report.get("candidates")
    if (
        not isinstance(items, list)
        or not isinstance(inventory, list)
        or not isinstance(candidates, list)
    ):
        return False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False
        involved = candidate.get("source_region_ids") or []
        if candidate.get("region_id") == region_id or region_id in involved:
            if candidate.get("accepted_token") is not None:
                return False
            if any(other != region_id for other in involved):
                return False
    x, y, width, height = bounds
    grid = [
        edge for edge in inventory
        if isinstance(edge, dict) and edge.get("region_id") == region_id
    ]
    spanning = [
        edge for edge in grid
        if edge.get("source_orientation") == "horizontal"
        and isinstance(edge.get("span_px"), list)
        and len(edge["span_px"]) == 2
        and all(isinstance(v, (int, float)) for v in edge["span_px"])
        and abs(edge["span_px"][1] - edge["span_px"][0]) >= width * 0.7
    ]
    columns = sum(edge.get("source_orientation") == "vertical" for edge in grid)
    if len(spanning) < 2 or columns < 6:
        return False
    other_boxes: list[tuple[float, float, float, float]] = []
    for other in other_regions:
        if not isinstance(other, dict) or other.get("region_id") == region_id:
            continue
        other_box = _region_source_bbox(other)
        if other_box is None:
            return False
        other_boxes.append(other_box)
    rows: list[list[tuple[float, str]]] = []
    row_centers: list[float] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        rect = _ocr_bbox_rect(item.get("bbox"))
        if rect is None:
            continue
        tx, ty, tw, th = rect
        if tx < x or ty < y or tx + tw > x + width or ty + th > y + height:
            continue
        if any(_rect_rect_distance(rect, other) == 0 for other in other_boxes):
            continue
        cy = ty + th / 2
        cx = tx + tw / 2
        existing = next(
            (index for index, center in enumerate(row_centers)
             if abs(center - cy) <= max(8.0, height * 0.045)),
            None,
        )
        if existing is None:
            row_centers.append(cy)
            rows.append([])
            existing = len(rows) - 1
        rows[existing].append((cx, item["text"].strip()))
    headers = [
        (row_centers[index], sorted(row))
        for index, row in enumerate(rows)
        if len(row) >= 7
        and sum(any(ch.isalpha() for ch in label) for _cx, label in row) >= 6
    ]
    data_rows = [
        (row_centers[index], sorted(row))
        for index, row in enumerate(rows)
        if len(row) >= 7
        and sum(any(ch.isdigit() for ch in label) for _cx, label in row) >= 6
    ]
    for header_y, header in headers:
        for data_y, data in data_rows:
            if data_y <= header_y + max(8.0, height * 0.045):
                continue
            aligned = sum(
                any(abs(hx - dx) <= width * 0.03 for dx, _ in data)
                for hx, _ in header
            )
            if aligned >= 7:
                return True
    return False


def _linked_annotation_view_owner(
    region: dict,
    all_regions: list[object],
    report: dict | None,
    *,
    has_structural_targets: bool,
) -> str | None:
    """Recover unique annotation-to-view ownership, not view geometry.

    At least two distinct accepted dimension axes must link the child to
    the same larger overlapping region. Conflicts fail closed.
    """
    if report is None or has_structural_targets:
        return None
    child_id = region.get("region_id")
    child = _region_source_bbox(region)
    candidates = report.get("candidates")
    if not isinstance(child_id, str) or child is None or not isinstance(candidates, list):
        return None
    if region.get("circle_group_count") != 0:
        return None
    if any(
        not isinstance(item, dict)
        or (item.get("region_id") == child_id and item.get("accepted_token") is not None)
        for item in candidates
    ):
        return None
    owners: dict[str, set[float]] = {}
    for item in candidates:
        sources = item.get("source_region_ids")
        owner = item.get("region_id")
        if (
            not isinstance(sources, list)
            or child_id not in sources
            or not isinstance(owner, str)
            or owner == child_id
            or owner not in sources
            or len(set(sources)) != 2
            or _positive_number(item.get("accepted_token")) is None
        ):
            continue
        position = item.get("axis_px")
        if not isinstance(position, (int, float)) or isinstance(position, bool):
            continue
        owners.setdefault(owner, set()).add(round(float(position), 1))
    eligible = []
    cx, cy, cw, ch = child
    for owner_id, positions in owners.items():
        if len(positions) < 2:
            continue
        matches = [
            item for item in all_regions
            if isinstance(item, dict) and item.get("region_id") == owner_id
        ]
        if len(matches) != 1:
            continue
        parent = _region_source_bbox(matches[0])
        if parent is None:
            continue
        px, py, pw, ph = parent
        overlap = max(0, min(cx + cw, px + pw) - max(cx, px))
        overlap *= max(0, min(cy + ch, py + ph) - max(cy, py))
        if pw * ph >= 2 * cw * ch and overlap >= 0.5 * cw * ch:
            eligible.append(owner_id)
    return eligible[0] if len(eligible) == 1 and len(owners) == 1 else None


_REFERENCE_REGION_HEADER_RE = re.compile(
    r"(?i)^(?:BOM|BILL OF MATERIALS|PARTS LIST|PARTS TABLE|"
    r"MATERIAL LIST|SPECIFICATIONS?|GENERAL NOTES|TECHNICAL NOTES|"
    r"明细表|零件明细|零件明细表|材料明细|材料表|规格表|技术要求|技术说明)$"
)


def _deterministic_non_geometric_reference_region(
    region: dict,
    all_regions: list[object],
    hybrid_report: dict | None,
    *,
    has_structural_targets: bool,
) -> bool:
    """OCR-labeled reference block with positively checked absence of geometry.

    Missing geometry detections alone are never sufficient to claim that a
    region is a reference table. Pixels are identity evidence, not mm.
    """
    if hybrid_report is None or has_structural_targets:
        return False
    box = _region_source_bbox(region)
    region_id = region.get("region_id")
    if box is None or not isinstance(region_id, str) or not region_id:
        return False
    if _tabular_grid_reference_region(region, all_regions, hybrid_report):
        return True
    for key in ("circle_group_count", "linear_pattern_candidate_count",
                "candidate_overlay_count"):
        count = region.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count != 0:
            return False
    inventory = hybrid_report.get("structural_profile_inventory")
    candidates = hybrid_report.get("candidates")
    ocr_items = hybrid_report.get("whole_drawing_items")
    if (
        not isinstance(inventory, list)
        or not isinstance(candidates, list)
        or not isinstance(ocr_items, list)
    ):
        return False
    if any(
        not isinstance(item, dict) or item.get("region_id") == region_id
        for item in inventory
    ):
        return False
    if any(
        not isinstance(item, dict)
        or item.get("region_id") == region_id
        or region_id in (item.get("source_region_ids") or [])
        for item in candidates
    ):
        return False

    x, y, w, h = box
    other_boxes: list[tuple[float, float, float, float]] = []
    for other in all_regions:
        if isinstance(other, dict) and other.get("region_id") != region_id:
            other_box = _region_source_bbox(other)
            if other_box is not None:
                other_boxes.append(other_box)

    matched_texts: list[str] = []
    for item in ocr_items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        text_box = _ocr_bbox_rect(item.get("bbox"))
        if text_box is None:
            continue
        tx, ty, tw, th = text_box
        if tx < x or ty < y or tx + tw > x + w or ty + th > y + h:
            continue
        if any(_rect_rect_distance(text_box, other) == 0.0 for other in other_boxes):
            continue
        matched_texts.append(item["text"].strip())

    return (
        len(matched_texts) >= 2
        and any(_REFERENCE_REGION_HEADER_RE.fullmatch(text) for text in matched_texts)
    )


_VIEW_LABEL_KIND: dict[str, ViewKind] = {
    "FRONT VIEW": "front",
    "FRONT ELEVATION": "front",
    "主视图": "front",
    "正视图": "front",
    "SIDE VIEW": "side",
    "LEFT SIDE VIEW": "side",
    "RIGHT SIDE VIEW": "side",
    "LEFT VIEW": "side",
    "RIGHT VIEW": "side",
    "侧视图": "side",
    "左视图": "side",
    "右视图": "side",
    "TOP VIEW": "top",
    "PLAN VIEW": "top",
    "俯视图": "top",
    "顶视图": "top",
}


def _deterministic_ocr_view_kind(
    region: dict,
    all_regions: list[object],
    hybrid_report: dict | None,
) -> tuple[ViewKind | None, int | None]:
    """Only an exclusive, exact view caption on a geometry-bearing region.

    Text boxes prove view-label ownership; they never provide numeric geometry.
    Other regions, conflicting captions, and missing geometry proof fail closed.
    """
    if hybrid_report is None:
        return None, None
    box = _region_source_bbox(region)
    rid = region.get("region_id")
    items = hybrid_report.get("whole_drawing_items")
    inventory = hybrid_report.get("structural_profile_inventory")
    if (
        box is None
        or not isinstance(rid, str)
        or not rid
        or not isinstance(items, list)
        or not isinstance(inventory, list)
    ):
        return None, None

    geometry_counts = (
        region.get("circle_group_count"),
        region.get("linear_pattern_candidate_count"),
        region.get("candidate_overlay_count"),
    )
    has_geometry = any(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in geometry_counts
    ) or any(
        isinstance(item, dict) and item.get("region_id") == rid
        for item in inventory
    )
    if not has_geometry:
        return None, None

    other_boxes: list[tuple[float, float, float, float]] = []
    for other in all_regions:
        if isinstance(other, dict) and other.get("region_id") != rid:
            other_box = _region_source_bbox(other)
            if other_box is None:
                return None, None
            other_boxes.append(other_box)

    x, y, width, height = box
    matches: list[tuple[ViewKind, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("text")
        source_index = item.get("source_item_index")
        if (
            not isinstance(raw_text, str)
            or not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index < 0
        ):
            continue
        normalized = " ".join(raw_text.upper().split())
        kind = _VIEW_LABEL_KIND.get(normalized)
        if kind is None:
            continue
        text_box = _ocr_bbox_rect(item.get("bbox"))
        if text_box is None:
            continue
        tx, ty, tw, th = text_box
        if tx < x or ty < y or tx + tw > x + width or ty + th > y + height:
            continue
        if any(
            _rect_rect_distance(text_box, other_box) == 0.0
            for other_box in other_boxes
        ):
            continue
        matches.append((kind, source_index))

    if len(matches) != 1:
        return None, None
    return matches[0]


class StructuralRegionQuery(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    kind: Literal["structural_context"] = "structural_context"
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    evidence_label: str = Field(min_length=1)
    deterministic_non_geometric_reference: bool = False
    deterministic_view_owner_region_id: str | None = None
    deterministic_view_kind: ViewKind | None = None
    deterministic_view_label_source_index: int | None = Field(default=None, ge=0)
    labeled_dimension_targets: list[StructuralLabeledDimensionTarget] = Field(
        default_factory=list
    )
    accepted_linear_span_lower_bounds: list[
        StructuralAcceptedLinearSpanLowerBound
    ] = Field(default_factory=list)
    deterministic_profile_symmetry_axis: Literal["horizontal", "vertical"] | None = None
    deterministic_profile_symmetry_method: Literal[
        "foreground_mirror_consensus_v1",
        "profile_edge_mirror_consensus_v1",
        "profile_edge_midpoint_consensus_v2",
    ] | None = None
    deterministic_profile_symmetry_overlay: Literal[
        "blue_dashed_topology_axis"
    ] | None = None
    instruction_key: Literal["structural-context-v1"] = "structural-context-v1"


class StructuralViewAxes(_StrictStructuralModel):
    horizontal: Axis
    vertical: Axis


_CANONICAL_VIEW_AXIS_MAP: dict[ViewKind, dict[str, Axis]] = {
    "front": {"horizontal": "X", "vertical": "Z"},
    "side": {"horizontal": "Y", "vertical": "Z"},
    "top": {"horizontal": "X", "vertical": "Y"},
}


class StructuralContextQueryPlan(_StrictStructuralModel):
    schema_version: Literal["structural-context-queries-v1"] = Field(
        default="structural-context-queries-v1",
        alias="schema",
    )
    queries: list[StructuralRegionQuery] = Field(min_length=1, max_length=4)
    rules: dict[str, bool]
    view_axis_map: dict[ViewKind, StructuralViewAxes]
    answer_template: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_queries(self) -> StructuralContextQueryPlan:
        query_ids = [item.query_id for item in self.queries]
        region_ids = [item.region_id for item in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("structural query ids must be unique")
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("structural query region ids must be unique")
        target_ids = [
            target.target_id
            for query in self.queries
            for target in query.labeled_dimension_targets
        ]
        source_indices = [
            target.source_item_index
            for query in self.queries
            for target in query.labeled_dimension_targets
        ]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("labeled dimension target ids must be unique")
        if len(source_indices) != len(set(source_indices)):
            raise ValueError("labeled dimension source indices must be unique")
        actual_axis_map = {
            view_kind: {
                "horizontal": axes.horizontal,
                "vertical": axes.vertical,
            }
            for view_kind, axes in self.view_axis_map.items()
        }
        if actual_axis_map != _CANONICAL_VIEW_AXIS_MAP:
            raise ValueError("structural view_axis_map must match canonical view semantics")
        return self


class StructuralOverallFact(_StrictStructuralModel):
    axis: Axis
    value: float = Field(gt=0)
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class StructuralRotationalSymmetryDecision(_StrictStructuralModel):
    status: Literal["established", "not_established"]
    basis: Literal["centerline", "axial_section_symmetry"] | None = None
    centerline_direction: Literal["horizontal", "vertical"] | None = None
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> StructuralRotationalSymmetryDecision:
        if self.status == "not_established":
            if self.basis is not None or self.centerline_direction is not None:
                raise ValueError(
                    "not_established rotational symmetry requires null visual basis fields"
                )
            return self

        if self.basis is None:
            raise ValueError("established rotational symmetry requires visual basis")
        if self.basis == "centerline" and self.centerline_direction is None:
            raise ValueError("centerline basis requires centerline_direction")
        if (
            self.basis == "axial_section_symmetry"
            and self.centerline_direction is not None
        ):
            raise ValueError(
                "axial_section_symmetry basis forbids centerline_direction"
            )
        return self


class StructuralLabeledDimensionDecision(_StrictStructuralModel):
    target_id: str = Field(min_length=1)
    status: Literal["resolved", "unresolved"]
    visual_direction: Literal["horizontal", "vertical"] | None = None
    relation: Literal[
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    ] | None = None
    profile_transition_geometry: Literal[
        "orthogonal",
        "non_orthogonal",
        "mixed",
    ] | None = None
    symmetry_scope: Literal["single", "bilateral"] | None = None
    evidence: list[str] = Field(min_length=1)
    reason: str | None = None

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> StructuralLabeledDimensionDecision:
        if self.status == "unresolved":
            if (
                self.visual_direction is not None
                or self.relation is not None
                or self.profile_transition_geometry is not None
                or self.symmetry_scope is not None
            ):
                raise ValueError(
                    "unresolved labeled dimension relation forbids semantic fields"
                )
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError(
                    "unresolved labeled dimension relation requires reason"
                )
            return self

        if self.visual_direction is None or self.relation is None:
            raise ValueError(
                "resolved labeled dimension relation requires visual_direction "
                "and relation"
            )
        if self.reason is not None:
            raise ValueError(
                "resolved labeled dimension relation forbids unresolved reason"
            )
        if self.relation == "overall_extent":
            if (
                self.profile_transition_geometry is not None
                or self.symmetry_scope is not None
            ):
                raise ValueError(
                    "overall_extent labeled dimension forbids profile topology fields"
                )
            return self
        # Local profile topology metadata is optional.  Deterministic raster
        # topology now owns endpoint/overall-side identity; these fields are
        # retained only as descriptive metadata when the visual reader can
        # supply them confidently.
        return self


class StructuralRegionAnswer(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    evidence: list[str] = Field(default_factory=list)
    overall_dimension_facts: list[StructuralOverallFact] = Field(default_factory=list)
    rotational_symmetry: StructuralRotationalSymmetryDecision | None = Field(...)
    labeled_dimension_decisions: list[StructuralLabeledDimensionDecision] = Field(
        default_factory=list
    )
    unresolved: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _clean_optional_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("unresolved")
    @classmethod
    def _clean_unresolved(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def _shape(self) -> StructuralRegionAnswer:
        if self.view_kind is None:
            if not self.unresolved:
                raise ValueError("missing view_kind requires structured unresolved reason")
            if self.overall_dimension_facts:
                raise ValueError("unresolved view_kind cannot carry overall dimension facts")
            if self.rotational_symmetry is not None:
                raise ValueError("unresolved view_kind cannot carry rotational symmetry decision")
        elif not self.evidence:
            raise ValueError("resolved view_kind requires evidence")
        elif not self.unresolved and self.rotational_symmetry is None:
            raise ValueError(
                "resolved structural answer requires explicit rotational symmetry decision"
            )
        return self


class StructuralContextAnswers(_StrictStructuralModel):
    schema_version: Literal["structural-context-answers-v1"] = Field(
        default="structural-context-answers-v1",
        alias="schema",
    )
    answers: list[StructuralRegionAnswer] = Field(min_length=1, max_length=4)


class StructuralCompactOverallFact(_StrictStructuralModel):
    axis: Axis
    value: float = Field(gt=0)


class StructuralCompactRotationalDecision(_StrictStructuralModel):
    status: Literal["established", "not_established"]
    basis: Literal["centerline", "axial_section_symmetry"] | None = None
    centerline_direction: Literal["horizontal", "vertical"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> StructuralCompactRotationalDecision:
        """Enforce the same evidence-bearing shape as the full Reader decision."""
        if self.status == "not_established":
            if self.basis is not None or self.centerline_direction is not None:
                raise ValueError(
                    "not_established rotational symmetry forbids basis and centerline_direction"
                )
            return self
        if self.basis is None:
            raise ValueError("established rotational symmetry requires visual basis")
        if self.basis == "centerline" and self.centerline_direction is None:
            raise ValueError("centerline basis requires centerline_direction")
        if (
            self.basis == "axial_section_symmetry"
            and self.centerline_direction is not None
        ):
            raise ValueError(
                "axial_section_symmetry basis forbids centerline_direction"
            )
        return self


class StructuralCompactLabeledDecision(_StrictStructuralModel):
    target_id: str = Field(min_length=1)
    status: Literal["resolved", "unresolved"]
    visual_direction: Literal["horizontal", "vertical"] | None = None
    relation: Literal[
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    ] | None = None
    profile_transition_geometry: Literal[
        "orthogonal", "non_orthogonal", "mixed"
    ] | None = None
    symmetry_scope: Literal["single", "bilateral"] | None = None
    reason: str | None = None


class StructuralCompactRegionDecision(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    overall_dimension_facts: list[StructuralCompactOverallFact] = Field(
        default_factory=list
    )
    rotational_symmetry: StructuralCompactRotationalDecision | None = None
    labeled_dimension_decisions: list[StructuralCompactLabeledDecision] = Field(
        default_factory=list
    )
    unresolved: list[str] = Field(default_factory=list)


class StructuralCompactVisualAnswers(_StrictStructuralModel):
    """Only decisions not already owned by deterministic Reader evidence."""

    schema_version: Literal["structural-visual-decisions-v1"] = Field(
        default="structural-visual-decisions-v1",
        alias="schema",
    )
    decisions: list[StructuralCompactRegionDecision] = Field(
        default_factory=list, max_length=4
    )


def compose_structural_visual_answers(
    plan: StructuralContextQueryPlan,
    visual: StructuralCompactVisualAnswers,
) -> StructuralContextAnswers:
    """Merge sparse visual decisions into machine-owned full answers.

    Query identities, evidence, deterministic view labels, known relation
    seeds, and all OCR engineering values stay under Reader ownership.
    Never invent missing geometry or silently accept omitted decisions.
    """
    import copy

    submitted = {item.query_id: item for item in visual.decisions}
    if len(submitted) != len(visual.decisions):
        raise StructuralContextError("duplicate compact visual query id")
    queries_by_id = {item.query_id: item for item in plan.queries}
    by_id: dict[str, StructuralCompactRegionDecision] = {}
    for query_id, patch in submitted.items():
        query = queries_by_id.get(query_id)
        if query is None:
            by_id[query_id] = patch
            continue
        reason = (
            "non_geometric_reference_region"
            if query.deterministic_non_geometric_reference
            else "rotational_symmetry_not_visible_in_region"
            if query.deterministic_view_owner_region_id is not None
            else None
        )
        if reason is None:
            by_id[query_id] = patch
            continue
        # Old Agent revisions may redundantly include Reader-owned regions.
        # Only their empty, equivalent observations are harmless. Any new
        # engineering value, view, or contrary status remains forbidden.
        if (
            patch.view_kind is not None
            or patch.overall_dimension_facts
            or patch.rotational_symmetry is not None
            or patch.labeled_dimension_decisions
            or patch.unresolved not in ([], [reason])
        ):
            raise StructuralContextError(
                f"query {query_id!r} overrides Reader-owned region"
            )
    expected_queries = {
        query.query_id
        for query in plan.queries
        if not query.deterministic_non_geometric_reference
        and query.deterministic_view_owner_region_id is None
    }
    if set(by_id) != expected_queries:
        raise StructuralContextError(
            "compact visual query coverage mismatch: "
            f"missing={sorted(expected_queries - set(by_id))} "
            f"extra={sorted(set(by_id) - expected_queries)}"
        )

    template = copy.deepcopy(plan.answer_template)
    entries = template.get("answers")
    if not isinstance(entries, list) or len(entries) != len(plan.queries):
        raise StructuralContextError("invalid deterministic structural answer template")

    for query, entry in zip(plan.queries, entries, strict=True):
        if not isinstance(entry, dict) or entry.get("query_id") != query.query_id:
            raise StructuralContextError("structural template query identity mismatch")
        if query.deterministic_non_geometric_reference:
            continue
        if query.deterministic_view_owner_region_id is not None:
            owner_region_id = query.deterministic_view_owner_region_id
            owners = [
                other for other in plan.queries
                if other.region_id == owner_region_id
                and not other.deterministic_non_geometric_reference
                and other.deterministic_view_owner_region_id is None
            ]
            if len(owners) != 1:
                raise StructuralContextError(
                    f"query {query.query_id!r} has invalid annotation view owner"
                )
            owner = owners[0]
            owner_patch = by_id.get(owner.query_id)
            kind = owner.deterministic_view_kind or (
                owner_patch.view_kind if owner_patch is not None else None
            )
            if kind is None:
                raise StructuralContextError(
                    f"query {query.query_id!r} annotation owner view unresolved"
                )
            entry["view_kind"] = kind
            entry["unresolved"] = ["rotational_symmetry_not_visible_in_region"]
            continue

        patch = by_id[query.query_id]
        if (
            query.deterministic_view_kind is not None
            and patch.view_kind is not None
            and patch.view_kind != query.deterministic_view_kind
        ):
            raise StructuralContextError(
                f"query {query.query_id!r} overrides deterministic OCR view"
            )
        entry["view_kind"] = query.deterministic_view_kind or patch.view_kind
        entry["overall_dimension_facts"] = [
            {**fact.model_dump(), "evidence": [query.evidence_label]}
            for fact in patch.overall_dimension_facts
        ]
        entry["rotational_symmetry"] = (
            {
                **patch.rotational_symmetry.model_dump(),
                "evidence": [query.evidence_label],
            }
            if patch.rotational_symmetry is not None
            else None
        )
        entry["unresolved"] = list(patch.unresolved)

        target_by_id = {
            item.target_id: item
            for item in query.labeled_dimension_targets
        }
        pending_ids = {
            item.target_id
            for item in query.labeled_dimension_targets
            if item.deterministic_relation_seed is None
        }
        submitted_ids = [
            item.target_id for item in patch.labeled_dimension_decisions
        ]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise StructuralContextError(
                f"query {query.query_id!r} repeats compact labeled decision"
            )
        # Some Agent versions echo Reader-seeded labeled relations despite
        # the compact contract. Such an echo is redundant only when every
        # semantic field exactly matches the Reader's frozen seed. Ignore
        # it rather than wasting the one-shot resume opportunity. Do not
        # permit changing the seed or smuggling profile topology metadata.
        submitted_pending: dict[str, StructuralCompactLabeledDecision] = {}
        for decision in patch.labeled_dimension_decisions:
            target = target_by_id.get(decision.target_id)
            if target is None or target.deterministic_relation_seed is None:
                submitted_pending[decision.target_id] = decision
                continue
            if (
                decision.status != "resolved"
                or decision.visual_direction != target.deterministic_visual_direction
                or decision.relation != target.deterministic_relation_seed
                or decision.profile_transition_geometry is not None
                or decision.symmetry_scope is not None
                or decision.reason is not None
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} overrides deterministic labeled "
                    f"relation seed: {decision.target_id!r}"
                )
        if set(submitted_pending) != pending_ids:
            raise StructuralContextError(
                f"query {query.query_id!r} compact labeled coverage mismatch: "
                f"missing={sorted(pending_ids - set(submitted_pending))} "
                f"extra={sorted(set(submitted_pending) - pending_ids)}"
            )
        patch_by_id = submitted_pending
        for target_entry in entry["labeled_dimension_decisions"]:
            target_id = target_entry["target_id"]
            if target_id not in patch_by_id:
                continue
            target = target_by_id[target_id]
            decision = patch_by_id[target_id]
            if (
                decision.status == "resolved"
                and target.deterministic_visual_direction is not None
                and decision.visual_direction != target.deterministic_visual_direction
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} compact labeled direction conflicts "
                    f"with deterministic topology: {target_id!r}"
                )
            target_entry.update(decision.model_dump())
            target_entry["evidence"] = [query.evidence_label]

    return StructuralContextAnswers.model_validate(template)


def build_structural_context_queries(
    reader_input: dict,
    *,
    hybrid_report: dict | None = None,
    max_region_queries: int = 4,
) -> StructuralContextQueryPlan:
    if reader_input.get("schema") != "reader-input-v1":
        raise StructuralContextError("structural context requires reader-input-v1")
    if not 1 <= max_region_queries <= 4:
        raise StructuralContextError("max_region_queries must be between 1 and 4")

    regions = reader_input.get("regions")
    if not isinstance(regions, list) or not regions:
        raise StructuralContextError("reader input requires at least one region")
    if len(regions) > max_region_queries:
        raise StructuralContextError(
            f"region query count {len(regions)} exceeds bounded maximum {max_region_queries}"
        )

    labeled_targets_by_region = _labeled_dimension_targets_by_region(
        regions,
        hybrid_report,
    )
    accepted_span_bounds_by_region = (
        _accepted_linear_span_lower_bounds_by_region(hybrid_report)
    )

    shared_structural_context_path = reader_input.get(
        "structural_context_overview_path"
    )
    if shared_structural_context_path is not None and (
        not isinstance(shared_structural_context_path, str)
        or not shared_structural_context_path
    ):
        raise StructuralContextError(
            "structural_context_overview_path must be a non-empty string"
        )

    queries: list[StructuralRegionQuery] = []
    seen_regions: set[str] = set()

    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            raise StructuralContextError("reader input region must be an object")
        region_id = region.get("region_id")
        structural_context_path = region.get("structural_context_path")
        crop_path = region.get("crop_path")
        if not isinstance(region_id, str) or not region_id:
            raise StructuralContextError("reader input region requires region_id")
        if region_id in seen_regions:
            raise StructuralContextError(f"duplicate reader region {region_id!r}")
        seen_regions.add(region_id)

        using_structural_context_image = False
        if isinstance(shared_structural_context_path, str):
            image_path = shared_structural_context_path
            evidence_label = f"structural:{region_id}:context"
            using_structural_context_image = True
        elif isinstance(structural_context_path, str) and structural_context_path:
            image_path = structural_context_path
            evidence_label = f"structural:{region_id}:context"
            using_structural_context_image = True
        elif isinstance(crop_path, str) and crop_path:
            image_path = crop_path
            evidence_label = f"structural:{region_id}:crop"
        else:
            raise StructuralContextError(
                f"reader region {region_id!r} requires crop_path or structural_context_path"
            )

        symmetry_hint = region.get("bilateral_symmetry_hint")
        deterministic_axis: Literal["horizontal", "vertical"] | None = None
        deterministic_method: Literal[
            "foreground_mirror_consensus_v1",
            "profile_edge_mirror_consensus_v1",
            "profile_edge_midpoint_consensus_v2",
        ] | None = None
        if isinstance(symmetry_hint, dict) and symmetry_hint.get("status") == "established":
            axis_direction = symmetry_hint.get("axis_direction")
            method = symmetry_hint.get("method")
            if axis_direction in {"horizontal", "vertical"}:
                deterministic_axis = axis_direction
            if method in {
                "foreground_mirror_consensus_v1",
                "profile_edge_mirror_consensus_v1",
                "profile_edge_midpoint_consensus_v2",
            }:
                deterministic_method = cast(
                    Literal[
                        "foreground_mirror_consensus_v1",
                        "profile_edge_mirror_consensus_v1",
                        "profile_edge_midpoint_consensus_v2",
                    ],
                    method,
                )

        region_targets = labeled_targets_by_region.get(region_id, [])
        region_bounds = accepted_span_bounds_by_region.get(region_id, [])
        view_kind, view_label_source = _deterministic_ocr_view_kind(
            region,
            regions,
            hybrid_report,
        )
        reference_region = _deterministic_non_geometric_reference_region(
            region,
            regions,
            hybrid_report,
            has_structural_targets=bool(region_targets or region_bounds),
        )
        annotation_owner = (
            None if reference_region else _linked_annotation_view_owner(
                region, regions, hybrid_report,
                has_structural_targets=bool(region_targets or region_bounds),
            )
        )
        queries.append(
            StructuralRegionQuery(
                query_id=f"S{index:03d}",
                region_id=region_id,
                image_path=image_path,
                evidence_label=evidence_label,
                deterministic_non_geometric_reference=reference_region,
                deterministic_view_owner_region_id=annotation_owner,
                deterministic_view_kind=(
                    None if reference_region else view_kind
                ),
                deterministic_view_label_source_index=(
                    None if reference_region else view_label_source
                ),
                labeled_dimension_targets=region_targets,
                accepted_linear_span_lower_bounds=region_bounds,
                deterministic_profile_symmetry_axis=(
                    None if reference_region or annotation_owner else deterministic_axis
                ),
                deterministic_profile_symmetry_method=(
                    None if reference_region or annotation_owner else deterministic_method
                ),
                deterministic_profile_symmetry_overlay=(
                    "blue_dashed_topology_axis"
                    if using_structural_context_image
                    and deterministic_axis is not None
                    and deterministic_method == "foreground_mirror_consensus_v1"
                    else None
                ),
            )
        )

    return StructuralContextQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "structural_query_images_may_be_shared": True,
            "deduplicate_identical_query_image_paths": True,
            "scan_workspace": False,
            "report_only_view_kind_and_direct_overall_dimensions": True,
            "report_only_visual_rotational_symmetry_basis": True,
            "agent_must_not_report_engineering_rotation_axis": True,
            "agent_must_not_report_axial_section_symmetry_direction": True,
            "axial_section_axis_from_deterministic_profile_symmetry": True,
            "topology_axis_overlay_is_visual_aid_not_centerline": True,
            "centerline_absence_alone_is_not_rotation_counterevidence": True,
            "require_explicit_rotational_symmetry_decision": True,
            "allow_nonsection_longitudinal_revolved_profile": True,
            "allow_axial_section_without_drawn_centerline": True,
            "require_centerline_for_nonsection_rotation": True,
            "require_unique_section_symmetry_axis_without_centerline": True,
            "require_section_semantics_without_centerline": True,
            "solid_profile_line_is_not_centerline": True,
            "mirror_symmetry_alone_insufficient": True,
            "require_paired_coaxial_profile_for_rotation": True,
            "not_established_requires_counterevidence": True,
            "insufficient_rotation_evidence_is_unresolved": True,
            "region_local_rotation_unobservable_may_defer": True,
            "allow_non_geometric_reference_region": True,
            "deterministic_reference_requires_explicit_ocr_header_and_no_geometry": True,
            "preclassified_reference_regions_skip_agent_visual_read": True,
            "annotation_view_ownership_requires_two_accepted_cross_region_dimensions": True,
            "annotation_view_owner_supplies_only_view_identity": True,
            "explicit_ocr_view_title_is_reader_owned": True,
            "reader_view_caption_requires_geometry_and_unique_ownership": True,
            "agent_must_preserve_deterministic_view_kind": True,
            "global_rotation_closure_remains_fail_closed": True,
            "derive_missing_dimensions": False,
            "cross_view_identity": False,
            "feature_inventory": False,
            "dimension_endpoint_ownership": False,
            "local_feature_values": False,
            "labeled_dimension_value_from_hybrid_ocr_only": True,
            "labeled_dimension_relation_only": True,
            "labeled_dimension_direction_from_topology_only": True,
            "labeled_dimension_direction_hint_must_be_preserved": True,
            "labeled_dimension_relation_seed_from_topology_only": True,
            "labeled_dimension_seeded_decisions_must_be_preserved": True,
            "labeled_dimension_overall_relation_requires_actual_overall_boundary": True,
            "labeled_dimension_resolved_reason_must_be_null": True,
            "labeled_dimension_unresolved_reason_required": True,
            "labeled_dimension_profile_topology_metadata_optional": True,
            "overall_dimension_must_cover_accepted_linear_spans": True,
            "pixel_measurement": False,
        },
        view_axis_map={
            view_kind: StructuralViewAxes(
                horizontal=axes["horizontal"],
                vertical=axes["vertical"],
            )
            for view_kind, axes in _CANONICAL_VIEW_AXIS_MAP.items()
        },
        answer_template={
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": query.query_id,
                    "view_kind": query.deterministic_view_kind,
                    "evidence": [query.evidence_label],
                    "overall_dimension_facts": [],
                    "rotational_symmetry": None,
                    "labeled_dimension_decisions": [
                        {
                            "target_id": target.target_id,
                            "status": (
                                "resolved"
                                if target.deterministic_relation_seed is not None
                                else "unresolved"
                            ),
                            "visual_direction": (
                                target.deterministic_visual_direction
                                if target.deterministic_relation_seed is not None
                                else None
                            ),
                            "relation": target.deterministic_relation_seed,
                            "profile_transition_geometry": None,
                            "symmetry_scope": None,
                            "evidence": [query.evidence_label],
                            "reason": (
                                None
                                if target.deterministic_relation_seed is not None
                                else "pending_labeled_dimension_relation_read"
                            ),
                        }
                        for target in query.labeled_dimension_targets
                    ],
                    "unresolved": (
                        ["non_geometric_reference_region"]
                        if query.deterministic_non_geometric_reference
                        else ["rotational_symmetry_not_visible_in_region"]
                        if query.deterministic_view_owner_region_id is not None
                        else ["pending_structural_visual_read"]
                    ),
                }
                for query in queries
            ],
        },
    )


def _assert_evidence(
    evidence: list[str],
    expected: str,
    *,
    query_id: str,
) -> None:
    if set(evidence) != {expected}:
        raise StructuralContextError(f"query {query_id!r} evidence must be exactly {expected!r}")


def assemble_structural_context(
    plan: StructuralContextQueryPlan,
    answers: StructuralContextAnswers,
) -> HybridAdapterContext:
    queries = {item.query_id: item for item in plan.queries}
    answer_ids = [item.query_id for item in answers.answers]
    if len(answer_ids) != len(set(answer_ids)):
        raise StructuralContextError("structural answer query_ids must be unique")
    if set(answer_ids) != set(queries):
        missing = sorted(set(queries) - set(answer_ids))
        extra = sorted(set(answer_ids) - set(queries))
        raise StructuralContextError(
            f"structural answers do not match query plan; missing={missing}, extra={extra}"
        )

    answers_by_id = {item.query_id: item for item in answers.answers}
    region_views: list[HybridRegionView] = []
    overall_facts: list[PartialOverallDimensionFact] = []
    rotational_facts: list[PartialRotationalSymmetryFact] = []
    rotational_counterevidence: list[str] = []
    labeled_dimension_facts: list[HybridLabeledDimensionFact] = []

    for query in plan.queries:
        answer = answers_by_id[query.query_id]
        unresolved = set(answer.unresolved)
        non_geometric_reference = unresolved == {_NON_GEOMETRIC_REFERENCE_REGION}
        if query.deterministic_non_geometric_reference and not non_geometric_reference:
            raise StructuralContextError(
                f"query {query.query_id!r} changed deterministic reference classification"
            )
        if (
            query.deterministic_view_kind is not None
            and answer.view_kind != query.deterministic_view_kind
        ):
            raise StructuralContextError(
                f"query {query.query_id!r} changed deterministic OCR view kind"
            )
        if non_geometric_reference:
            if answer.view_kind is not None:
                raise StructuralContextError(
                    f"query {query.query_id!r} non-geometric reference region "
                    "must not carry view_kind"
                )
            if (
                query.labeled_dimension_targets
                or query.accepted_linear_span_lower_bounds
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} cannot defer as non-geometric "
                    "because structural geometry targets are present"
                )
            _assert_evidence(
                answer.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
            continue

        deferred_local_rotation = bool(unresolved) and unresolved.issubset(
            _REGION_LOCAL_DEFERRED_UNRESOLVED
        )
        if unresolved and not deferred_local_rotation:
            raise StructuralContextError(
                f"query {query.query_id!r} remains unresolved: {answer.unresolved}"
            )
        if answer.view_kind is None:
            raise StructuralContextError(f"query {query.query_id!r} has no resolved view_kind")

        _assert_evidence(
            answer.evidence,
            query.evidence_label,
            query_id=query.query_id,
        )
        region_views.append(
            HybridRegionView(
                region_id=query.region_id,
                view_kind=answer.view_kind,
                evidence=answer.evidence,
            )
        )

        view_axes = plan.view_axis_map[answer.view_kind]
        visible_axes = {view_axes.horizontal, view_axes.vertical}

        target_by_id = {
            item.target_id: item
            for item in query.labeled_dimension_targets
        }
        decision_ids = [
            item.target_id for item in answer.labeled_dimension_decisions
        ]
        if len(decision_ids) != len(set(decision_ids)):
            raise StructuralContextError(
                f"query {query.query_id!r} repeats labeled dimension decision"
            )
        decision_by_id = {
            item.target_id: item
            for item in answer.labeled_dimension_decisions
        }
        if set(decision_by_id) != set(target_by_id):
            missing_targets = sorted(set(target_by_id) - set(decision_by_id))
            extra_targets = sorted(set(decision_by_id) - set(target_by_id))
            raise StructuralContextError(
                f"query {query.query_id!r} labeled dimension decisions mismatch; "
                f"missing={missing_targets}, extra={extra_targets}"
            )
        for target_id in sorted(target_by_id):
            target = target_by_id[target_id]
            decision = decision_by_id[target_id]
            _assert_evidence(
                decision.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
            if target.deterministic_relation_seed is not None and (
                decision.status != "resolved"
                or decision.visual_direction
                != target.deterministic_visual_direction
                or decision.relation != target.deterministic_relation_seed
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} labeled dimension "
                    f"{target_id!r} changed deterministic relation seed"
                )
            if decision.status != "resolved":
                raise StructuralContextError(
                    f"query {query.query_id!r} labeled dimension "
                    f"{target_id!r} remains unresolved: {decision.reason}"
                )
            assert decision.visual_direction is not None
            assert decision.relation is not None
            if (
                target.deterministic_visual_direction is not None
                and decision.visual_direction != target.deterministic_visual_direction
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} labeled dimension "
                    f"{target_id!r} visual direction conflicts with "
                    "deterministic short-dimension topology"
                )
            visual_direction = (
                target.deterministic_visual_direction or decision.visual_direction
            )
            labeled_dimension_facts.append(
                HybridLabeledDimensionFact(
                    target_id=target.target_id,
                    source_item_index=target.source_item_index,
                    source_text=target.source_text,
                    region_id=query.region_id,
                    value=target.value,
                    axis=getattr(view_axes, visual_direction),
                    relation=decision.relation,
                    profile_transition_geometry=decision.profile_transition_geometry,
                    symmetry_scope=decision.symmetry_scope,
                    evidence=[
                        f"hybrid:whole:{target.source_item_index}",
                        query.evidence_label,
                    ],
                )
            )

        rotation_decision = answer.rotational_symmetry
        if rotation_decision is None and not deferred_local_rotation:
            raise StructuralContextError(
                f"query {query.query_id!r} has no explicit rotational symmetry decision"
            )
        if rotation_decision is not None:
            _assert_evidence(
                rotation_decision.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
        if rotation_decision is not None and rotation_decision.status == "not_established":
            rotational_counterevidence.extend(rotation_decision.evidence)
        if rotation_decision is not None and rotation_decision.status == "established":
            if rotation_decision.basis == "centerline":
                visual_axis_direction = rotation_decision.centerline_direction
            else:
                visual_axis_direction = query.deterministic_profile_symmetry_axis
                if visual_axis_direction is None:
                    raise StructuralContextError(
                        f"query {query.query_id!r} axial section lacks deterministic "
                        "profile symmetry axis"
                    )
            if visual_axis_direction not in ("horizontal", "vertical"):
                raise StructuralContextError(
                    f"query {query.query_id!r} has no deterministic visual rotation axis"
                )
            rotation_axis = getattr(view_axes, visual_axis_direction)
            rotational_facts.append(
                PartialRotationalSymmetryFact(
                    axis=rotation_axis,
                    evidence=rotation_decision.evidence,
                )
            )

        lower_bound_by_axis: dict[Axis, StructuralAcceptedLinearSpanLowerBound] = {}
        for bound in query.accepted_linear_span_lower_bounds:
            axis = getattr(view_axes, bound.visual_direction)
            previous = lower_bound_by_axis.get(axis)
            if (
                previous is None
                or bound.minimum_value > previous.minimum_value
            ):
                lower_bound_by_axis[axis] = bound

        seen_axes: set[Axis] = set()
        for fact in answer.overall_dimension_facts:
            if fact.axis not in visible_axes:
                raise StructuralContextError(
                    f"query {query.query_id!r} axis {fact.axis!r} is not visible "
                    f"in {answer.view_kind!r} view"
                )
            if fact.axis in seen_axes:
                raise StructuralContextError(
                    f"query {query.query_id!r} repeats overall axis {fact.axis}"
                )
            seen_axes.add(fact.axis)
            _assert_evidence(
                fact.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
            lower_bound = lower_bound_by_axis.get(fact.axis)
            if (
                lower_bound is not None
                and fact.value < lower_bound.minimum_value - 1e-9
            ):
                raise StructuralContextError(
                    f"query {query.query_id!r} overall axis {fact.axis}="
                    f"{fact.value:g} is smaller than accepted same-axis linear "
                    f"span {lower_bound.minimum_value:g} from "
                    f"{lower_bound.candidate_ids}"
                )
            overall_facts.append(
                PartialOverallDimensionFact(
                    axis=fact.axis,
                    value=fact.value,
                    evidence=fact.evidence,
                )
            )

    # An OCR-owned labeled value may be a global overall when the bounded
    # visual decision explicitly established overall_extent. This is the
    # missing bridge between labeled dimensions and global closure: the
    # numeric value comes ONLY from the validated OCR target, never pixels
    # or a newly supplied Agent value. Local labeled relations are excluded.
    #
    # Require a single corroborating label for any previously missing axis.
    # Reconcile with independently reported global facts; never select a
    # competing value or silently override an existing overall.
    all_axes: tuple[Axis, Axis, Axis] = ("X", "Y", "Z")
    labeled_overall_by_axis: dict[Axis, list[HybridLabeledDimensionFact]] = {
        "X": [], "Y": [], "Z": [],
    }
    for labeled_fact in labeled_dimension_facts:
        if labeled_fact.relation == "overall_extent":
            labeled_overall_by_axis[labeled_fact.axis].append(labeled_fact)
    for axis in all_axes:
        candidates = labeled_overall_by_axis[axis]
        if not candidates:
            continue
        previously_proven = [
            item.value for item in overall_facts if item.axis == axis
        ]
        if previously_proven:
            if any(
                not math.isclose(candidate.value, value, abs_tol=1e-9)
                for candidate in candidates
                for value in previously_proven
            ):
                raise StructuralContextError(
                    f"labeled overall_extent conflicts with direct overall for axis {axis}"
                )
            continue
        if len(candidates) != 1:
            raise StructuralContextError(
                f"ambiguous labeled overall_extent for axis {axis}: "
                f"{[candidate.target_id for candidate in candidates]}"
            )
        candidate = candidates[0]
        overall_facts.append(
            PartialOverallDimensionFact(
                axis=axis,
                value=candidate.value,
                evidence=list(candidate.evidence),
            )
        )

    by_axis: dict[Axis, list[float]] = {"X": [], "Y": [], "Z": []}
    for overall_fact in overall_facts:
        by_axis[overall_fact.axis].append(overall_fact.value)

    direct_values: dict[Axis, float] = {}
    for axis in all_axes:
        values = by_axis[axis]
        if not values:
            continue
        reference = values[0]
        if any(not math.isclose(value, reference, abs_tol=1e-9) for value in values[1:]):
            raise StructuralContextError(
                f"conflicting structural overall facts for axis {axis}: {values}"
            )
        direct_values[axis] = reference

    rotational_axes = {item.axis for item in rotational_facts}
    if rotational_axes and rotational_counterevidence:
        raise StructuralContextError(
            "conflicting structural rotational symmetry evidence: "
            "established rotation conflicts with explicit not_established "
            "counterevidence"
        )
    if len(rotational_axes) > 1:
        raise StructuralContextError(
            f"conflicting structural rotational symmetry axes: {sorted(rotational_axes)}"
        )

    merged_rotational_facts: list[PartialRotationalSymmetryFact] = []
    rotation_axis = next(iter(rotational_axes), None)
    if rotation_axis is not None:
        evidence = list(
            dict.fromkeys(
                label
                for item in rotational_facts
                for label in item.evidence
            )
        )
        merged_rotational_facts.append(
            PartialRotationalSymmetryFact(
                axis=rotation_axis,
                evidence=evidence,
            )
        )

        transverse_axes = [
            axis for axis in ("X", "Y", "Z") if axis != rotation_axis
        ]
        known_transverse = [
            axis for axis in transverse_axes if axis in direct_values
        ]
        if len(known_transverse) == 2 and not math.isclose(
            direct_values[known_transverse[0]],
            direct_values[known_transverse[1]],
            abs_tol=1e-9,
        ):
            raise StructuralContextError(
                "rotational symmetry conflicts with direct transverse overall facts: "
                f"{known_transverse[0]}={direct_values[known_transverse[0]]}, "
                f"{known_transverse[1]}={direct_values[known_transverse[1]]}"
            )

    missing_axes = [
        axis for axis in ("X", "Y", "Z") if axis not in direct_values
    ]
    if missing_axes:
        derivable = False
        if rotation_axis is not None and len(missing_axes) == 1:
            missing_axis = missing_axes[0]
            transverse_axes = [
                axis for axis in ("X", "Y", "Z") if axis != rotation_axis
            ]
            if missing_axis in transverse_axes:
                source_axis = next(
                    axis for axis in transverse_axes if axis != missing_axis
                )
                derivable = source_axis in direct_values
        if not derivable:
            raise StructuralContextError(
                f"missing structural overall fact for axis {missing_axes[0]}"
            )

    return HybridAdapterContext(
        region_views=region_views,
        overall_dimension_facts=overall_facts,
        rotational_symmetry_facts=merged_rotational_facts,
        confirmed_start_sides=[],
        labeled_dimension_facts=labeled_dimension_facts,
    )
