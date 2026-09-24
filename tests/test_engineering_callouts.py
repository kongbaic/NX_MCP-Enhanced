from nx_mcp.drawing_intelligence.engineering_callouts import (
    parse_engineering_callout,
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
    assert parsed["ambiguities"] == [
        "leading_zero_diameter_like_token_not_promoted"
    ]
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
