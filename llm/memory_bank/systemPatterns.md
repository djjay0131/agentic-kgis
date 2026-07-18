# System Patterns — agentic-kgis

Ports layer (`kg_contracts`) and engines (`kgis`) are separate; everything the
pipeline needs is an injected Protocol.

- **Ports and adapters.** `kg_contracts` defines Protocols; readers, normalizers,
  validators, builders, sinks, clocks, and ID strategies are all injected
  (ADR-0001, ADR-0002). Determinism is a property of the *configured* pipeline
  (inject `FixedClock` + `DeterministicIdStrategy`), not of the code.
- **Candidate is the universal seam.** Ingestion emits `Candidate` proposals
  (typed union: entity / relation / attribute_assertion / artifact, + scores +
  provenance); it never writes a graph. The only write surface anywhere in
  `kgis` is `CandidateSink` (ADR-0010) — the pipeline holds no reference that
  could mutate a graph. KGCS owns all canonical writes.
- **Identity is namespaced and immutable (ADR-0008).** Entities are addressed by
  `EntityRef{entity_type, namespace, key}`, validated at construction — bare
  `Label:key` strings are forbidden and rejected by the contract. `semantic_key`
  is a *composed* key (`type/namespace/key`), deliberately not a hash;
  `content_hash` rides alongside as a supplementary change-detection signal only
  (spec §5.8).
- **Two-tier validation (ADR candidate 0001).** Records are rejected *before* a
  candidate exists (`RecordValidation`, keyed on `(index, coordinates)`);
  candidates are validated after building against the ontology (the contract's
  `ValidationDecision`, keyed on `candidate_id`). A failed record never produces
  a candidate.
- **Failure isolation at every stage.** One malformed row is rejected and the run
  continues; a source read fault marks the report `incomplete` and keeps what was
  built (never a silent truncation, spec §9). Build-time data faults are caught at
  a defined boundary (`RecordDataError | pydantic.ValidationError`) and become
  record rejections with no partial candidates; a genuine builder bug propagates.
  Builders' declared `required_fields` are auto-wired into a
  `RequiredValuesValidator` so a missing endpoint/key is rejected before any
  builder runs.
- **Dry-run == execution, except submission.** A single private plan path feeds
  both `run()` and `plan()`; the plan an operator approves is the plan that runs.
- **Two-layer idempotency.** Intra-run: a repeated `semantic_key` is suppressed
  before the sink (but the key is reserved only *after* candidate validation
  succeeds, so a rejected candidate can't suppress a later valid one). Cross-run:
  the sink returns `DUPLICATE` for a key it already holds. Deterministic IDs make
  a replay recognizable as the same facts.
- **Honest nulls (ADR-0009).** Absence is reported as absence, never as a
  comforting zero: `coverage_ratio` is `None` with no ontology; `ledger_duplicates`
  is `None` without a reader; stages KGIS doesn't own are omitted, not zeroed. A
  null value produces no candidate (absence of evidence ≠ evidence of absence).
- **Reusable contract suites.** `kg_contracts.testing` ships `CandidateSinkContract`
  / `GraphMutationStoreContract`; `kgis.testing` ships `RecordReaderContract`.
  Every adapter must pass its suite.
- **Graph-level decisions via registry + advisor**, human-gated in v1 (ADR-0005).
- **Layered write path (ADR-0003, amended by v2):** deterministic gates inline,
  probabilistic curation async — owned by KGCS, downstream of the candidate ledger.
