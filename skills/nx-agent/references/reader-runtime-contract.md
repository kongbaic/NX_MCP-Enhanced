# Reader Runtime Contract

This file is the compact runtime contract for Mode B drawing interpretation.
Normal Reader execution reads this file plus `nx-drawing-rules.md`. The longer
`drawing-reader.md` and `reader-capture-contract.md` are development/audit
references and are not normal runtime input.

## 1. Mission

Read the current engineering drawing once as a continuous first-pass session
and produce exactly one immutable `reader-observations-v1` payload.

The semantic Reader stops after `reader-observations.json`. The pipeline then
runs deterministic `assemble-reader-capture` once to produce ReaderCapture v2.
Do not run check-capture, link-capture, Resolver, Gate A, Planner, Runner or NX
until that deterministic assembly succeeds.

Do not read historical artifacts, tests, fixtures, expected answers, benchmark
operator documents, previous Agent results, or downstream outputs.

### Deterministic Reader input bundle

The current engineering drawing remains the sole authoritative geometry source.

When the pipeline successfully generated the current `reader-input.json` from the
explicit runtime-local path of the current uploaded raster drawing, Reader normally reads:

- the current source drawing;
- exactly one current `reader-input.json`;
- exactly one current `reader-contact-sheet.png`.

Do not open all individual crops sequentially. Only when one specific contact-sheet
panel is unreadable may Reader open the corresponding already-listed crop from the
manifest, then return to the same first-pass.

Hard boundaries:

- do not read `raw-evidence.json` or `reader-visual-aid.json` directly;
- do not read historical or pre-existing Reader input/contact-sheet/crop files;
- do not scan the workspace, chat history, repository, or user directories;
- do not create additional crops, PowerShell image scripts, PIL/.NET image helpers, or
  alternate image preprocessing during Reader interpretation;
- use only bounded candidate buckets; an `overflow` bucket has no candidate list and
  must be handled from the authoritative source drawing itself;
- candidate buckets may narrow visual search by region, line orientation and normalized
  position band only;
- witness anchors may indicate nearby region edges, circle-center axes or detected
  linear-pattern axes only;
- never match a dimension by numeric/pixel-scale coincidence;
- never create or merge a physical feature, assign a numeric label, or decide endpoint
  ownership solely from deterministic Reader input.

## 2. Runtime discipline

Use one continuous interpretation pass:

1. identify standard views;
2. capture view-local modeling entities;
3. capture direct values and visible dimensions;
4. resolve each dimension endpoint from visible witness geometry;
5. perform cross-view census once;
6. record explicit datum alignment and blocking ambiguity;
7. assemble one compact `reader-observations-v1` payload using temporary local keys;
8. write `reader-observations.json` exactly once;
9. run deterministic `assemble-reader-capture` exactly once;
10. if assembly fails, stop without a second interpretation or second observations file;
11. if assembly succeeds, freeze the resulting `reader-capture.json`.

Inspect the source drawing and the contact sheet directly. Do not open every listed
crop as a checklist. Open at most the specific existing crop needed for an unreadable
contact-sheet panel. Do not create new crops or preprocessing scripts, restart
interpretation, reread the whole drawing merely to satisfy bookkeeping, or perform an
open-ended self-audit loop.

## 3. Observation shape

Top level:

~~~json
{
  "schema": "reader-observations-v1",
  "overall_dimensions": {
    "length_x": 0,
    "width_y": 0,
    "height_z": 0
  },
  "views": [],
  "entities": [],
  "associations": [],
  "values": [],
  "dimensions": [],
  "datum_alignments": [],
  "unresolved": []
}
~~~

Use short temporary keys such as `front`, `side`, `front_main_bore`,
`dim_center_height`. The deterministic assembler maps those keys to formal
Capture IDs. Do not create formal V/E/A/D/U IDs yourself.

Every semantic item carries a non-empty `evidence` list using concise current-run
visual labels such as `overview`, `R1`, or `R1.vertical.right`. The assembler
copies those labels to ReaderCapture `source_ids`; do not build `source_ids`
yourself.

Allowed view kinds: `front | side | top`.

Allowed entity shapes:
`circle | concentric_circles | hidden_parallel | slot_edges | profile | other`.

Modeling-critical cylindrical semantics must use
`circle/concentric_circles/hidden_parallel`, not `other`.

Allowed direct-value fields:
`diameter, fit, thread_spec, thread_depth, depth, count, through, width,
counterbore_diameter, counterbore_depth, type`.

For threaded entities use `thread_depth`, not generic `depth`.

`required_targets=[]`, `schema_version`, `coordinate_system`, formal IDs and
ReaderCapture bookkeeping are assembler responsibilities, not Agent output.

The following item field names are exact. Do not invent aliases or pack several
semantic values into one item:

- `views[]`: `key, kind, evidence`.
- `entities[]`: `key, view_key, shape, cross_view_disposition, evidence`, optional
  `required_for_modeling`.
- `associations[]`: `entity_keys, basis, evidence`, optional
  `required_for_modeling`.
- `values[]`: exactly one semantic value per item:
  `entity_key, field, value, evidence`, optional `semantic`.
- `dimensions[]`: `key, value, axis, endpoints, evidence`, optional
  `unresolved_reason, direction, required_for_modeling`. `endpoints` is always a
  two-item list; never use `endpoint_min` / `endpoint_max`.
- resolved center/profile endpoint: `role, entity_key, basis, evidence`;
  overall endpoint: `role, evidence`; unresolved endpoint:
  `role="unresolved", unresolved_kind, evidence` and only
  `ambiguous_owner` may carry `candidate_entity_keys`.
- `datum_alignments[]`: `entity_key, axis, evidence`, optional
  `required_for_modeling`.
- `centerline_alignments[]`: `entity_keys, feature_axis, evidence`, optional
  `required_for_modeling`.
- `unresolved[]`: `kind, reason, evidence` plus only the applicable optional
  `entity_keys, dimension_key, dimension_value, field, axis, basis,
  required_for_modeling`.

Do not use `view` in place of `view_key`, do not put `diameter/fit/thread_spec`
as sibling keys inside a `values[]` item, and do not omit `reason` from
`unresolved[]`.

## 4. Source evidence

For multi-view production observations, non-empty `evidence` labels are required for:

- every view;
- every modeling-critical entity;
- every association;
- every direct value;
- every modeling-critical dimension;
- each endpoint of every modeling-critical dimension;
- every modeling-critical datum alignment;
- every blocking unresolved record.

Evidence labels are local visual references for this run only. Keep them concise and
stable. Do not create a second evidence-analysis pass merely to beautify or rename them.
The deterministic assembler converts them to ReaderCapture `source_ids`.

## 5. Cross-view identity

Every modeling-critical local entity in a multi-view drawing must set:

`cross_view_disposition = associated | unresolved | single_view`.

Association basis may use:

- `projection_alignment`
- `shared_centerline`
- `shared_center_mark`
- `leader_correspondence`
- `matching_specification`
- `explicit_section_correspondence`

Identity-sufficient association requires either:

- `explicit_section_correspondence`; or
- `projection_alignment` plus
  `matching_specification` or `leader_correspondence`.

Shared centerline/center mark alone is not identity proof.

If exactly one plausible orthographic counterpart remains and the basis is
identity-sufficient, emit one association. If multiple plausible counterparts
remain or identity evidence is insufficient, keep entities separate and emit
blocking `cross_view_identity` or `member_identity` unresolved evidence.
If no plausible modeling counterpart exists, use `single_view`.

Never merge only because dimensions match, objects are both holes, they look
symmetric, or they are nearby.

Association claims must be disjoint before the immutable write:

- one `entity_key` may appear in at most one `associations[]` item;
- one association may contain at most one entity from each view;
- if one view has a grouped entity while another view exposes multiple individual
  members, never associate the grouped entity separately to multiple members;
- for that grouped/member granularity mismatch, keep all affected entities separate,
  set their `cross_view_disposition="unresolved"`, and emit one blocking
  `member_identity` unresolved record containing the affected `entity_keys`.

Before writing `reader-observations.json`, flatten all association `entity_keys`
in memory and verify there are no duplicates. This is a contract-shape preflight,
not a second drawing interpretation.

## 6. Dimensions

Every modeling-critical visible dimension appears once in `dimensions[]`.

Axis is canonical `X | Y | Z`.

Endpoint roles:

- `overall_min`
- `overall_max`
- `entity_center`
- `unresolved`

`entity_center` requires an `entity_key` and basis
`centerline | center_mark | explicit_midline`.

Use `entity_center` only when the actual arrow/witness/extension geometry
terminates on that center reference.

An unresolved endpoint must set one:

- `intermediate_surface`
- `ambiguous_owner`
- `unsupported_reference`

`ambiguous_owner` requires supported `candidate_entity_keys`.
`intermediate_surface` and `unsupported_reference` keep
`candidate_entity_keys=[]`.

The enclosing dimension must contain `unresolved_reason`.

Do not convert an intermediate/local surface to an overall boundary or nearby
feature center merely to close the model.

If two resolved dimensions measure from opposite overall boundaries to the
same entity center on the same axis, their values must sum to that overall
extent. Otherwise the payload is inconsistent.

## 7. Overall dimensions and datums

`overall_dimensions.length_x/width_y/height_z` must be positive values
directly supported by the drawing.

Do not derive missing overall extents by arithmetic.

Record `datum_alignments` only when the drawing explicitly establishes an
entity center on `overall_center`. Visual centering or symmetry by appearance
is insufficient.

Do not calculate centered global coordinates in Reader.

## 8. Unresolved evidence

Use structured unresolved evidence for modeling-critical ambiguity.

Important kinds:

- `cross_view_identity`
- `member_identity`
- `feature_inventory`
- `feature_value`
- `start_side`
- `termination`
- `local_surface`
- `unsupported_representation`

Do not use standalone `kind="dimension_endpoint"` for new Capture; dimension
endpoint ambiguity stays inside the dimension endpoint itself.

`feature_value` requires exactly one entity plus the ambiguous `field`.

For `cross_view_identity`, list the actual cross-view candidate entities and
structured association `basis`. A unique pair with identity-sufficient basis
must be an association, not unresolved.

## 9. Freeze

Write `reader-observations.json` exactly once. Normal production Mode B must
immediately hand control to the deterministic coordinator:

~~~text
python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator <reader-observations.json> <fresh-artifact-prefix>
~~~

The artifact prefix must be a fresh direct child prefix of the current
`NX_MCP_WORKSPACE`. The coordinator owns the production sequence after visual
interpretation: ReaderObservations validation → ReaderCapture assembly and
contract check → identity linker / Gate 0 → Resolver → bounded Human
Confirmation when eligible → second resolve at most once → canonicalizer /
Gate A.

The coordinator writes a persistent `*-mode-b-state.json` before assembly.
Therefore a failed first submission is terminal for that prefix: do not rewrite
observations, do not perform a second interpretation, and do not retry by
manually invoking downstream CLI stages.

If the coordinator returns `phase=awaiting_confirmation`, present only the
generated confirmation request. After the user selects existing option IDs,
write `user-confirmations.json` and resume exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator resume <mode-b-state.json> <user-confirmations.json>
~~~

Only `exit code=0` with `phase=gate_a_pass` may continue to Planner. Any other
terminal or blocked result stops the production run.

A Mode B front-end failure from Reader input preparation through Gate A is never
eligible for Controlled Self-Healing. After the first coordinator terminal/blocked
result, do not read schema/source code, do not rewrite `reader-observations.json`,
do not choose a new artifact prefix to retry, and do not call the coordinator again.
Report the first state/phase/errors and STOP.

Standalone `assemble-reader-capture`, `check-capture`, `link-capture`,
`resolve`, confirmation, and Gate A commands remain available only for
development, audit, or explicitly requested single-stage troubleshooting; they
must not be chained manually during normal Mode B.
