# Candidate Value-Only Reader v3.2 Contract

This contract is used only for the value-only Reader performance smoke.
It is not yet the production Mode B Reader.

## 1. Goal

Measure the cost of direct visual value reading after deterministic candidate
location has already been provided.

The Agent must not decide endpoint ownership, feature ownership, cross-view
identity, datum semantics, or downstream geometry closure.

For each listed target, the Agent answers only one question:

- a positive visible numeric dimension value; or
- null when no clear numeric dimension value can be read for that target.

Do not emit endpoint fields. Do not emit dimension/not_dimension/uncertain
classification fields.

Stop after `reader-candidate-value-partial-observations.json`. Do not continue
to ReaderCapture, linker, Resolver, Gate A, Planner, Runner, or NX.

## 2. Deterministic setup

Record `smoke_start` before setup.

Run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence prepare-reader-input <current-raster-path> <workspace_root>
python_exe -m nx_mcp.drawing_intelligence build-reader-candidate-queries <reader-input.json> <reader-candidate-queries.json>
~~~

Before Q001, delete only these exact stale outputs if they exist, without reading
them:

- `reader-candidate-value-Q001.json` through `reader-candidate-value-Q004.json`;
- `reader-candidate-value-partial-observations.json`.

Read `reader-candidate-queries.json` once.

Do not scan the workspace, source code, history, old candidate answers, old
partial observations, or prior smoke reports.

## 3. One overlay read, values only

Process queries in ascending `query_id` order.

For each query:

1. Open only that query's candidate-overlay `image_path`, exactly once.
2. Use the visible `DGxx` overlay labels only to locate the listed target IDs.
3. Determine only the query's `view_kind`: `front`, `side`, or `top`.
4. For every listed target, copy the clear positive numeric dimension value
   visually associated with that target. Otherwise return null.
5. Do not decide whether a null target is `not_dimension` or `uncertain`.
6. Do not decide endpoint ownership or emit endpoint tokens.
7. Do not search for unlisted entities, dimensions, tolerances, datums, notes,
   holes, slots, profiles, or other engineering facts.
8. Do not open the original drawing, unannotated region crop, contact sheet,
   bucket crops, history, source, old answers, or any unlisted image.
9. Do not use PIL/Pillow, OpenCV, System.Drawing, PowerShell/.NET image code,
   OCR, pixel measurement, line detection, thresholding, ASCII rendering,
   re-cropping, resizing, enhancement, or any programmatic image analysis.
10. Immediately write exactly one answer file:
    `<workspace_root>/reader-candidate-value-<query_id>.json`.
11. After writing that file, do not edit, patch, diff, reread, or rename it.

## 4. Per-region answer schema

~~~json
{
  "schema": "reader-candidate-value-region-v1",
  "query_id": "Q001",
  "view_kind": "front",
  "targets": [
    {
      "target_id": "DG7",
      "value": 23
    },
    {
      "target_id": "DG8",
      "value": null
    }
  ]
}
~~~

Every listed target must appear exactly once.

No target object may contain `classification`, `endpoint_a`,
`endpoint_b`, entity ownership, datum ownership, or any additional semantic
field.

## 5. Deterministic assembly

After all expected value answer files are fully written, run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence assemble-reader-candidate-values <reader-candidate-queries.json> <workspace_root> <reader-candidate-value-partial-observations.json>
~~~

The assembler:

- requires exact query/target correspondence;
- creates deterministic circle projection entities from the query plan;
- maps view + target orientation to the local part axis;
- creates a dimension observation for every non-null value;
- keeps both dimension endpoints explicitly unresolved;
- preserves null targets and overflow buckets as unresolved;
- writes `reader-candidate-value-partial-observations.json`.

The assembler must not infer endpoint ownership or cross-view identity.

Any assembler failure is immediate STOP. Do not edit answers and retry.

## 6. Timing

Record `visual_value_start` immediately before opening Q001.

Record `visual_value_end` immediately after the final expected value answer
file is fully written.

Target: <= 120 seconds.
Hard stop: 180 seconds.

If the final value answer file is not written by 180 seconds, STOP and do not run
the assembler.

Record assembler elapsed separately.

The final report must include:

- smoke_start / smoke_end / smoke_wall_elapsed;
- deterministic setup elapsed;
- query count and total target count;
- visual_value_start / visual_value_end / visual_value_elapsed;
- each value answer path and non-null/null target counts;
- assembler elapsed and exit code;
- partial observations path when written;
- unlisted image usage: yes/no;
- programmatic image analysis usage: yes/no.
