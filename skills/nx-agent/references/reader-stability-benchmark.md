# Reader First-Pass Stability Benchmark v2

## 1. Purpose

Measure whether the visual Reader produces logically stable immutable first-pass
`reader-capture.json` artifacts for the same engineering drawing after deterministic
identity linking and Gate 0 normalization.

This benchmark measures **Reader stability**, not Resolver determinism and not
NX backend stability.

## 2. Required isolation

A valid benchmark run must satisfy all of the following:

1. Use the exact same source drawing bytes for every run.
2. Use the exact same Reader contract revision.
3. Each Reader pass starts in a fresh independent model/session context.
4. The Reader receives only:
   - the current source drawing;
   - the current `drawing-reader.md`;
   - the current `reader-capture-contract.md`;
   - the visual vocabulary/rules explicitly required by those contracts.
5. The Reader must not receive or read:
   - this benchmark/operator document itself;
   - another run's capture or evidence JSON;
   - old semantic-draft/drawing JSON;
   - frozen/executable plans;
   - Runner reports;
   - PRT/STEP output;
   - benchmark expected answers.
6. Each Reader pass writes exactly one immutable first-pass `reader-capture.json` file.
7. No second-look repair, retry, rewrite, or Gate A feedback is allowed.

If these isolation requirements are not met, the result is not an independent
Reader stability benchmark.

## 3. Recommended run count

Minimum:

```text
10 independent Reader runs
```

For a difficult regression drawing, 20 runs may be used.

File naming:

```text
reader-stability/
  capture-run-01.json
  capture-run-02.json
  ...
  capture-run-10.json
  linked/
    run-01.json
    ...
    run-10.json
```

The numeric suffix is execution order only and must not affect the Reader prompt.

## 4. Deterministic normalization and comparison

For every immutable first-pass capture, run exactly once:

~~~text
python -m nx_mcp.drawing_intelligence link-capture \
  reader-stability/capture-run-01.json \
  reader-stability/linked/run-01.json
~~~

Repeat for all runs without editing either the capture or linked output.

Then compare the linked strict evidence:

~~~text
python -m nx_mcp.drawing_intelligence stability \
  reader-stability/linked/run-01.json \
  reader-stability/linked/run-02.json \
  ... \
  reader-stability/linked/run-10.json \
  --report reader-stability/report.json
~~~

The identity linker is deterministic and must not read the source image.

The comparator intentionally ignores:

- evidence IDs;
- source IDs;
- source ordering;
- JSON ordering;
- free-text observation wording.

It compares logical semantics after deterministic compilation/resolution.

## 5. Strict PASS criteria

Reader stability PASS requires:

```text
stable = true
unique_fingerprints = 1
value_drift = {}
unresolved_presence = {}
changed_sections = {}
```

All runs must therefore agree after deterministic identity linking on:

- overall dimensions;
- physical feature semantic signatures;
- feature direct semantic values;
- view/projection-derived axes;
- dimension ownership/relation semantics;
- datum alignments;
- required HARD targets;
- resolved coordinates;
- blocking unresolved target set;
- conflict state;
- dimension_closure state.

Reader-local entity IDs, evidence IDs, source IDs, and association record IDs are not required to match. Physical feature identities produced from equivalent normalized evidence must match.

## 6. Failure interpretation

### VALUE-DRIFT

Example:

```text
feature:F_MAIN_HOLE.centerline.z
run 1 = 40
run 2 = 48
```

This is a Reader semantic stability failure.

### AXIS-DRIFT

Example:

```text
feature:F_MAIN_HOLE.axis
Y ↔ X
```

This is a Reader projection/association failure.

### OWNERSHIP-DRIFT

The same annotation compiles to different relation semantics or targets across
runs.

This is a dimension endpoint/ownership failure.

### UNRESOLVED-DRIFT

A HARD target is unresolved in only some runs.

This means the Reader is changing its confidence/association decision across
independent passes.

### CONSISTENT-UNRESOLVED

A HARD target is unresolved in every run.

This is **stable behavior**, not Reader drift. It indicates a consistent
capability/evidence gap that should be addressed separately, without guessing.

## 7. SHKSS20-40 regression targets

For the current SHKSS20-40 regression drawing, the following values are
especially important drift sentinels:

- main bore axis remains Y;
- main bore center Z remains 40;
- clamp/clearance axis remains X;
- clamp center Z remains 58;
- clamp center Y remains 8;
- mounting-hole row Y remains -8;
- slot centerline X remains 0;
- unsupported mounting-hole absolute X positions must not randomly appear.

Current known capability gaps such as unsupported absolute mount-hole X
anchoring or incomplete L-body profile evidence must remain explicit unresolved
until the contract gains a fully evidence-backed representation.

The benchmark must never convert a known unresolved target into a concrete
number merely to improve PASS rate.

## 8. What this benchmark does not test

It does not test:

- Planner quality;
- Runner stability;
- Loader/NX behavior;
- PRT/STEP export;
- repair behavior;
- post-NX geometry validation.

Those belong to the frozen Backend v1 benchmark.

## 9. Backend boundary

A Reader stability failure must not be repaired by changing:

- Planner;
- Runner;
- Loader;
- NX core;
- Gate A acceptance strictness.

Fix Reader Capture extraction / association claims / deterministic identity linking, or leave the target unresolved.
