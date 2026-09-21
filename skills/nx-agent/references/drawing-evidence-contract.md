# Drawing Evidence / Deterministic Resolver Contract v1

## 1. Purpose

This contract separates **visual observation** from **geometry resolution**.

The visual stage may report only what is directly observed or associated with
drawing evidence. It must not calculate final global coordinates, invent a
relation, choose one of multiple geometric solutions, or repair a failed Gate A.

The deterministic resolver may calculate geometry only from formal evidence
records. It never reads the source image and never guesses missing intent.

## 2. Pipeline boundary

```text
engineering drawing
        ↓
Evidence Extraction
        ↓
drawing-evidence.json
        ↓
Deterministic Geometry Resolver
        ↓
semantic-draft.json
        ↓
existing canonicalizer
        ↓
existing Gate A
        ↓
Backend v1 (frozen)
```

Backend v1 remains unchanged.

## 3. Evidence Extraction responsibilities

Allowed:

- view-local vector / raster geometry observations
- OCR / dimension text
- leader, witness and extension-line endpoints
- centerline / center-mark observations
- hidden-line and circular-projection observations
- feature candidates
- same-feature candidate links with supporting observation IDs
- direct coordinate facts only when a real drawing witness establishes them
- formal relation evidence such as edge-to-center, center-to-center,
  alignment and tangent evidence
- explicit unresolved evidence

Forbidden:

- global coordinate arithmetic
- using nearby numbers as dimensions
- converting an unsigned distance into a signed coordinate without direction evidence
- choosing a start side without evidence
- inventing missing feature geometry
- writing final Gate A PASS / FAIL
- reading old plans or NX output to reinterpret the drawing

## 4. Resolver responsibilities

The Resolver owns deterministic operations such as:

- centered global bounds:
  - X = [-length_x/2, +length_x/2]
  - Y = [-width_y/2, +width_y/2]
  - Z = [0, height_z]
- edge_offset
- direct datum/boundary offset
- alignment/coaxial coordinate propagation
- center spacing/distance only when the signed solution is unique
- upper/lower tangent calculations
- conflict detection for competing writers
- required HARD target closure
- blocking unresolved when no unique solution exists

A mathematically ambiguous relation is never resolved by preference.

## 5. First v1 invariants

The following historical SHKSS failures must be deterministic:

1. overall width Y=32 and max-edge→mount-center=24 resolves to Y=-8.
2. bottom datum→Ø20 H7 center=40 resolves to Z=40, never 48.
3. conflicting direct and relation writers are rejected as conflict.
4. unsigned center spacing with only one known endpoint remains unresolved.
5. identical evidence input produces byte-equivalent logical resolution output.

## 6. External code policy

The v1 contract and resolver contain no copied third-party project code.

Future Evidence Extraction adapters may use established open-source libraries
for DXF/PDF/OCR input, but each dependency must be isolated behind an adapter
and reviewed for license compatibility before inclusion. Research repositories
may inform tests and architecture without copying their implementation.

## 7. Non-goals for v1

- no OCR engine implementation
- no DXF/PDF parser implementation
- no VLM provider integration
- no modification to Gate A
- no modification to Planner / Runner / Loader / NX core
- no post-NX drawing reinterpretation
