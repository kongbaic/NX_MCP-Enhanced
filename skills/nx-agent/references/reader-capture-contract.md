# Reader Capture v2 Contract

## 1. Purpose

Reader Capture v2 separates three concerns that must not be mixed:

1. visual observation;
2. physical feature identity;
3. deterministic geometry resolution.

The visual Reader records only view-local observations and explicit visual
association evidence. It does not invent final physical feature IDs such as
`F_FINAL_01`, does not calculate global coordinates, and does not choose a
geometric solution.

The fixed front-end chain is:

~~~text
engineering drawing
↓
Reader Capture v2
↓
reader-capture.json
↓
deterministic identity linker
↓
Gate 0
↓
drawing-evidence.json
↓
Compiler / Resolver
↓
semantic-draft.json
↓
Gate A
~~~

Backend v1 remains outside this contract and unchanged.

## 2. Top-level schema

~~~json
{
  "schema_version": "2.0",
  "coordinate_system": "part_center_xy_bottom_z0",
  "overall_dimensions": {
    "length_x": 120,
    "width_y": 80,
    "height_z": 50
  },
  "views": [],
  "entities": [],
  "associations": [],
  "values": [],
  "dimensions": [],
  "datum_alignments": [],
  "required_targets": [],
  "observations": [],
  "unresolved_evidence": []
}
~~~

The Reader must not add final `feature:...` targets anywhere in v2 capture.

`overall_dimensions.length_x`, `width_y`, and `height_z` are mandatory
positive numeric values in a valid Capture v2 artifact. They must never be
`null`, omitted, zero, or replaced by a placeholder string.

For standard orthographic views, copying an explicitly dimensioned overall
extent into the canonical part axis is allowed and required. This is a view-axis
mapping, not prohibited coordinate arithmetic:

- front-view horizontal overall extent → X / `length_x`;
- side-view horizontal overall extent → Y / `width_y`;
- any standard-view vertical overall extent → Z / `height_z`;
- top-view horizontal axes map to X/Y according to the documented view
  orientation.

Do not leave an explicitly dimensioned overall extent blank merely because the
sheet displays it in a projected view. If an overall extent is genuinely not
readable or not present, record a blocking unresolved reason and do not write a
supposedly schema-valid capture with a null overall dimension.

## 3. Views

Only standard orthographic views are formalized:

~~~json
{
  "id": "V_FRONT",
  "kind": "front",
  "source_ids": ["OBS_FRONT_VIEW"]
}
~~~

Allowed kinds: `front`, `side`, `top`.

DETAIL / SECTION information may stay in `observations` unless another
generic contract explicitly supports it.

## 4. View-local entities

An entity is one visible candidate in one view. It is not a physical feature
identity.

~~~json
{
  "id": "E_FRONT_01",
  "view_id": "V_FRONT",
  "shape": "circle",
  "source_ids": ["OBS_FRONT_CIRCLE_01"],
  "required_for_modeling": true
}
~~~

Allowed shapes use the existing projection vocabulary:

- circle
- concentric_circles
- hidden_parallel
- slot_edges
- profile
- other

Canonical shape rules:

- `profile` is reserved for a material/body outline or a true local material
  profile;
- an edge-on cylindrical-hole projection represented by a pair of parallel
  lines is `hidden_parallel`, even when the lines are visible rather than
  dashed;
- `circle` / `concentric_circles` are used only for circular end-on
  projections;
- an outer body outline that has no supported feature-local value, dimension,
  datum, or association stays in `observations`; do not create a modeling
  entity solely to restate the overall silhouette.

Rules:

- an entity belongs to exactly one view;
- entity IDs only distinguish observations inside the current capture;
- entity IDs carry no physical meaning;
- entity IDs must not encode an assumed final feature name;
- the deterministic linker, not the Reader, creates physical feature IDs.

## 5. Association claims

If the drawing explicitly supports that view-local entities are projections of
one physical feature, record an association claim:

~~~json
{
  "id": "A_01",
  "entity_ids": ["E_FRONT_01", "E_SIDE_03"],
  "source_ids": ["OBS_SHARED_CENTERLINE", "OBS_PROJECTION_ALIGNMENT"],
  "required_for_modeling": true
}
~~~

The Reader reports the evidence-backed claim; it does not create the final
feature identity.

Allowed association evidence includes combinations of:

- orthographic projection alignment;
- shared centerline / center mark;
- a leader or witness clearly referring to the same physical item;
- matching explicit callout/specification;
- explicit DETAIL/SECTION correspondence.

Insufficient by itself:

- proximity on the sheet;
- equal numeric value;
- both objects are holes;
- apparent symmetry;
- engineering expectation.

If association is not uniquely supported:

- do not create the association;
- keep the entities separate;
- add blocking `unresolved_evidence` when modeling depends on the identity.

The linker rejects an association that tries to merge multiple distinct
view-local entities from the same standard view.

## 6. Direct values

Direct values attach to a view-local entity and a relative field, never to a
final `feature:...` target.

~~~json
{
  "id": "S_01",
  "entity_id": "E_FRONT_01",
  "field": "diameter",
  "value": 12,
  "source_ids": ["OBS_DIA_CALLOUT"]
}
~~~

Canonical direct-value vocabulary:

- `diameter` — use for cylindrical hole/bore diameter; do not emit
  `hole_diameter`;
- `fit`;
- `thread_spec`;
- `thread_depth` — use for a thread callout depth such as an explicitly
  stated thread depth;
- `depth` — reserve for a non-thread feature depth when the drawing directly
  distinguishes it from thread depth;
- `count`;
- `through`;
- `width`;
- `counterbore_diameter`;
- `counterbore_depth`;
- `type` only when the drawing explicitly supports a type value.

Do not emit alternate synonyms for the same semantic field. In particular:

- `hole_diameter` → forbidden; use `diameter`;
- generic `depth` for a threaded feature → forbidden; use
  `thread_depth`;
- `spec` for thread specification → forbidden; use `thread_spec`.

The deterministic linker retains compatibility normalization for older
captures, but a new Reader pass must emit the canonical vocabulary directly.

The Reader must not encode a calculated global coordinate as a direct value.

## 7. Dimensions

Dimension endpoints refer to overall boundaries or view-local entity centers.

~~~json
{
  "id": "D_01",
  "value": 15,
  "axis": "Z",
  "endpoints": [
    {"role": "overall_min"},
    {
      "role": "entity_center",
      "entity_id": "E_FRONT_01"
    }
  ],
  "source_ids": ["OBS_DIM_01"],
  "required_for_modeling": true
}
~~~

Allowed endpoint roles:

- overall_min
- overall_max
- entity_center

The Reader determines endpoint ownership only from actual arrows, witness
lines, extension lines, center marks, and other visible dimension geometry.

`entity_center` is allowed only when the visible dimension geometry
unambiguously terminates at the center/centerline/midline of one specific
view-local entity. Do not use `entity_center` merely because a dimension line
passes between, near, or symmetrically around hidden lines.

For repeated or overlapping hole projections, if the witness/extension
geometry does not uniquely identify each member center, keep the dimension
unresolved rather than assigning member centers by assumption.

If an endpoint is an intermediate/local surface that Capture v2 cannot
represent, do not coerce it into an overall boundary or entity center. Record
the dimension as unresolved instead.

The Reader records the measured axis but does not calculate the resulting
coordinate.

Mapping a standard-view dimension to its canonical part axis is allowed and
required. For example, a directly read overall horizontal dimension in a side
view is a Y-axis dimension. This mapping does not authorize calculating a new
numeric value; the numeric value must still come directly from the drawing.

## 8. Datum alignments

Use only when a feature center is explicitly coincident with the part overall
center datum:

~~~json
{
  "id": "DA_01",
  "entity_id": "E_TOP_02",
  "axis": "X",
  "datum": "overall_center",
  "source_ids": ["OBS_EXPLICIT_CENTERLINE"]
}
~~~

Do not create a datum alignment merely because geometry looks centered.

## 9. Required targets

For new Capture v2 production runs, the Reader writes:

~~~json
"required_targets": []
~~~

The formal strict-Evidence required-target set is derived deterministically by
the linker from:

- direct values that were actually captured;
- required dimensions and their axis-specific entity-center endpoints;
- required datum alignments.

This removes free-form Reader decisions such as `centerline` versus
`centerline.z` from physical identity and closure.

If a modeling-critical semantic is missing from the available evidence, do
not invent a required target for it. Put the missing/ambiguous semantic in
`unresolved_evidence` with `required_for_modeling=true`.

The schema retains `required_targets` only for compatibility/audit of older
captures; the linker treats Reader-provided entries as advisory provenance,
not as the formal required set.

## 10. Repeated-feature granularity

Use one canonical representation for quantity callouts:

- if one callout states a quantity such as N identical holes and individual
  member centers are not independently dimensioned/identified, create one
  view-local entity and attach `count=N`;
- if individual members have independently identifiable/dimensioned centers,
  create separate entities for those members and do not also create a grouped
  count entity for the same view;
- do not alternate between one grouped entity and N duplicate entities merely
  because both are visually plausible;
- if the drawing does not establish whether visible lines belong to distinct
  repeated members, keep the member identity/count ambiguity unresolved.

A quantity callout by itself does not authorize guessed member coordinates or
cross-view pairing.

## 11. Unresolved evidence

Any ambiguity that can change the modeled solid must remain explicit.

Typical reasons:

- cross-view identity not uniquely supported;
- physical dimension endpoint not uniquely owned;
- start side not established;
- termination not established;
- two candidate entities cannot be distinguished;
- a local surface cannot be represented by Capture v2.

No unresolved target may simultaneously receive a guessed concrete value.

## 12. First-pass immutability

The Reader writes exactly one `reader-capture.json` for the current drawing.

Before that single write, the complete in-memory payload must be validated with
the production Pydantic model:

~~~python
ReaderCapture.model_validate(payload)
~~~

A JSON parse check, top-level-key count, or custom ad-hoc validator is not a
substitute for production schema validation.

If production validation fails:

- do not write `reader-capture.json`;
- do not repair by reading the drawing a second time;
- report the validation error and stop the run.

Only a payload that passes `ReaderCapture.model_validate(payload)` may be
written as the immutable first-pass artifact.

After writing it:

- do not look at the drawing again to repair the capture;
- do not read linker / Gate 0 / Resolver / Gate A errors and reinterpret the
  drawing;
- do not read previous capture/evidence/draft/plan/report/PRT/STEP;
- do not create a second capture for the same run.

The immutable first-pass artifact for Reader benchmarking is
`reader-capture.json`, not `drawing-evidence.json`.

## 13. Deterministic identity linker

The linker:

- ignores Reader-local entity names when constructing physical feature IDs;
- groups only structurally admissible explicit association claims;
- derives physical feature IDs from normalized semantic/view signatures;
- detects indistinguishable disconnected components as identity collisions;
- emits blocking unresolved rather than choosing an arbitrary physical identity.

The linker never reads the source drawing.

## 14. Gate 0

After linking, Gate 0 validates that the generated strict EvidenceGraph is:

- schema-valid;
- target-grammar safe;
- free of parent/child object-path conflicts;
- consumable by the frozen Compiler / Resolver / Draft path.

Gate 0 may quarantine invalid representation records, but it may not invent
geometry, ownership, axis, feature identity, or coordinates.
