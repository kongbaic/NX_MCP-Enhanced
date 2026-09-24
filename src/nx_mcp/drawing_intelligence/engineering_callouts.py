from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    return (
        text.strip()
        .replace("Φ", "Ø")
        .replace("φ", "Ø")
        .replace("∅", "Ø")
        .replace("×", "x")
        .replace("Ｘ", "x")
        .replace(" ", "")
    )


def _number(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise ValueError("engineering callout numeric values must be positive")
    return value


def parse_engineering_callout(text: str) -> dict[str, Any] | None:
    """Parse only engineering semantics explicitly present in OCR text.

    This parser deliberately does not infer a diameter from a leading zero,
    does not bind the callout to geometry, and does not choose a recessed-hole
    subtype when the source text only says 沉孔.
    """

    normalized = _normalize(text)
    upper = normalized.upper()
    facts: dict[str, Any] = {}
    ambiguities: list[str] = []
    tags: list[str] = []

    count_match = re.match(r"^(\d+)[-x]", normalized, flags=re.IGNORECASE)
    if count_match:
        count = int(count_match.group(1))
        if count > 0:
            facts["count"] = count

    thread_match = re.search(
        r"(?<![A-Z0-9])M(\d+(?:\.\d+)?(?:[xX]\d+(?:\.\d+)?)?)",
        upper,
    )
    if thread_match:
        facts["thread_spec"] = f"M{thread_match.group(1).replace('X', 'x')}"
        tags.append("thread")

    diameter_match = re.search(r"Ø(\d+(?:\.\d+)?)", normalized)
    if diameter_match:
        facts["diameter"] = _number(diameter_match.group(1))
        tags.append("diameter")

    fit_match = re.search(r"(?<![A-Z])([Hh][0-9]{1,2})(?![A-Z0-9])", normalized)
    if fit_match:
        facts["fit"] = fit_match.group(1)
        tags.append("fit")

    depth_match = re.search(r"深(?:度)?[:：]?(\d+(?:\.\d+)?)", normalized)
    if depth_match:
        depth = _number(depth_match.group(1))
        if "thread_spec" in facts:
            facts["thread_depth"] = depth
        elif "沉孔" in normalized:
            facts["recess_depth"] = depth
        else:
            facts["depth"] = depth
        tags.append("depth")

    if "通孔" in normalized:
        facts["through"] = True
        tags.append("through")

    if "沉孔" in normalized:
        facts["recessed_hole"] = True
        tags.append("recessed_hole")
        ambiguities.append("recessed_hole_subtype_not_explicit")

    leading_zero_match = re.search(
        r"(?<![A-Z0-9Ø.])(0\d+(?:\.\d+)?)(?![A-Z0-9.])",
        normalized,
        flags=re.IGNORECASE,
    )
    if leading_zero_match and "diameter" not in facts:
        ambiguities.append("leading_zero_diameter_like_token_not_promoted")

    if not facts and not ambiguities:
        return None

    return {
        "raw_text": text,
        "normalized_text": normalized,
        "facts": facts,
        "ambiguities": list(dict.fromkeys(ambiguities)),
        "tags": list(dict.fromkeys(tags)),
        "geometry_binding": "unresolved",
    }
