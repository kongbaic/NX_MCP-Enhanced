from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    benchmark_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    sys.path.insert(0, str(benchmark_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "dg_hybrid_ocr_bakeoff",
            benchmark_dir / "dg_hybrid_ocr_bakeoff.py",
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


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
