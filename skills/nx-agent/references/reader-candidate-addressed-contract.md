# Candidate-Addressed Semantic Reader v3 Contract

This contract is used only for the candidate-addressed Reader performance smoke.
It is not yet the production Mode B Reader.

## 1. Goal

Measure whether Reader semantics become fast enough when deterministic geometry
chooses the questions before the Agent sees the region.

The Agent must not inventory the whole region. It answers only the listed
`dimension_targets` in `reader-candidate-queries.json`.

Circle entities in the query are deterministic geometry facts used only by the
assembler. The Agent does not recreate or enumerate them.

Stop after `reader-candidate-partial-observations.json`. Do not continue to
ReaderCapture, linker, Resolver, Gate A, Planner, Runner, or NX.

## 2. Deterministic setup

Record `smoke_start` before setup.

Run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence prepare-reader-input <current-raster-path> <workspace_root>
python_exe -m nx_mcp.drawing_intelligence build-reader-candidate-queries <reader-input.json> <reader-candidate-queries.json>
~~~

Before Q001, delete only these exact stale outputs if they exist, without reading
them:

- `reader-candidate-Q001.json` through `reader-candidate-Q004.json`;
- `reader-candidate-partial-observations.json`.

Do not scan the workspace, source code, history, or old answers.

Read `reader-candidate-queries.json` once.

## 3. One region read, addressed targets only

Process queries in ascending `query_id` order.

For each query:

1. Open only that query's `image_path`, exactly once.
2. Determine only the query's `view_kind`: `front`, `side`, or `top`.
3. Answer every listed `dimension_target` exactly once.
4. Do not search the region for additional entities, dimensions, tolerances,
   datums, notes, holes, slots, profiles, or other facts that are not represented
   by a listed target.
5. Do not invent additional target IDs.
6. Use only the anchor refs listed in that target's `witness_hints`.
7. If a listed target cannot be decided from this single read, return
   `classification="uncertain"`. Do not reopen or zoom the image.
8. Do not open the original drawing, contact sheet, bucket crops, other region
   crops, history, source, old answers, or any unlisted image.
9. Do not use PIL/Pillow, OpenCV, System.Drawing, PowerShell/.NET image code,
   OCR, pixel measurement, line detection, thresholding, ASCII rendering,
   re-cropping, resizing, enhancement, or any programmatic image analysis.
10. Immediately write exactly one answer file:
    `<workspace_root>/reader-candidate-<query_id>.json`.
11. After writing that file, do not edit, patch, diff, reread, or rename it.

Only then continue to the next query.

## 4. Per-region answer schema

~~~json
{
  "schema": "reader-candidate-region-v1",
  "query_id": "Q001",
  "view_kind": "front",
  "targets": []
}
~~~

There must be exactly one answer object for every listed `dimension_target`.

### Confirmed visible dimension

~~~json
{
  "target_id": "DG7",
  "classification": "dimension",
  "value": 23,
  "endpoint_a": "bbox:R1.bbox.left",
  "endpoint_b": "circle:R1.C2.center_x:centerline"
}
~~~

### Not a dimension

~~~json
{
  "target_id": "DG8",
  "classification": "not_dimension",
  "value": null,
  "endpoint_a": null,
  "endpoint_b": null
}
~~~

### Cannot decide from the single read

~~~json
{
  "target_id": "DG9",
  "classification": "uncertain",
  "value": null,
  "endpoint_a": null,
  "endpoint_b": null
}
~~~

For `dimension`, `value` must be a positive visible numeric label and both
endpoint tokens are required.

For `not_dimension` or `uncertain`, value and endpoints must be null/omitted.

## 5. Endpoint tokens

Use only these token forms:

- `bbox:<listed-region-bbox-ref>`
- `circle:<listed-circle-center-ref>:centerline`
- `circle:<listed-circle-center-ref>:center_mark`
- `circle:<listed-circle-center-ref>:explicit_midline`
- `ambiguous:<listed-circle-center-ref>,<listed-circle-center-ref>[,...]`
- `intermediate_surface`
- `unsupported_reference`

A `bbox:` or `circle:` ref must appear in that same target's listed
`witness_hints.anchor_options`.

Do not convert a `linear_pattern_axis` anchor into a circle or bbox endpoint.
If the visible endpoint is only represented by a linear-pattern hint and no
safe supported endpoint token exists, use `intermediate_surface` or
`unsupported_reference`.

Do not infer endpoint ownership from equal numeric values or approximate symmetry.

## 6. Deterministic assembly

After all expected per-region answer files are fully written, run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence assemble-reader-candidate-regions <reader-candidate-queries.json> <workspace_root> <reader-candidate-partial-observations.json>
~~~

The assembler:

- requires exact query/target correspondence;
- rejects unlisted anchor refs;
- creates circle projection entities only from deterministic circle groups;
- maps orthographic view + target orientation to the local part axis;
- converts safe bbox/circle endpoint tokens into the existing strict endpoint
  representation;
- preserves uncertain targets and overflow buckets as unresolved;
- writes `reader-candidate-partial-observations.json`.

It does not read images, discover new features, infer cross-view identity, infer
unlisted endpoints, or add missing engineering semantics.

Any assembler failure is immediate STOP. Do not modify answers and retry.

## 7. Timing

Record `visual_semantic_start` immediately before opening Q001.

Record `visual_semantic_end` immediately after the final expected
`reader-candidate-Q00N.json` is fully written.

Visual semantic timing includes only the single direct region reads, addressed
target decisions, and per-region answer writes. It excludes deterministic setup
and deterministic assembly.

Target: <= 120 seconds.
Hard stop: 180 seconds.

If the final answer file is not written by 180 seconds, STOP and do not run the
assembler.

Record assembler elapsed separately and `smoke_end` when the smoke stops.

The final report must include:

- smoke_start / smoke_end / smoke_wall_elapsed;
- prepare elapsed;
- candidate-query build elapsed;
- query count and total dimension target count;
- visual_semantic_start / end / elapsed;
- each per-region answer path and answered target count;
- assembler elapsed and exit code;
- partial observations path when written;
- unlisted image usage: yes/no;
- programmatic image analysis usage: yes/no.
