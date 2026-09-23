# Bounded Semantic Token Reader v2 Contract

This contract is used only for the bounded Region Query Reader performance smoke.
It replaces the legacy strict-answer smoke for new performance runs. It does not
replace the normal Mode B production pipeline until separately accepted.

## 1. Goal

Measure direct region-local visual semantics without making the Agent construct
the full strict `reader-semantic-answers-v1` schema.

The Agent writes one small compact file immediately after each query image.
A deterministic local assembler converts those compact files into the existing
strict answers schema and then into `reader-partial-observations.json`.

Do not create ReaderCapture, run linker, Resolver, Gate A, Planner, Runner, or NX.

## 2. Deterministic setup

Record `smoke_start` before setup.

Run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence prepare-reader-input <current-raster-path> <workspace_root>
python_exe -m nx_mcp.drawing_intelligence build-reader-semantic-queries <reader-input.json> <reader-semantic-queries.json>
~~~

Read `reader-semantic-queries.json` once.

Before Q001, delete only these exact stale outputs if they exist, without reading
their contents:

- `reader-semantic-Q001.json` through `reader-semantic-Q004.json`;
- `reader-semantic-answers.json`;
- `reader-partial-observations.json`.

Do not scan the workspace or history.

## 3. One query = one direct visual pass = one immediate compact file

Process queries once in ascending `query_id` order.

For each query:

1. Read only that query's `image_path`, exactly once.
2. Use only its `candidate_buckets` as geometry-only hints.
3. Use only its `allowed_evidence_labels`.
4. Do not open the original drawing, contact sheet, another crop, bucket crop,
   history, source code, old answer, or any unlisted image.
5. Do not use PIL/Pillow, OpenCV, System.Drawing, PowerShell/.NET image code,
   OCR, pixel measurement, line detection, thresholding, ASCII rendering,
   re-cropping, resizing, enhancement, or any programmatic image analysis.
6. Do not perform cross-view identity or global feature merge.
7. If evidence is insufficient, preserve that uncertainty. Do not reopen images.
8. Immediately write exactly one compact file for this query:
   `<workspace_root>/reader-semantic-<query_id>.json`.
9. After that file is written, do not edit, patch, diff, reread, or rename it.

Only then continue to the next query.

## 4. Compact region schema

Each file is:

~~~json
{
  "schema": "reader-semantic-region-v1",
  "query_id": "Q001",
  "view_kind": "front",
  "facts": []
}
~~~

`view_kind` is exactly one of `front`, `side`, `top`.

Each fact is one flat object. Use only fields relevant to its `kind`.

### Overall dimension fact

~~~json
{
  "kind": "overall",
  "axis": "X",
  "value": 40,
  "evidence": "R1"
}
~~~

### Entity fact

~~~json
{
  "kind": "entity",
  "key": "main_bore",
  "shape": "circle",
  "evidence": "R1"
}
~~~

Accepted shape tokens are:

- `circle`
- `concentric` or `concentric_circles`
- `hidden_parallel`
- `slot` or `slot_edges`
- `profile`
- `rectangle`, `rect`, `plane`, `plate`, `face`, `step`
- `other`

The deterministic assembler normalizes only those listed representation aliases.
It does not infer a different engineering feature.

### Direct value fact

~~~json
{
  "kind": "value",
  "entity_key": "main_bore",
  "field": "diameter",
  "value": 20,
  "semantic": "diameter",
  "evidence": "R1"
}
~~~

### Dimension fact

~~~json
{
  "kind": "dimension",
  "key": "center_height",
  "axis": "Z",
  "value": 40,
  "endpoint_a": "overall_min",
  "endpoint_b": "center:main_bore:centerline",
  "evidence": "R1.vertical.right"
}
~~~

Use exactly these endpoint token forms:

- `overall_min`
- `overall_max`
- `center:<entity_key>:centerline`
- `center:<entity_key>:center_mark`
- `center:<entity_key>:explicit_midline`
- `ambiguous:<entity_key>,<entity_key>[,...]`
- `intermediate_surface`
- `unsupported_reference`

For `ambiguous:`, list at least two explicit local entity keys visible in this
same query. Do not use it when no concrete candidates exist.

If a dimension has an unresolved endpoint, optional `reason` may contain the
local reason. The assembler supplies only a generic unresolved reason when this
field is omitted; it does not choose an owner.

Optional `direction` is `-1` or `1`.

### Datum alignment fact

~~~json
{
  "kind": "datum",
  "entity_key": "main_bore",
  "axis": "Z",
  "evidence": "R1"
}
~~~

### Unresolved / unsupported fact

~~~json
{
  "kind": "unresolved",
  "category": "unsupported_representation",
  "reason": "Visible tolerance ±0.02 is not represented by this bounded compact fact.",
  "dimension_key": "center_height",
  "dimension_value": 40,
  "field": "tolerance",
  "axis": "Z",
  "evidence": "R1.vertical.right"
}
~~~

`category` must be one of:

- `feature_inventory`
- `feature_value`
- `start_side`
- `termination`
- `local_surface`
- `unsupported_representation`
- `other`

Optional `entity_keys` may list local entities only.

Every fact may optionally set `required_for_modeling`; default is true.

Do not construct nested endpoint objects. Do not construct strict
`reader-semantic-answers-v1` yourself.

## 5. Deterministic assembly

After every expected per-query compact file has been written, run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence assemble-reader-semantic-regions <reader-semantic-queries.json> <workspace_root> <reader-semantic-answers.json> <reader-partial-observations.json>
~~~

The assembler reads only the exact files implied by the query IDs. It:

- validates every compact region file;
- validates allowed evidence labels;
- normalizes only documented shape aliases;
- expands explicit endpoint tokens into the existing strict endpoint schema;
- validates local references;
- writes strict `reader-semantic-answers.json`;
- reuses the existing deterministic merge to write
  `reader-partial-observations.json`.

It does not read images, infer endpoint ownership, perform cross-view identity,
or add missing engineering semantics.

Any assembler failure is immediate STOP. Do not edit compact files, reread an
image, inspect source code, or retry.

## 6. Timing

Record `visual_semantic_start` immediately before opening Q001.

Record `visual_semantic_end` immediately after the last expected
`reader-semantic-Q00N.json` file is fully written.

Therefore visual semantic time includes direct visual interpretation and the small
per-query compact write, but excludes deterministic strict-schema assembly.

Target: <= 120 seconds.
Hard stop: 180 seconds.

If the last compact region file is not written by 180 seconds, STOP and do not run
the assembler.

Record assembler elapsed separately.

Record `smoke_end` when the smoke stops and report `smoke_wall_elapsed`.

Final report must include:

- smoke_start / smoke_end / smoke_wall_elapsed;
- prepare and query-build elapsed;
- query count;
- visual_semantic_start / end / elapsed;
- each compact region file path;
- assembler elapsed and exit code;
- strict answers path when written;
- partial observations path when written;
- whether any stale exact output was deleted;
- whether any unlisted image or programmatic image analysis was used.
