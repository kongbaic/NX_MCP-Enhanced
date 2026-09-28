# Reader Runtime Contract

This file is the compact runtime contract for Mode B drawing interpretation.
Normal Reader execution reads this file plus `nx-drawing-rules.md`. The longer
`drawing-reader.md` and `reader-capture-contract.md` are development/audit
references and are not normal runtime input.

## 1. Mission

For a current request with an explicit runtime-local raster path, normal production
Mode B does **not** run the full free-form semantic Reader first. The sole raster
front-end entry is:

~~~text
python_exe -m nx_mcp.drawing_intelligence run-hybrid-frontend <current-raster-path> <fresh-hybrid-run-directory>
~~~

That coordinator owns deterministic Reader input preparation, production Whole +
Wide-Local Hybrid OCR, and the structural query plan. It intentionally stops at
`phase=awaiting_structural_context`. The Agent then acts only as the bounded
Structural Reader: inspect each listed `query.image_path` once. Production query images
prefer a deterministic full-drawing context image with the target region boxed; classify
the boxed region's orthographic view, not the deterministic region as an assumed
standalone view. The box is only a region-to-view locator, not an annotation-reading
boundary. An explicit overall dimension anywhere in that query image may be reported
when it unambiguously belongs to the boxed region's same orthographic view and spans
that view's complete visible part/profile extent, even when its dimension line or text
is outside the box. Never borrow an overall dimension from another view; ambiguous
ownership stays unresolved. Legacy reader-input without `structural_context_path` may
still point at the region crop. Then write
`structural-context-answers-v1` containing only view_kind, directly visible overall
X/Y/Z facts allowed by that view, the required explicit `rotational_symmetry`
decision, the exact query evidence label, and unresolved reasons. For every resolved
answer that is allowed to continue, `rotational_symmetry` must be either
`{"status":"established","axis":"X|Y|Z","evidence":[exact_query_evidence]}` or
`{"status":"not_established","axis":null,"evidence":[exact_query_evidence]}`.
Omitting the field is not equivalent to `not_established` and must fail schema
validation. The template may carry `rotational_symmetry:null` only while the answer
is pending/unresolved. If the visual evidence cannot decide the question, keep it null,
record an unresolved reason, and fail closed; do not invent an unknown/uncertain state
that can continue. Use `established` only when the complete drawing explicitly and uniquely establishes
whole-part revolution about one visible engineering axis. A printed X/Y/Z axis name is not required. Two visual bases are allowed: (1) an explicit whole-part
axial/longitudinal section or equivalent complete revolved section/profile; or (2) a
non-section longitudinal orthographic profile whose whole principal body is traversed
by one centerline and whose principal stepped/cylindrical body stages are represented
by paired opposite coaxial profile boundaries/shoulders about that same centerline.
This second basis is drafting semantics for a revolved body, not a pixel-distance or
equal-distance calculation. Map the visible centerline direction only through the
resolved view and `view_axis_map`: front horizontal=>X / vertical=>Z; side
horizontal=>Y / vertical=>Z; top horizontal=>X / vertical=>Y. Mirror symmetry alone,
a centerline without paired coaxial revolved-profile evidence, visual resemblance, or
parameter-name guessing is insufficient. `not_established` is not an uncertainty fallback: use it only when the query positively shows that whole-part rotational
symmetry does not hold. If positive establishment evidence and positive counterevidence
are both absent or ambiguous, keep `rotational_symmetry:null`, record unresolved, and
fail closed.
The Agent must never synthesize the missing overall extent.
Deterministic closure is fixed as rotation X => Y=Z, rotation Y => X=Z, rotation Z =>
X=Y, and the finalizer must preserve derivation provenance. Local dimensions must never be promoted to `overall_dimension_facts`.
An overall fact requires an explicit dimension spanning the complete visible part/profile
extent on that view axis. Chained/local lengths, hole-center spacing, center-to-edge
dimensions, radii, diameters, angles, and dimensions that cover only a local profile
segment remain local even when they are the largest visible numbers. If no explicit
overall dimension is shown for an allowed axis, omit that fact and keep it unresolved;
never invent it to satisfy the Adapter, derive it arithmetically, or estimate it from
pixels. Do not answer feature inventory, cross-view identity, local feature values,
dimension endpoint ownership, start side, termination, or pixel-derived coordinates.

Resume exactly once with:

~~~text
python_exe -m nx_mcp.drawing_intelligence resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-context-answers.json> <fresh-mode-b-prefix>
~~~

Before that one call, choose `<fresh-mode-b-prefix>` as a fresh **direct child prefix**
of the current `workspace_root` / `NX_MCP_WORKSPACE`. For example,
`<workspace_root>\\drawing-02-radial-angular-20260928-mode-b` is valid, while
`<workspace_root>\\mode-b-runs\\drawing-02-radial-angular-20260928-mode-b` is
invalid. The Hybrid Frontend run directory may be nested anywhere inside the workspace;
the Mode B artifact prefix may not. A prefix/path validation failure is terminal for
that production attempt: do not fix the path and retry, and do not choose another
prefix.

The resume path owns Structural Context assembly → Hybrid Adapter → Reader Observation
Finalizer → deterministic Mode B coordinator. Do not hand-write
`partial-reader-observations.json` or `reader-observations.json` on this raster path.

Only when the current request has no explicit runtime-local raster path, or the input
is not raster, use the fallback semantic Reader defined below: read the current
engineering drawing once as a continuous first-pass session and produce exactly one
immutable `reader-observations-v1` payload, then hand it to the Mode B coordinator.

Do not read historical artifacts, tests, fixtures, expected answers, benchmark
operator documents, previous Agent results, or downstream outputs.

### Deterministic Reader input bundle

On the Hybrid raster path, `prepare-reader-input` is an internal implementation
stage owned by `run-hybrid-frontend`; the Agent must not invoke it separately.
The first Hybrid Frontend failure is terminal for the production run; report it and
STOP. On the fallback semantic path, no raster path may be scanned or guessed.

The current engineering drawing remains the sole authoritative geometry source.

When Hybrid Frontend successfully generated the current `reader-input.json`, its
Structural Reader may inspect only the image paths listed by
`structural-context-queries.json`. The fallback semantic Reader may use the source
drawing directly under the rules below.

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

### Hybrid raster Structural Reader

For each structural query, inspect exactly its listed `image_path` once and answer
only the fields allowed by the generated query contract. Evidence must be exactly the
query's `evidence_label`. If view_kind is unresolved, provide a structured unresolved
reason and no overall facts. Never use OCR output, pixel scale, old artifacts, or
another crop to fill a missing structural answer.

### Fallback semantic Reader

Only on the no-raster/non-raster fallback path, use one continuous interpretation pass:

1. identify standard views;
2. capture view-local modeling entities;
3. capture direct values and visible dimensions;
4. resolve each dimension endpoint from visible witness geometry;
5. perform cross-view census once;
6. record explicit datum alignment and blocking ambiguity;
7. assemble one compact `reader-observations-v1` payload using temporary local keys;
8. write `reader-observations.json` exactly once;
9. immediately hand it to the deterministic Mode B coordinator;
10. if the coordinator blocks, stop without a second interpretation or second observations file.

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
  "pattern_symmetries": [],
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
- `pattern_symmetries[]`: `entity_key, axis, evidence`, optional
  `required_for_modeling`; `datum` is fixed to `overall_center`.
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

For a repeated feature controlled by one quantity/specification callout, keep one
grouped entity per view when the members differ only by their intra-group spacing.
A center-to-center spacing dimension between two members of a `count=2` group does
not by itself require two member entities. In that grouped case the spacing
dimension may use the same grouped `entity_key` for both `entity_center`
endpoints, but each endpoint must carry its own witness/center evidence and
`direction` must preserve the measured min-to-max or max-to-min order. Do not
also emit duplicate member entities for the same view.

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

For a grouped `count=2` repeated feature, `pattern_symmetries[]` is a separate
topology relation: it may record that the two-member pattern is symmetric about
the overall center on one axis when that symmetry is supported by the visible
centerline/witness layout or equivalent traceable drawing geometry. This record
does not contain member coordinates and must not calculate them from pixels.
The deterministic linker combines the proven symmetry relation with the accepted
overall extent and member-spacing dimension to derive the two engineering
coordinates. If the symmetry relation is not supported, omit
`pattern_symmetries[]` and keep the member placement unresolved.

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

On the Hybrid raster path, `resume-hybrid-frontend` writes the canonical
`reader-observations.json` through Hybrid Adapter + Reader Observation Finalizer and
immediately hands it to the deterministic Mode B coordinator. The Agent must not
create or rewrite that observations file.

On the no-raster/non-raster fallback path, write `reader-observations.json` exactly
once and immediately hand control to the deterministic coordinator:

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
After a terminal/blocked result, do not inspect OCR reports or Reader inputs; do not offer restart/fallback/retry as recovery.
Report only the first terminal phase/reason/errors and stop. End the user-facing reply
immediately after that failure report: do not append recommendations, next steps,
alternative inputs, Mode A, restart instructions, or suggestions to start a new task.
A separate fresh task may begin only when the user independently requests it in a later
message; the Agent must not prompt or steer the user to do so. If this task started with
an explicit raster path, the fallback semantic Reader cannot be selected as a recovery
path. A new fresh production run is allowed only after the user explicitly starts a
separate new task.
Report the first state/phase/errors and STOP.

Standalone `assemble-reader-capture`, `check-capture`, `link-capture`,
`resolve`, confirmation, and Gate A commands remain available only for
development, audit, or explicitly requested single-stage troubleshooting; they
must not be chained manually during normal Mode B.
