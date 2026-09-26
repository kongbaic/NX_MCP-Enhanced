# Hybrid Reader Integration

The Hybrid OCR frontend is integrated through the existing Reader observation
contract. It does not write Gate A input directly.

## Production path

```text
Hybrid OCR
-> PartialReaderObservations
-> explicit structural context
-> ReaderObservations
-> ReaderCapture
-> check-capture
-> identity linker / Gate0
-> Resolver
-> optional one Human Confirmation
-> second resolve
-> Gate A
```

The Hybrid adapter may assert only facts that have already passed its
whole-drawing plus local-verification gates. Dimension endpoint ownership stays
unresolved unless another evidence stage resolves it.

The partial-observation finalizer performs no semantic inference. It requires:

- at least one explicit standard view;
- an explicit X overall fact;
- an explicit Y overall fact;
- an explicit Z overall fact;
- no conflicting facts for the same overall axis.

Missing or conflicting structural facts are fatal. A normal dimension value is
never promoted to an overall X/Y/Z dimension merely because the number matches.

## Blocking unresolved evidence

Hybrid whole/local conflicts, secondary linear assignments, unassigned linear
text, and local-only linear text are represented as
`unsupported_representation` while they remain modeling-critical. This keeps
them contract-valid and blocking rather than hiding them behind `kind=other`.

The full coverage ledger is also preserved in `observations`.

Accepted Hybrid dimension candidates also carry their geometry-only
`witness_anchor_evidence` and the merged orthogonal `witness_line_evidence`
that produced each witness into a `hybrid_dimension_anchor_ledger` observation.
This preserves deterministic endpoint evidence for later structural resolution
without promoting region bounding boxes, circle centers, pattern axes, or source
lines to dimension ownership by themselves.

## SHKSS integration fixture

`benchmarks/hybrid_integration/shkss20-40-adapter-context.json` contains
manually audited structural facts for the long-running SHKSS20-40 benchmark.

It is an integration-test fixture only. Its R1/R2 view names and 40/32/66
overall dimensions must never be used as production recognition rules.

The fixture exists solely to test whether the new Hybrid frontend can pass its
observations through the existing Capture/Linker/Resolver backend without
changing or losing them while the generic structural classifier is developed.

## Standalone finalizer

```text
python -m nx_mcp.drawing_intelligence.reader_observation_finalizer \
  reader-partial-observations.json \
  reader-observations.json
```

The command exits nonzero if an overall axis is missing, same-axis structural
facts conflict, or the partial observation payload is invalid.
