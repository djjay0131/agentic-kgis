# Active Context — agentic-kgis

Update 2026-08-21: **Remaining KGIS v1 backlog executed — six independently
reviewed, owner-ready PRs.** An orchestrated multi-agent run took the rest of
the KGIS v1 backlog through the full governance loop (implementer → independent
reviewer inspecting the real diff → fix loop → marked ready). Each PR was
reviewed by an agent other than its author, zero blockers survived, none was
self-merged. Wave 3 integration verified all six compose cleanly: combined
**748 passed, ruff clean repo-wide, mypy --strict clean (78 files), all 11
architectural invariants PASS.**

**Six ready PRs (recommended merge order):**

1. **#15 — Plan 2 remediation (Issue #16).** Logical-erasure wording; a unified
   `LIVE_ROW_PREDICATE` across the partial unique index, sink dedup, and
   `ledger_entries()`; plan()/run() now agree under the default
   `DeterministicIdStrategy` (candidate_id global-PK probe; the former
   strict-xfail now passes); safe v1→v2 migration from a real v1 DB; dead
   `frozen_dict()` removed; evidence `put_many` made atomic. (562 tests on
   branch.)
2. **#20 — contracts hygiene.** Issue #8 safe subset (pattern/alias dedup;
   fail-closed `CommitResult`/`VersionChange`/`ConfidencePolicy` validators),
   #10 build-boundary comment, #11 `CompositeCandidateBuilder` adopter doc, and
   **ruff pinned to 0.15.22** (fixes unpinned-ruff drift that made fresh envs
   report ~63 spurious findings). ADR candidate 0007 documents the fail-closed
   contract narrowings. (499 tests.)
3. **#18 — registry/advisor (Plan 7).** Persistent `SqliteRegistryStore` behind
   the frozen `RegistryStore` protocol; graph-descriptor versioning +
   extension-attribute sidecar; a 12-factor advisor (factors 1/2/5/6/11
   automated, 7 human-assessed); four architecture outcomes plus
   `INSUFFICIENT_INFORMATION` honest-null; human-gated decision/outcome corpus;
   deterministic recommendations; **no auto graph creation.** ADR candidates
   0004 (amend), 0005 (open-backend id), 0006 (recommendation outcomes +
   honest-null). (518 tests.)
4. **#19 — kg_eval (Plan 6, KGIS part).** Named arms, extraction gold sets,
   P/R/F1, evidence-span/reference validity, ontology/hallucination/abstention
   metrics, seeded bootstrap CIs, ablation with honest-null verdicts,
   JSON+Markdown reports, a `MetricProvider` extension seam (no kgcs import).
   (535 tests.)
5. **#21 — Plan 4 structured sync.** Injected `RowProvider`/DB-API source port
   (no vendor drivers in core); materialized snapshot for plan/run honesty;
   stable key-based source coordinates; deterministic snapshot version;
   cross-run idempotency via the persistent ledger; resolvable per-row evidence;
   reuses the existing pipeline. ADR candidate 0008 (snapshot-version
   provenance). Stacked on #15. (599 tests.)
6. **#22 — Plan 4 LLM extraction.** Document/chunk source; per-entity-type
   extractor config; injected `CompletionClient` (no vendor SDK in core; replay
   client for deterministic tests); bounded-concurrency extraction with a
   single-threaded SQLite reduce; failure isolation; honest nondeterministic
   dry-run; resolvable passage evidence; producer/model/version capture;
   ADR-0004 confidence-axis separation. ADR candidate 0009 (model/extractor
   version fields). Stacked on #15. (623 tests.)

Two integration follow-ups are being folded into the branches: rename #21
`tests/kgis/structured/test_providers.py` → `test_row_providers.py` (basename
collision with #19); split the top-level `kgis.__init__` re-exports so each
Plan-4 PR exports its own mode.

**ADR candidates now open (all awaiting owner promotion):** 0001, 0002, 0003-A,
0004, 0005, 0006, 0007, 0008, 0009. Candidates 0004(amend) and 0005–0009 live
on the six PR branches above and land on `main` when those PRs merge; 0001,
0002, 0003-A, 0004 are already on `main`.

**Pending owner decisions:**
- (a) Issue #16 residual — an optional richer "revoked resubmit = free the id /
  changed content + reason" feature. Not required for correctness: the current
  default-strategy semantics are correct and plan()/run() agree.
- (b) Before promoting ADR candidate 0007, confirm no external/KGCS
  `GraphMutationStore` adapter emits a reasonless `committed=False` (the
  fail-closed validators would then reject it).

**Issue dispositions:** #10, #11 → addressed by #20 (close on merge); #8 → safe
subset by #20 + `GraphDescriptor` by #18 (close on merge of both); #2 → item 3
(open-backend) addressed by #18/ADR-0005, items 1/2/4/5/6 remain
kg_contracts/KGCS/baseball-ai; #16 → core done (#15), residual open; #14 →
partially done (#15), append-only/shallow-freeze remain; #23 (new) → kg_eval
stability/source-coverage metrics deferred; #13 → closed (bot spam); #12 →
superseded by this steward reconciliation (closed).

**What's next:** owner merges the six PRs in the order above, dispositions the
ADR candidates, and closes the issues that merge resolves. Then the work that is
explicitly NOT unfinished KGIS core: KGCS Plan 3 curation core+executor, KGCS
Plan 5 entity resolution, the KGCS review-API part of Plan 6, adopter rollouts
(baseball / traffic / research / construction), a polished review UI, streaming
ingestion, a full service wrapper, and full temporal query on every backend.

---

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

Update 2026-07-14: **Sprint 1 (Core Ingestion Engine) complete** on
`feature/sprint-1-core-ingestion`. First deterministic
structured-ingestion pipeline in `src/kgis/`, on `kg_contracts` v2 only:
reader (iterable/CSV/JSON) → normalize (total) → validate (two-tier) →
build candidates (entity/relation/attribute) → `CandidateSink` →
`IngestionReport`. `IngestPipeline` satisfies `IngestJob`; dry-run,
idempotency (intra-run suppression + cross-run sink dedup + injectable
deterministic IDs), full DI. 481 tests repo-wide, `ruff`/`mypy src`
strict green, 8 small commits. Report:
`docs/sprints/2026-07-14-sprint-1-core-ingestion.md`.

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
`mypy src` (strict) all green; CI wired (`.github/workflows/ci.yml`).
Cross-repo verified from agentic-kgcs against the memory adapters.

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
(5a/5b split for ER).

Prior state (2026-07-09):

- Design spec approved and committed:
  docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md
- Plan 1 written (bootstrap + kg_contracts):
  docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md.
- Governance adopted (agentic-governance v0.1): delta, ADRs 0001–0005
  back-filled, .github surface, CONTRIBUTING. From now on:
  Issue → Branch → Draft PR → Review → Merge; no direct commits to main.

Open questions: extractor config format (decided in Plan 3); IngestJob
protocol shape (deferred to Plan 3 by design).
