# Active Context — agentic-kgis

Update 2026-07-18: **PR #9 MERGED — Sprint 1 fully closed.** Merged to `main`
(merge commit `b2ff131`) after the round-2 review; all three blocking
correctness findings landed. Sprint 1 delivered the first deterministic
structured-ingestion pipeline in `src/kgis/` on `kg_contracts` v2, 488 tests
repo-wide, `ruff`/`mypy src` strict green. `kg_contracts` remains **frozen and
unchanged** by the whole sprint. Four ADR candidates now sit in
`docs/adr/candidates/` awaiting owner promotion, with reviewer dispositions
recorded: **0001** record-scoped validation — keep local, promote to contract
only via a separate PR after KGCS confirms the shared shape; **0002**
`Source.fetch()` facade — defer until a real consumer needs it; **0003-A**
public deterministic-ID helper on `kg_contracts` — likely small additive
promotion; **0004** `GraphDescriptor` attribute vocabulary — needs
registry/advisor review. NEXT: **awaiting the next task from the owner.** The
planned next body of work is Plan 2 (candidate ledger + evidence registry),
which makes idempotency durable and lets the null-value rule record absence via
`Evidence` ABSENT. Local gotcha: the working tree carries pervasive CRLF↔LF
line-ending noise on ~71 files (no `.gitattributes`, no `core.autocrlf`);
commits must stay content-only — normalize touched files to LF before staging.

Round-2 review fixes, for the record (in `main` via PR #9): (1) data-dependent
build failures isolated per record — `RequiredValuesValidator(builder.required_fields)`
auto-wired + a `RecordDataError | pydantic.ValidationError` build boundary; no
partial candidates from a failed row; genuine builder bugs still propagate.
(2) `semantic_key` reserved only after candidate validation succeeds. (3)
`IngestionReport.succeeded` counts sink-side `INVALID`. New `RecordDataError`
in `kgis.errors`.

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
