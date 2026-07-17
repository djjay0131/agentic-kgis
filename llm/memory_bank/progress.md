# Progress — agentic-kgis

- 2026-07-09: Design spec approved and committed (root commit).
- 2026-07-09: Plan 1 (bootstrap + kg_contracts) written.
- 2026-07-09: Governance established (agentic-governance v0.1): delta,
  ADRs 0001–0005, GitHub surface, memory bank. Bootstrap commits
  grandfathered; PR workflow applies from here.
- 2026-07-10: First governed review cycle (PR #1): ChatGPT feedback
  captured verbatim, dispositioned (22 accept / 3 defer / 3 reject),
  chief-reviewer Request-Changes findings addressed, owner approved.
  Spec v2 + ADRs 0006–0010 + amendments written by chief-architect agent.
  Plan 1 (2026-07-09) obsoleted — rewrite pending after PR #1 merge.

Works: kg_contracts v2 complete — identity, evidence, nine-variant
candidates (four implemented: entity, relation, attribute_assertion,
artifact), bitemporal assertions, derivation, policy, two-level stores,
curation contracts, registry, memory adapters + reusable contract
suites, public API surface, CI.
Not built yet: candidate ledger + evidence registry (Plan 2); kgis
ingestion implementations (Plan 4); kg_eval (Plan 6); KGCS Plans 3/5/6/7.
- 2026-07-12: PR #1 (spec v2 cycle) merged by owner. Governance upgraded
  to agentic-governance v0.2 (levels L0-L3, workflow-selection, steward
  INACTIVE) via delta upgrade PR.
- 2026-07-12: Plan 1 v2 executed (19 SDD tasks) — `kg_contracts` v2
  complete: identity, evidence, nine-variant candidates (four
  implemented: entity, relation, attribute_assertion, artifact),
  bitemporal assertions, derivation, policy, two-level stores, curation
  contracts, registry, memory adapters + contract suites, CI. Public API
  surface wired in `src/kg_contracts/__init__.py`; `pytest`,
  `ruff check`, `mypy src` (strict) all green; cross-repo consumability
  verified from agentic-kgcs (`CandidateSinkContract` +
  `GraphMutationStoreContract` suites pass against memory adapters).
- 2026-07-14: **Sprint 1 (Core Ingestion Engine) executed** on
  `feature/sprint-1-core-ingestion`. First end-to-end deterministic
  structured-ingestion pipeline in `src/kgis/`, built only on
  `kg_contracts` v2. Stages (all injected ports): `RecordReader`
  (iterable/CSV/JSON, no DBs) → `Normalizer` (total, deterministic,
  format-erasing) → two-tier validation (`RecordValidation` + contract
  `ValidationDecision`) → candidate builders (entity/relation/attribute,
  no graph models) → `CandidateSink`, producing `IngestionReport`
  (extends contract `IngestReport`). `IngestPipeline` satisfies
  `IngestJob`; dry-run == execution except submission; idempotency via
  intra-run semantic-key suppression + cross-run sink dedup + injectable
  deterministic IDs. 310 kgis tests (481 repo-wide), `ruff`/`mypy src`
  strict green; 8 small commits. Reusable `RecordReaderContract` added
  (`kgis.testing`). Three ADR candidates filed (`docs/adr/candidates/`):
  0001 record-scoped validation (ValidationDecision is candidate-keyed),
  0002 Source-yields-Candidate so stages compose inward, 0003 contract
  gaps (public ULID helper, GraphDescriptor attribute vocabulary). Sprint
  report: `docs/sprints/2026-07-14-sprint-1-core-ingestion.md`. NOT in
  scope (later plans): graph writes, entity resolution, LLM extraction,
  GraphRAG, persistent ledger, evidence registry, CLI.
- 2026-07-17: **PR #9 review round 2 addressed.** Three blocking correctness
  findings fixed on `feature/sprint-1-core-ingestion`: (1) data-dependent
  build failures isolated per record — `RequiredValuesValidator` auto-wired
  from `builder.required_fields`, plus a `RecordDataError | ValidationError`
  build boundary that turns build-time faults (inverted valid-time, bad
  dynamic type) into record rejections with no partial candidates, while
  genuine builder bugs still propagate; (2) `semantic_key` reserved only
  after candidate validation succeeds, so a rejected candidate cannot
  suppress a later valid same-key one; (3) `IngestionReport.succeeded`
  counts sink-side `INVALID`. +6 tests (488 passed), ruff/mypy strict clean.
  ADR candidate 0003 split into 0003-A (ULID helper) + 0004 (attribute
  vocabulary). 0001 stays local; 0002 facade deferred.
