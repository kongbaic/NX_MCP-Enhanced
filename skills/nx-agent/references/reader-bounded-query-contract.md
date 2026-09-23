# Bounded Semantic Query Reader Contract

This contract is used only when the user explicitly requests a bounded semantic
query / Region Query Reader performance smoke. It does not replace the normal
Mode B production pipeline until this path is separately accepted.

## 1. Mission

Measure whether small region-local semantic questions are fast enough to keep.

The current uploaded engineering drawing remains the sole authoritative geometry
source. Deterministic crops are derived visual aids from that same current drawing.

Stop after producing and validating:

- `reader-semantic-queries.json`;
- `reader-semantic-answers.json`;
- `reader-partial-observations.json`.

Do not create ReaderCapture, run check-capture, link-capture, Resolver, Gate A,
Planner, Runner, or NX in this smoke.

## 2. Deterministic setup

With the current runtime-local raster path and current workspace, run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence prepare-reader-input <current-raster-path> <workspace_root>
python_exe -m nx_mcp.drawing_intelligence build-reader-semantic-queries <reader-input.json> <reader-semantic-queries.json>
~~~

Both commands must succeed before visual interpretation starts.

Do not scan the workspace or history. Do not reuse an older query plan.

## 3. Region query discipline

Read `reader-semantic-queries.json` once.

Process every query exactly once in ascending `query_id` order.

For each `kind="region_observation"` query:

- read only that query's `image_path`;
- use only that query's `candidate_buckets` as geometry-only search hints;
- use only `allowed_evidence_labels` in the answer;
- do not open the original drawing, contact sheet, another region crop, another
  bucket crop, or any unlisted image;
- do not scan files or search for alternate visual evidence;
- interpret the listed crop directly with the Agent's visual capability in one pass;
- do not inspect image pixels programmatically and do not use PIL, Pillow, OpenCV,
  System.Drawing, ImageMagick, PowerShell/.NET image code, GetPixel, LockBits,
  edge/line detection, thresholding, OCR, ASCII rendering, or any other generated
  text/pixel representation of the crop;
- do not crop, resize, resample, enhance, threshold, convert, redraw, or otherwise
  transform the query image;
- do not measure pixel coordinates, arrow positions, centerlines, or distances with
  code. Candidate buckets are hints only and must not trigger a secondary image
  analysis pipeline;
- do not perform cross-view identity;
- do not merge physical features across views;
- do not create final ReaderCapture IDs;
- if the local crop is insufficient, keep the local item unresolved instead of
  opening more images.

The purpose is bounded local semantics, not whole-drawing closure.

## 4. Answer shape

Write exactly one `reader-semantic-answers.json` after all listed region queries
have been answered.

Top level:

~~~json
{
  "schema": "reader-semantic-answers-v1",
  "answers": []
}
~~~

Each answer corresponds to exactly one query and contains:

~~~json
{
  "query_id": "Q001",
  "view_kind": "front",
  "evidence": ["R1"],
  "overall_dimension_facts": [],
  "entities": [],
  "values": [],
  "dimensions": [],
  "datum_alignments": [],
  "unresolved": []
}
~~~

Use short local keys only inside one query, for example `main_bore` or
`center_height`.

Entity:

~~~json
{
  "key": "main_bore",
  "shape": "circle",
  "evidence": ["R1"],
  "required_for_modeling": true
}
~~~

Direct value:

~~~json
{
  "entity_key": "main_bore",
  "field": "diameter",
  "value": 20,
  "semantic": "diameter",
  "evidence": ["R1"]
}
~~~

Visible dimension:

~~~json
{
  "key": "center_height",
  "value": 40,
  "axis": "Z",
  "endpoints": [
    {
      "role": "overall_min",
      "evidence": ["R1.vertical.right"]
    },
    {
      "role": "entity_center",
      "entity_key": "main_bore",
      "basis": "centerline",
      "evidence": ["R1.vertical.right"]
    }
  ],
  "unresolved_reason": null,
  "direction": null,
  "evidence": ["R1.vertical.right"],
  "required_for_modeling": true
}
~~~

If an endpoint cannot be uniquely owned from the query image, use
`role="unresolved"` plus one of:

- `intermediate_surface`
- `ambiguous_owner`
- `unsupported_reference`

Do not guess an owner just to close the dimension.

Overall dimension facts are local directly visible facts only:

~~~json
{
  "axis": "X",
  "value": 40,
  "evidence": ["R1"]
}
~~~

Do not derive missing extents by arithmetic.

### Strict answer-schema rules

`reader-semantic-answers-v1` is strict. Do not invent fields, aliases, wrapper
objects, or alternate shapes. Every object may contain only the fields shown by
this contract.

The exact allowed fields are:

- answer: `query_id`, `view_kind`, `evidence`,
  `overall_dimension_facts`, `entities`, `values`, `dimensions`,
  `datum_alignments`, `unresolved`;
- entity: `key`, `shape`, `evidence`, `required_for_modeling`;
- direct value: `entity_key`, `field`, `value`, `semantic`, `evidence`;
- dimension: `key`, `value`, `axis`, `endpoints`,
  `unresolved_reason`, `direction`, `evidence`,
  `required_for_modeling`;
- dimension endpoint: `role`, `entity_key`, `candidate_entity_keys`,
  `basis`, `unresolved_kind`, `evidence`;
- datum alignment: `entity_key`, `axis`, `evidence`,
  `required_for_modeling`;
- unresolved: `kind`, `reason`, `entity_keys`, `dimension_key`,
  `dimension_value`, `field`, `axis`, `evidence`,
  `required_for_modeling`.

For unresolved items, `kind` must be one of:

- `feature_inventory`
- `feature_value`
- `start_side`
- `termination`
- `local_surface`
- `unsupported_representation`
- `other`

If a visible engineering fact cannot be represented by the fields above, do not
extend the schema. Preserve it as `kind="unsupported_representation"`.

This applies in this smoke to facts such as a tolerance attached to a dimension,
a datum letter/identifier, surface roughness such as Ra, or a GD&T frame whose
full semantics are not represented by this answer schema.

Example for a visible dimension tolerance that the current smoke schema cannot
carry directly:

~~~json
{
  "kind": "unsupported_representation",
  "reason": "Visible tolerance ±0.02 is not represented by the bounded answer dimension schema.",
  "entity_keys": [],
  "dimension_key": "center_height",
  "dimension_value": 40,
  "field": "tolerance",
  "axis": "Z",
  "evidence": ["R1.vertical.right"],
  "required_for_modeling": true
}
~~~

`dimension_key` may be used only when that local dimension is present in the same
answer. Otherwise leave it null. `entity_keys` may contain only local entities
declared in the same answer.

Do not read Python source code to discover or repair the answer shape during this
performance smoke. This contract is the complete Agent-facing answer contract.
If the answer cannot be written conformingly from this contract alone, report the
failure and stop.

## 5. Deterministic merge

After writing answers once, run exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence merge-reader-semantic-answers <reader-semantic-queries.json> <reader-semantic-answers.json> <reader-partial-observations.json>
~~~

The merge must return exit code 0 and `written=true`.

The merge only:

- validates query/answer correspondence;
- rejects evidence labels outside the query;
- prefixes local keys with their region ID;
- preserves local unresolved semantics.

It does not perform cross-view association or dimension ownership inference.

If merge fails, stop. Do not reread images, inspect implementation source, reshape
the answer, modify the same answer file, or retry merge. Report the first merge
error exactly as returned. A retry would invalidate this performance smoke.

## 6. Timing report

For this smoke report only:

- prepare-reader-input elapsed;
- build-reader-semantic-queries elapsed;
- visual start and end time for all region queries;
- total visual semantic elapsed;
- query count;
- reader-semantic-answers.json path;
- merge-reader-semantic-answers elapsed;
- reader-partial-observations.json path;
- whether any unlisted image was opened.

The visual semantic target is <= 2 minutes. Hard stop at 3 minutes.
