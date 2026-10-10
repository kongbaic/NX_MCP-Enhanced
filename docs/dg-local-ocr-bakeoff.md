# DG-local OCR Bake-off

This benchmark hardens text extraction before any text-to-DG claim is allowed
into the production Reader path.

It consumes an existing `reader-input.json` and its
`reader-visual-aid.json`. No new geometry detector is introduced.

## Architecture under test

For each bounded DG candidate:

1. derive a deterministic local ROI from its dimension axis, line span, witness
   positions, and owning region;
2. create both a tight and a wide ROI;
3. rotate vertical-candidate ROIs 90 degrees so text is horizontal;
4. tile every tight ROI into one unlabeled contact sheet;
5. tile every wide ROI into a second unlabeled contact sheet;
6. run RapidOCR exactly twice per drawing, once per sheet;
7. assign OCR items back to DG candidates only by sheet-cell coordinates;
8. parse engineering tokens deterministically;
9. accept a value only when the same unique token appears in both tight and wide
   ROI results; otherwise keep the candidate unresolved.

OCR confidence is recorded but is never a correctness gate.

A plain leading-zero integer such as `012` is treated as ambiguous and cannot
be normalized to `12` or inferred as `Ø12`.

## Acceptance gate

For the current SHKSS20-40 validation:

- total OCR inference target: <= 5 seconds per drawing;
- automatically accepted wrong DG/value claims: exactly 0;
- unresolved is allowed and preferred over a wrong claim;
- the previously observed high-confidence `66 -> 63` substitution is a
  mandatory inspection case;
- no output from this benchmark may enter ReaderCapture, Resolver, Gate A,
  Planner, Runner, or NX.

If the same wrong token survives both tight and wide local views, local
RapidOCR consensus alone is insufficient. The next step is a second OCR engine
only for unresolved or suspicious local ROIs, not a return to whole-drawing
Agent vision.
