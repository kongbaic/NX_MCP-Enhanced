# Whole + Local OCR Association Bake-off

This benchmark tests the next deterministic OCR architecture after the
tight/wide local-only experiment.

## Hypothesis

Whole-drawing RapidOCR is fast and provides a useful text inventory with source
bounding boxes. Wide local, orientation-normalized OCR is useful as an
independent presentation of the same drawing evidence.

The benchmark therefore uses exactly two OCR calls:

1. whole drawing at native orientation;
2. one batched wide local sheet built from deterministic DG geometry.

## Deterministic association

Only standalone linear numeric tokens and plus/minus tolerance tokens are
eligible for a linear DG candidate.

Diameter, radius, thread, and other callout tokens are excluded from this path
and must be handled by the appropriate circle/leader association layer.

A whole-drawing OCR observation may be assigned to at most one DG candidate.
The assignment requires:

- compatible text and candidate orientation, unless the OCR bbox is ambiguous;
- the OCR bbox center to lie inside that candidate's deterministic wide ROI;
- nearest perpendicular distance to the candidate axis;
- a minimum distance margin over the next competing candidate.

If one DG receives multiple globally assigned linear tokens, its nearest token
must also win by the same margin.

The final value is accepted only when the globally associated token is also
present in that DG's wide local OCR result.

## Locked SHKSS20-40 gate

Before production integration:

- total OCR inference must be <= 5 seconds per drawing;
- automatically accepted wrong DG/value claims must be exactly 0;
- at least 4 of the 5 already-audited key linear dimensions should close
  automatically in this benchmark;
- a whole-drawing partial digit such as `6` conflicting with local `66`
  must remain unresolved;
- diameter/radius/thread text must never be forced into a linear DG;
- no benchmark output may enter ReaderCapture, Resolver, Gate A, Planner,
  Runner, or NX.

If a wrong accepted value occurs, or only 3 or fewer audited key linear
dimensions close, stop tuning association thresholds. The next experiment is a
second OCR engine for unresolved/suspicious local ROIs rather than further
threshold fitting.


## Reverse coverage / no-silent-loss contract

Passing a DG/value correctness gate is not sufficient. Every whole-drawing OCR
observation must remain visible after association even when it is not accepted.

The report therefore contains a reverse coverage ledger with mutually exclusive
whole-observation states:

- accepted support;
- global/local conflict;
- unconfirmed global proposal;
- secondary assignment not selected as the candidate proposal;
- unassigned standalone linear observation;
- routed-elsewhere or currently unclassified observation.

Linear tokens seen only by the wide local sheet are also preserved separately.
For example, a whole observation of `6` and a local observation of `66` are
both retained when they disagree.

The benchmark requires `observed_silent_drop_count == 0`. This guarantees
bookkeeping completeness for observations already extracted by OCR. It does not
prove that OCR extracted every piece of engineering text present in the source
drawing; that remains a separate extraction-coverage problem.
