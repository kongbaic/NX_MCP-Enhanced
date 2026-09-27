from __future__ import annotations

def _load_module():
    from nx_mcp.drawing_intelligence import hybrid_ocr

    return hybrid_ocr


def test_stdout_json_is_safe_for_windows_legacy_encoding():
    module = _load_module()

    rendered = module._stdout_json(
        {
            "diameter": "Ø20",
            "ocr": "∅20",
            "tolerance": "40±0.02",
        }
    )

    rendered.encode("cp936")
    assert "\\u00d8" in rendered
    assert "\\u2205" in rendered
