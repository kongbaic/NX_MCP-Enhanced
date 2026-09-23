# Hybrid Dimension Ownership Feasibility Smoke

Goal: decide quickly whether RawEvidence v1 materially improves dimension endpoint ownership on SHKSS20-40.

Time budget: 5 minutes. If not finished within 5 minutes, stop and report HYBRID_DIMENSION_TIMEOUT.

Inputs:
- current SHKSS20-40 source drawing;
- RawEvidence v1 produced by the raster experiment.

Rules:
- The source drawing is authoritative.
- RawEvidence v1 is pixel geometry only. It does not assert dimension labels or endpoint semantics.
- Do not read historical captures, benchmark artifacts, tests, fixtures, expected answers, or downstream NX artifacts.
- Do not read full Reader contracts.
- Do not create ReaderCapture or run linker, Resolver, Gate A, Planner, Runner, or NX.
- Do not perform open-ended self-audit.
- Use dimension_geometry_candidates only as geometric witnesses; read the visible numeric dimension labels from the source drawing.

Evaluate only these visible dimensions:
- front view: 8
- front view: 24
- front view: 40±0.02
- side view: 24

For each dimension:
1. identify the best matching dimension_geometry_candidate;
2. identify the two witness positions that correspond to the visible dimension arrows / extension geometry;
3. classify each endpoint as one of:
   - overall_min
   - overall_max
   - entity_center
   - intermediate_surface
   - unresolved
4. if entity_center, name the visible feature;
5. if evidence is insufficient, return unresolved rather than guessing.

Return compact JSON only:

{
  "dimensions": [
    {
      "view": "",
      "label": "",
      "candidate_id": "",
      "witness_positions_px": [],
      "endpoint_a": {"role": "", "feature": null},
      "endpoint_b": {"role": "", "feature": null},
      "confidence": "high|medium|low",
      "basis": ""
    }
  ],
  "raw_evidence_helped": true,
  "remaining_gap": [],
  "result": "useful|not_useful"
}
