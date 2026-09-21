# Reader Capture v2 Contract

## 1. Purpose

Reader Capture v2 separates three concerns that must not be mixed:

1. visual observation;
2. physical feature identity;
3. deterministic geometry resolution.

The visual Reader records only view-local observations and explicit visual
association evidence. It does not invent final physical feature IDs such as
`F_MAIN_HOLE`, does not calculate global coordinates, and does not choose a
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

Examples of allowed fields when directly evidenced:

- type / kind
- diameter / hole_diameter
- fit
- thread_spec / spec
- depth / thread_depth
- count
- through
- width
- counterbore_diameter
- counterbore_depth
- member.* fields when the visual evidence explicitly supports the compound
  structure

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

If an endpoint is an intermediate/local surface that Capture v2 cannot
represent, do not coerce it into an overall boundary or entity center. Record
the dimension as unresolved instead.

The Reader records the measured axis but does not calculate the resulting
coordinate.

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

Required modeling semantics refer to a local entity plus a relative field:

~~~json
{
  "entity_id": "E_FRONT_01",
  "field": "centerline.z"
}
~~~

The deterministic linker converts this to the final physical feature target.

## 10. Unresolved evidence

Any ambiguity that can change the modeled solid must remain explicit.

Typical reasons:

- cross-view identity not uniquely supported;
- physical dimension endpoint not uniquely owned;
- start side not established;
- termination not established;
- two candidate entities cannot be distinguished;
- a local surface cannot be represented by Capture v2.

No unresolved target may simultaneously receive a guessed concrete value.

## 11. First-pass immutability

The Reader writes exactly one `reader-capture.json` for the current drawing.

After writing it:

- do not look at the drawing again to repair the capture;
- do not read linker / Gate 0 / Resolver / Gate A errors and reinterpret the
  drawing;
- do not read previous capture/evidence/draft/plan/report/PRT/STEP;
- do not create a second capture for the same run.

The immutable first-pass artifact for Reader benchmarking is
`reader-capture.json`, not `drawing-evidence.json`.

## 12. Deterministic identity linker

The linker:

- ignores Reader-local entity names when constructing physical feature IDs;
- groups only structurally admissible explicit association claims;
- derives physical feature IDs from normalized semantic/view signatures;
- detects indistinguishable disconnected components as identity collisions;
- emits blocking unresolved rather than choosing an arbitrary physical identity.

The linker never reads the source drawing.

## 13. Gate 0

After linking, Gate 0 validates that the generated strict EvidenceGraph is:

- schema-valid;
- target-grammar safe;
- free of parent/child object-path conflicts;
- consumable by the frozen Compiler / Resolver / Draft path.

Gate 0 may quarantine invalid representation records, but it may not invent
geometry, ownership, axis, feature identity, or coordinates.
