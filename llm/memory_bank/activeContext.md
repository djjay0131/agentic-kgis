# Active Context — agentic-kgis

Update 2026-07-22: **Plan 2 (candidate ledger + evidence registry) complete.**
Issue #7 closed: `kg_contracts._frozen.FrozenDict` makes dict-typed payload
fields (curation payloads/reversal data/score vectors, candidate
properties/parameters/conclusion/representations, derivation parameters,
registry factor_scores) read-only at rest with byte-stable JSON round-trip;
this is the only Plan 2 group that touched `kg_contracts`. Everything else is
net-new under `src/kgis/`: `SqliteCandidateLedger` (`src/kgis/ledger/`)
persists candidates in SQLite behind the frozen `CandidateSink`/`LedgerReader`
ports with cross-run idempotency by semantic key, the full persisted
`LedgerRow` (dedup key, retry counter, quarantine reason, bitemporal
valid/transaction time), an auditable `ProcessingState` lifecycle (R1:
`OBSOLETE` replaces spec `SUPERSEDED`), and a revoke/erase governance surface
with `IdentityMode`/`ConsumerProfile` (ADR-0012/0013/0014, Issue #2 folded
in). `SqliteEvidenceRegistry` (`src/kgis/evidence/`) persists PRESENT/ABSENT/
ERROR `Evidence` resolvable by `evidence_id` and resolves `EvidenceRef`
relationships without silently dropping dangling refs. `SqliteAuditStream`
writes an immutable `audit_records` row per ledger transition (hash-only
tombstone on erase). The already-merged Plan 4 ingestion pipeline composes
onto the persistent ledger unchanged — `plan().plan.ledger_duplicates` now
returns a real count. Public surfaces stabilized: `from kgis.ledger import
SqliteCandidateLedger, SqliteAuditStream, LedgerRow, PersistentLedgerContract,
IdentityMode, ConsumerProfile, BASEBALL_AI_PROFILE, IdentityResolver,
IllegalTransitionError, open_ledger_db` and `from kgis.evidence import
SqliteEvidenceRegistry, EvidenceRegistryContract, EvidenceNotFoundError,
open_evidence_db`. All new stores pass the reusable contract suites
(`CandidateSinkContract`/`LedgerReaderContract` unchanged from Plan 1, plus
new kgis-local `PersistentLedgerContract`/`EvidenceRegistryContract`). 551
tests green (549 baseline + public-API surface test), `ruff check src tests`
clean, `mypy src` strict clean. NEXT: Plan 3 (curation core + executor,
KGCS) — the canonical-graph write path (`GraphMutationStore`) is still
unbuilt; entity resolution (Plan 5) and durable review-queue (Plan 6) also
deferred.

Update 2026-07-17: **PR #9 review round 2 addressed.** A fresh full review of
PR #9 (Sprint 1) raised three blocking correctness findings; all three are
fixed on `feature/sprint-1-core-ingestion`. (1) Data-dependent build failures
no longer abort the run — the pipeline auto-wires
`RequiredValuesValidator(builder.required_fields)`, and build-time faults
(inverted valid-time, bad dynamic type, contract-model rejections) are caught
at a defined boundary (`RecordDataError | pydantic.ValidationError`) and become
structured record rejections; no partial candidates from a failed row; genuine
builder bugs still propagate. (2) A rejected candidate no longer reserves its
`semantic_key` — `seen_keys` is updated only after candidate validation
succeeds. (3) `IngestionReport.succeeded` now counts sink-side `INVALID`.
New `RecordDataError` in `kgis.errors`. +6 tests (488 passed), ruff/mypy strict
clean. ADR candidate 0003 split into 0003-A (public ULID helper) and 0004
(GraphDescriptor attribute vocabulary) per the reviewer — unrelated decisions,
different blast radii. ADR-candidate dispositions from the review: 0001 keep
local, promote to contract only via a separate PR after KGCS confirms the
shape; 0002 defer the `Source.fetch()` facade until a real consumer needs it.
NEXT (author): push branch, post the author-response comment on PR #9, request
another review pass. Then Plan 2 (candidate ledger + evidence registry).

Update 2026-07-14: **Sprint 1 (Core Ingestion Engine) complete** on
`feature/sprint-1-core-ingestion`. First deterministic
structured-ingestion pipeline in `src/kgis/`, on `kg_contracts` v2 only:
reader (iterable/CSV/JSON) → normalize (total) → validate (two-tier) →
build candidates (entity/relation/attribute) → `CandidateSink` →
`IngestionReport`. `IngestPipeline` satisfies `IngestJob`; dry-run,
idempotency (intra-run suppression + cross-run sink dedup + injectable
deterministic IDs), full DI. 481 tests repo-wide, `ruff`/`mypy src`
strict green, 8 small commits. Three ADR candidates in
`docs/adr/candidates/` for reviewer/owner disposition (0001 record-scoped
validation, 0002 Source composition, 0003 ULID helper + attribute
vocabulary gaps). Report:
`docs/sprints/2026-07-14-sprint-1-core-ingestion.md`. NEXT (author):
push branch + open draft PR (author responsibility per `CONTRIBUTING.md`);
then reviewer reviews and the ADR candidates get dispositioned. After that,
Plan 2 (candidate ledger + evidence registry) makes idempotency durable and
lets the null-value rule record absence via `Evidence` ABSENT. Deferred
within kgis: `Source.fetch()` facade, CLI, streaming/bounded dedup. Scope
held: no graph writes, no ER, no LLM extraction, no GraphRAG this sprint.

Update 2026-07-12: **Plan 1 v2 complete.** `kg_contracts` public API v2
shipped (Tasks 3–18 implemented, Task 19 wired the top-level export
surface): security context/deletion semantics, evidence, immutable
identity, derivation provenance, contract/component versioning, the
nine-variant candidate union (four implemented — entity, relation,
attribute_assertion, artifact — five spec-level), bitemporal assertions
and canonical entities, the confidence policy, two-level (candidate
sink / graph mutation) store protocols, curation-plane contracts,
ingestion protocols, the graph registry, and memory adapters + reusable
contract suites (`kg_contracts.testing`). `pytest`, `ruff check`,
`mypy src` (strict) all green in agentic-kgis; CI wired
(`.github/workflows/ci.yml`). Cross-repo verified: agentic-kgcs installs
`kg_contracts` editable and runs the `CandidateSinkContract` and
`GraphMutationStoreContract` suites green against the memory adapters.
NEXT: Plan 2 (candidate ledger + evidence registry).

Prior state (2026-07-10): External design review (ChatGPT) dispositioned
(chief-reviewer-checked, owner-approved) → **spec v2** + ADRs 0006–0010 +
amendments to 0002/0004/0005 (0003 superseded in part) + delta amendment,
all on PR #1. Key changes: candidate ledger / canonical graph / derived
projections separation with curation epochs; 9-variant typed candidate
union + CandidateScores; Evidence first-class (present/absent/error);
immutable identity IDs + namespaced aliases; ER = calibrated matcher +
bounded LLM adviser (debate → eval arm); bitemporal contracts; kg_eval
third package; five-phase adoption (VTTSI reference → baseball → traffic
shadow → research retrofit → construction). Plan sequence now 7 plans
(5a/5b split for ER). NEXT: owner merges PR #1, then Plan 1 rewrite
against contracts v2 (the 2026-07-09 Plan 1 is obsolete — do not execute).

Prior state (2026-07-09):

- Design spec approved and committed:
  docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md
- Plan 1 written (bootstrap + kg_contracts):
  docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md —
  NOT yet executed. Plans 2–5 to follow (gate, ingestion, curation plane,
  registry).
- Governance adopted (agentic-governance v0.1): delta, ADRs 0001–0005
  back-filled, .github surface, CONTRIBUTING. From now on:
  Issue → Branch → Draft PR → Review → Merge; no direct commits to main.
- NEXT BEFORE IMPLEMENTATION: ChatGPT feedback review cycle on the design
  spec (first governed review); amendments may update the spec/ADRs, then
  Plan 1 executes.

Open questions: extractor config format (decided in Plan 3); IngestJob
protocol shape (deferred to Plan 3 by design).
