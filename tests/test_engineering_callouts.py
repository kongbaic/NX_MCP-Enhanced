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


def test_explicit_radius_callout_preserves_engineering_radius():
    for raw in ("R5", "R 5.0", "圆角R2.5"):
        parsed = parse_engineering_callout(raw)

        assert parsed is not None
        assert parsed["facts"] == {
            "radius": 5.0 if raw != "圆角R2.5" else 2.5,
        }
        assert parsed["ambiguities"] == []
        assert parsed["tags"] == ["radius"]
        assert parsed["geometry_binding"] == "unresolved"


def test_radius_can_coexist_with_other_explicit_engineering_semantics():
    parsed = parse_engineering_callout("M6 R3")

    assert parsed is not None
    assert parsed["facts"] == {
        "thread_spec": "M6",
        "radius": 3.0,
    }
    assert parsed["ambiguities"] == []
    assert parsed["geometry_binding"] == "unresolved"


def test_radius_requires_an_explicit_token_boundary():
    parsed = parse_engineering_callout("M6R3")

    assert parsed is not None
    assert parsed["facts"] == {"thread_spec": "M6"}
    assert "radius" not in parsed["facts"]


def test_leading_zero_through_hole_does_not_invent_diameter():
    parsed = parse_engineering_callout("2-06.6通孔")

    assert parsed is not None
    assert parsed["facts"] == {
        "count": 2,
        "through": True,
    }
    assert parsed["ambiguities"] == ["leading_zero_diameter_like_token_not_promoted"]
    assert "diameter" not in parsed["facts"]


def test_recessed_hole_depth_does_not_invent_subtype_or_diameter():
    parsed = parse_engineering_callout("011沉孔深6.5")

    assert parsed is not None
    assert parsed["facts"] == {
        "recess_depth": 6.5,
        "recessed_hole": True,
    }
    assert parsed["ambiguities"] == [
        "recessed_hole_subtype_not_explicit",
        "leading_zero_diameter_like_token_not_promoted",
    ]
    assert "diameter" not in parsed["facts"]


def test_plain_linear_value_is_not_an_engineering_callout():
    assert parse_engineering_callout("24") is None



def test_recess_note_keeps_neutral_geometry_facts_and_subtype_ambiguity():
    parsed = parse_engineering_callout("011沉孔深6.5")

    assert parsed is not None
    assert parsed["facts"]["recessed_hole"] is True
    assert parsed["facts"]["recess_depth"] == 6.5
    assert "recessed_hole_subtype_not_explicit" in parsed["ambiguities"]



def test_bound_recess_recovers_diameter_but_keeps_subtype_unresolved():
    parsed = parse_engineering_callout("011沉孔深6.5")
    assert parsed is not None

    recovered = _recover_geometry_backed_leading_zero_hole_value(
        parsed,
        {
            "status": "bound",
            "entity_key": "R2.C1",
        },
    )

    assert recovered["facts"]["recess_diameter"] == 11.0
    assert recovered["facts"]["recess_depth"] == 6.5
    assert recovered["facts"]["recessed_hole"] is True
    assert "leading_zero_diameter_like_token_not_promoted" not in recovered["ambiguities"]
    assert "recessed_hole_subtype_not_explicit" in recovered["ambiguities"]
    assert recovered["geometry_backed_ocr_recovery"]["field"] == "recess_diameter"
