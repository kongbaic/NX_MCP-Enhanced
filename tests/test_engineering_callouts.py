from nx_mcp.drawing_intelligence.engineering_callouts import (
    parse_engineering_callout,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    _recover_geometry_backed_leading_zero_hole_value,
)


def test_thread_callout_preserves_thread_and_depth():
    parsed = parse_engineering_callout("M6深12")

    assert parsed is not None
    assert parsed["facts"] == {
        "thread_spec": "M6",
        "thread_depth": 12.0,
    }
    assert parsed["ambiguities"] == []
    assert parsed["geometry_binding"] == "unresolved"


def test_explicit_diameter_and_fit_are_safe():
    parsed = parse_engineering_callout("∅20 H7")

    assert parsed is not None
    assert parsed["facts"] == {
        "diameter": 20.0,
        "fit": "H7",
    }
    assert parsed["ambiguities"] == []


def test_leading_zero_through_hole_does_not_invent_diameter():
    parsed = parse_engineering_callout("2-06.6通孔")

    assert parsed is not None
    assert parsed["facts"] == {
        "count": 2,
        "through": True,
    }
    assert parsed["ambiguities"] == ["leading_zero_diameter_like_token_not_promoted"]
    assert "diameter" not in parsed["facts"]


def test_recessed_hole_depth_establishes_counterbore_without_inventing_diameter():
    parsed = parse_engineering_callout("011沉孔深6.5")

    assert parsed is not None
    assert parsed["facts"] == {
        "counterbore_depth": 6.5,
        "recessed_hole": True,
    }
    assert parsed["ambiguities"] == [
        "leading_zero_diameter_like_token_not_promoted",
    ]
    assert "diameter" not in parsed["facts"]


def test_plain_linear_value_is_not_an_engineering_callout():
    assert parse_engineering_callout("24") is None



def test_plain_recess_note_without_depth_keeps_subtype_ambiguity():
    parsed = parse_engineering_callout("011沉孔")

    assert parsed is not None
    assert parsed["facts"]["recessed_hole"] is True
    assert "counterbore_depth" not in parsed["facts"]
    assert "recessed_hole_subtype_not_explicit" in parsed["ambiguities"]



def test_bound_counterbore_recovers_canonical_counterbore_diameter():
    parsed = parse_engineering_callout("011沉孔深6.5")
    assert parsed is not None

    recovered = _recover_geometry_backed_leading_zero_hole_value(
        parsed,
        {
            "status": "bound",
            "entity_key": "R2.C1",
        },
    )

    assert recovered["facts"]["counterbore_diameter"] == 11.0
    assert recovered["facts"]["counterbore_depth"] == 6.5
    assert recovered["facts"]["recessed_hole"] is True
    assert "leading_zero_diameter_like_token_not_promoted" not in recovered["ambiguities"]
    assert "recessed_hole_subtype_not_explicit" not in recovered["ambiguities"]
    assert recovered["geometry_backed_ocr_recovery"]["field"] == "counterbore_diameter"
