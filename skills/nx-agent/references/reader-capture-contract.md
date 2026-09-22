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
  "cross_view_disposition": "associated",
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
- a modeling-critical entity carrying cylindrical semantics
  (`diameter`, `fit`, `thread_spec`, `thread_depth`, `through`,
  `counterbore_diameter`, `counterbore_depth`) must not use
  `shape="other"`; classify the direct projection as
  `circle`, `concentric_circles`, or `hidden_parallel`. If no canonical
  cylindrical projection shape is supported, use structured
  `unsupported_representation` unresolved evidence instead;
- an outer body outline that has no supported feature-local value, dimension,
  datum, or association stays in `observations`; do not create a modeling
  entity solely to restate the overall silhouette.

Rules:

- an entity belongs to exactly one view;
- entity IDs only distinguish observations inside the current capture;
- entity IDs carry no physical meaning;
- entity IDs must not encode an assumed final feature name;
- the deterministic linker, not the Reader, creates physical feature IDs.

For a modeling-critical entity on a drawing with more than one standard view,
`cross_view_disposition` is mandatory. Allowed values are:

- `associated` — the entity participates in an explicit `associations[]` claim;
- `unresolved` — a plausible cross-view/member correspondence exists but is
  not uniquely supported; the entity must be referenced by blocking
  `cross_view_identity` or `member_identity` unresolved evidence;
- `single_view` — after checking the other standard views, no plausible
  modeling-relevant counterpart is present.

This is a completeness ledger, not a physical merge decision. For every
modeling-critical entity, the Reader must explicitly record one of these
three outcomes. Leaving the decision implicit by writing neither an
association nor an unresolved record is not valid.

## 5. Association claims

If the drawing explicitly supports that view-local entities are projections of
one physical feature, record an association claim:

~~~json
{
  "id": "A_01",
  "entity_ids": ["E_FRONT_01", "E_SIDE_03"],
  "basis": ["projection_alignment", "shared_centerline"],
  "source_ids": ["OBS_SHARED_CENTERLINE", "OBS_PROJECTION_ALIGNMENT"],
  "required_for_modeling": true
}
~~~

The Reader reports the evidence-backed claim; it does not create the final
feature identity.

Association claims are disjoint identity candidates:
- one CaptureEntity may appear in at most one association claim;
- one association claim may contain at most one entity from each view;
- if one entity has multiple plausible counterparts, do not emit overlapping
  association claims; use cross_view_identity/member_identity unresolved.

Allowed `basis` values are:

- `projection_alignment`;
- `shared_centerline`;
- `shared_center_mark`;
- `leader_correspondence`;
- `matching_specification`;
- `explicit_section_correspondence`.

The Reader records these visual facts; it does not decide the final merge.
The deterministic linker applies the merge policy.

For standard orthographic views, `projection_alignment` alone is insufficient.
`shared_centerline` and `shared_center_mark` are corroborating alignment /
coaxiality evidence only; neither is identity-sufficient.

A same-physical-feature merge requires `projection_alignment` plus at least one
identity-specific basis:

- `matching_specification`;
- `leader_correspondence`.

`explicit_section_correspondence` is a standalone strong basis.

`matching_specification` means one explicit specification can be traced to the
same physical item across the projections. Different but coaxial machining
semantics (for example thread versus counterbore families) are not
`matching_specification` merely because they share a centerline.

Insufficient by itself:

- proximity on the sheet;
- equal numeric value;
- both objects are holes;
- apparent symmetry;
- engineering expectation.

If association is not uniquely supported:

- do not create the association;
- keep the entities separate;
- mark the affected entity/entities `cross_view_disposition="unresolved"`;
- add blocking `cross_view_identity` or `member_identity`
  `unresolved_evidence`.

If no plausible counterpart exists after checking the other standard views,
mark the entity `cross_view_disposition="single_view"`.

The linker rejects an association that tries to merge multiple distinct
view-local entities from the same standard view. The production contract also
rejects dispositions that do not match the actual association/unresolved
records.

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

Direct-value ownership is local and annotation-backed:

- record a value only on the view-local entity directly identified by the
  visible callout/leader/specification;
- do not copy one callout across views while physical identity is unresolved;
- when a quantity/group specification directly annotates one grouped projection,
  attach the specification and count to that grouped local entity;
- do not expand one grouped quantity callout into duplicate per-member values
  unless each member has its own independently traceable local annotation.

## 7. Dimensions

Every modeling-critical visible dimension callout must be represented exactly
once in `dimensions[]`.

Do not choose between a formal `dimensions[]` record and a separate
`dimension_endpoint` unresolved record. Endpoint ambiguity stays inside the
same dimension record.

A fully owned dimension uses resolved endpoints:

~~~json
{
  "id": "D_01",
  "value": 15,
  "axis": "Z",
  "endpoints": [
    {"role": "overall_min"},
    {
      "role": "entity_center",
      "entity_id": "E_FRONT_01",
      "basis": "centerline"
    }
  ],
  "source_ids": ["OBS_DIM_01"],
  "required_for_modeling": true
}
~~~

Allowed endpoint roles:

- `overall_min`
- `overall_max`
- `entity_center`
- `unresolved`

The Reader determines endpoint ownership only from actual arrows, witness
lines, extension lines, center marks, and other visible dimension geometry.
Each endpoint must be traced independently from the dimension line/arrow
through its actual witness/extension geometry to the measured geometry.
Nearby centerlines, matching numeric spacing, symmetry, count, or expected
pattern geometry do not substitute for that trace.

`entity_center` is allowed only when the visible dimension geometry
unambiguously terminates at one specific view-local center reference. Every
`entity_center` endpoint must include exactly one structured `basis`:

- `centerline`;
- `center_mark`;
- `explicit_midline`.

If one endpoint is not uniquely owned, keep the callout in `dimensions[]`
and use an unresolved endpoint:

~~~json
{
  "id": "D_02",
  "value": 12,
  "axis": "Y",
  "endpoints": [
    {"role": "overall_max"},
    {
      "role": "unresolved",
      "candidate_entity_ids": ["E_SIDE_01", "E_SIDE_02"]
    }
  ],
  "unresolved_reason": "visible witness geometry does not uniquely own one center",
  "source_ids": ["OBS_DIM_02"],
  "required_for_modeling": true
}
~~~

For `role="unresolved"`:

- `entity_id` is forbidden;
- `basis` is forbidden;
- `candidate_entity_ids` may list only candidates supported by the visible
  annotation geometry;
- `candidate_entity_ids` may be empty when the endpoint is a local or
  intermediate surface Capture v2 cannot identify;
- the enclosing dimension must include `unresolved_reason`.

For repeated or overlapping projections, do not assign member centers by
symmetry, count, matching pitch/span values, or engineering expectation.
A member-center-to-member-center dimension requires an independently traceable
visible endpoint for each member center. Use an unresolved endpoint whenever
either endpoint is not uniquely established by the annotation geometry.

A grouped repeated entity may nevertheless own an `entity_center` endpoint
when the current view contains an explicit shared projected centerline/center
mark for the overlapping group and the dimension witness/extension geometry
unambiguously terminates on that shared center reference. `count>1` alone does
not make such a projected-center endpoint ambiguous.

If a witness terminates on a profile/intermediate face, do not add a nearby
feature to `candidate_entity_ids` merely because a centerline is close to the
witness.

The deterministic linker converts any dimension containing an unresolved
endpoint into blocking unresolved evidence. It does not choose an endpoint.

Before the single write, resolved overall-boundary dimensions must pass a
dimension-chain consistency check. If the same entity center on one axis is
measured once from overall_min and once from overall_max, the two direct
dimension values must sum to that axis overall extent. If they do not, at least
one endpoint ownership is wrong: re-trace the visible witness/extension
geometry during the same first-pass session and leave the uncertain endpoint
unresolved. Do not preserve an internally contradictory resolved chain.

The Reader records the measured axis but does not calculate the resulting
coordinate.

Mapping a standard-view dimension to its canonical part axis is allowed and
required. This mapping does not authorize calculating a new numeric value; the
numeric value must still come directly from the drawing.

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

`overall_center` requires explicit evidence that binds the feature center to
the overall midpoint, for example an explicit symmetry/equidistance dimension,
an explicit overall-center datum/reference, or another directly traceable
center-to-overall-center annotation. A centerline that visually bisects the
outline, shares a line with another feature, aligns with a slot, or merely
appears halfway across an overall extent is not sufficient.

Before the single capture write, perform a datum/center-reference census over
all modeling-critical entities. Record every positive evidence-backed
alignment in `datum_alignments[]`; otherwise leave it absent rather than
inferring one from appearance.

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
- if individual members have independently identifiable/dimensioned centers
  with separately traceable annotation geometry, create separate entities for
  those members and do not also create a grouped count entity for the same view;
- do not alternate between one grouped entity and N duplicate entities merely
  because both are visually plausible;
- if one view is grouped while another view exposes individual members, never
  associate the grouped entity separately to multiple members;
- when unique one-to-one member correspondence is not established, preserve the
  view-local granularity and emit member_identity unresolved;
- if the drawing does not establish whether visible lines belong to distinct
  repeated members, keep the member identity/count ambiguity unresolved.

A quantity callout by itself does not authorize guessed member coordinates or
cross-view pairing.

## 11. Unresolved evidence

Any ambiguity that can change the modeled solid must remain explicit and
machine-comparable.

For new production Capture v2 output, dimension-endpoint ambiguity is represented
inside `dimensions[]` with `role="unresolved"`; do not create a standalone
`kind="dimension_endpoint"` unresolved record.

Other blocking ambiguity uses structured `unresolved_evidence`, for example:

~~~json
{
  "id": "U_01",
  "kind": "cross_view_identity",
  "reason": "human-readable audit note",
  "entity_ids": ["E_FRONT_01", "E_SIDE_02"],
  "source_ids": ["OBS_ASSOC_CANDIDATE"],
  "required_for_modeling": true
}
~~~

Allowed `kind` values in the schema are retained for compatibility:

- `cross_view_identity`;
- `dimension_endpoint` — legacy/read compatibility only; forbidden for new
  production capture by the contract checker;
- `feature_inventory`;
- `feature_value`;
- `member_identity`;
- `start_side`;
- `termination`;
- `local_surface`;
- `unsupported_representation`;
- `other`.

For `required_for_modeling=true`, new production capture must not use
`kind="other"`.

Use unresolved kinds by semantic question:

- `cross_view_identity` — whether view-local entities across views represent
  the same physical identity cannot be uniquely established;
- `member_identity` — repeated/grouped members cannot be uniquely paired;
- `feature_value` — physical/local identity is already established, but one
  specific semantic field value itself is missing/ambiguous.

A production `feature_value` unresolved record must contain exactly one
`entity_id` and a non-empty `field`. Do not use field-less
`feature_value` records as a substitute for identity ambiguity.

A blocking `cross_view_identity` or `member_identity` record must include
the affected `entity_ids`. Those entities must declare
`cross_view_disposition="unresolved"`.

Typical unresolved cases include:

- cross-view identity not uniquely supported;
- start side not established;
- termination not established;
- repeated members cannot be distinguished;
- a local surface cannot be represented by Capture v2.

No unresolved semantic may simultaneously receive a guessed concrete value.

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
