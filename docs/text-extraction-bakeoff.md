# Text Extraction Bake-off

This benchmark is isolated from production Mode B. It compares text extraction
engines only. It does not perform text-to-DG association, endpoint ownership,
cross-view identity, Resolver work, or NX modeling.

## Locked decision gate

Use three real mechanical drawings.

Every benchmark result must include:

- recognized text;
- polygon/bounding box;
- confidence;
- orientation estimate;
- per-image elapsed time.

The dataset must contain examples of:

- integer dimensions;
- decimal dimensions;
- diameter symbols;
- radius notation;
- metric thread notation;
- plus/minus tolerance;
- fit notation such as H7;
- horizontal text;
- vertical/rotated dimension text.

Performance gate:

- CPU warm-run <= 5 seconds per image;
- model/engine initialization is reported separately and excluded from warm-run inference time.

Correctness gate:

- wrong engineering tokens must not be silently accepted;
- exact-token recall is always reported;
- exact-token precision is reported only when the manifest declares a complete token inventory;
- preserve or normalize common diameter glyph variants to `Ø`;
- a missed token is preferable to a wrong token passed downstream.

The bake-off does not select a production engine automatically. Results are
reviewed before any text-to-DG association code is written. A partial
`expected_tokens` list must set `complete_token_inventory=false`; unrelated
title-block or note text is then not mislabeled as a false positive.

## Initial candidates

### RapidOCR

Primary lightweight candidate.

Expected local install for the bake-off only:

~~~powershell
python -m pip install rapidocr onnxruntime
~~~

The benchmark imports `rapidocr` only when that engine is selected. RapidOCR
is not added to `pyproject.toml` or production dependencies.

### Tesseract

Traditional control baseline.

The benchmark invokes the external `tesseract` executable with TSV output.
Tesseract is not a production recommendation; it provides an inexpensive
reference point for bbox/confidence and mixed-orientation behavior.

### PaddleOCR

Second neural OCR candidate, to be added to the harness only after the first
RapidOCR/Tesseract run establishes whether a heavier comparison is necessary.
It is deliberately not added to production dependencies.

## Run

Create this local benchmark tree:

~~~text
benchmarks/text_extraction/
  manifest.json
  images/
    drawing-01.png
    drawing-02.png
    drawing-03.png
~~~

Then run, for example:

~~~powershell
python benchmarks/text_extraction_bakeoff.py benchmarks/text_extraction/manifest.json benchmarks/text_extraction/report.json --engine rapidocr
~~~

Or compare two engines:

~~~powershell
python benchmarks/text_extraction_bakeoff.py benchmarks/text_extraction/manifest.json benchmarks/text_extraction/report.json --engine rapidocr --engine tesseract
~~~

Do not connect the result to ReaderCapture / linker / Resolver / Gate A before
the bake-off is reviewed.

## Fixed three-drawing benchmark set

The first local bake-off uses exactly three drawings:

1. the current SHKSS20-40 authoritative raster copied from
   `<workspace>/reader-crops/overview.png`;
2. `2D PROFILE DRAWING WITH RADIAL AND ANGULAR DIMENSION.png` from
   `Aadityajain-hub/AutoCAD_2D_Drawings`;
3. `Screenshot AutoCAD Task 1.png` from `SivaTX92/AutoCAD-Task-1`.

Run:

~~~powershell
.\benchmarks\text_extraction\setup_bakeoff.ps1 -Workspace "C:\Users\Kavin\NX_MCP_FAST_BASELINE"
~~~

The script creates `benchmarks/text_extraction/manifest.json` and downloads or
copies the exact three images. Do not substitute other drawings during the first
comparison run.
