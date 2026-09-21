# Active Context — agentic-kgis

Update 2026-09-21: **two platform defects that made the deterministic
curation core unusable as shipped** (issues #43/#44, ADR-0024/ADR-0025,
version 0.2.1 → 0.3.0). Both were surfaced by the `agentic-kg` adopter
wiring its curation pipeline, and both were re-verified here before any code
moved.

**#43 — the adjudication deadlock.** `ConfidencePolicy.route()` took only a
`CandidateScores` and refused `AUTO` without `identity_confidence >= 0.95`.
Nothing in `kg_contracts`, `kgis` or `kg_eval` produces that score:
`SourceScoring.to_scores()` is the only `CandidateScores` construction site
in production code and never sets it, the LLM extractor updates only
`extraction_confidence`, and the sole remaining writer is
`kg_contracts.testing.factories` — a test double. Measured here: a real
`IngestPipeline` run over 90 rows emits 270 candidates and routes **0** of
them `AUTO`; the most generous scoring the platform can express changes
nothing; flipping `require_identity_confidence_for_auto` alone flips all 270.
So *every* adopter's deterministic core planned nothing, on any corpus.

The fix treats it as a **contract bug, not a missing producer**. Resolution
confidence is confidence in a resolution; a candidate minting a brand-new
identity has no resolution to be confident about, and KGIS structurally
cannot produce the number anyway (no graph read surface, ADR-0010) — anything
it emitted would be a fabricated score. `route()` now takes an
`IdentityDisposition` (`RESOLVED_EXISTING` default, `NEW_IDENTITY`,
`UNRESOLVED`); only an absent score on a `NEW_IDENTITY` is excused, a stated
low score still blocks, extraction/source/risk gates are untouched, and
`UNRESOLVED` is now blocked outright — strictly stronger than before.
`ResolutionDecision.identity_disposition()` does the mapping so no caller
derives it by hand.

**#44 — `CREATE_IDENTITY` had no inverse,** so a committed run of creations
compensated to nothing. Added `REVOKE_IDENTITY` (a tombstone: status
`REVOKED`, record retained, **original `curation_epoch` preserved** — moving
it would make the identity vanish from epoch-scoped reads of the epoch that
created it) plus `INVERSE_OPERATION_TYPES`, which names the pairing for KGCS
and leaves `PROMOTE_ONTOLOGY_TERM` deliberately absent (issue #45). The
second half matters as much: `_is_visible` left `REVOKED` records visible by
default, so a revoke would have changed nothing observable — a rollback that
rolls nothing back. `GraphReadOptions.include_revoked` now exists and
`REVOKED` is hidden by default, superseding ADR-0006 in part. The old
`test_revoked_record_visible_by_default` pinned the previous behaviour and
named an ADR as the way to change it; ADR-0025 is that ADR.

**A cross-repo near-miss worth keeping.** This change briefly carried a
fail-closed narrowing on `ResolutionDecision` rejecting
`create_new_identity=True` alongside a non-null `resolved_identity`. The
`agentic-kgcs` agent caught it against the in-flight branch: it would have
raised for **every** AUTO-routed entity candidate, because
`kgcs.policy.ResolutionPolicy.resolve` sets both fields — trading a platform
that plans nothing for a platform that raises. On inspection the validator
was unsound independently of that: `kg_contracts` has no graph access, so it
cannot tell a freshly minted identity id from a pre-existing one (both are
`kg://<graph-id>/identity/<ulid>`), meaning the check fired on the legitimate
case and could not detect the illegitimate one — *a check that cannot fail
for the reason it names*, which is the exact defect class this work was
guarding against. It was also incidental: `identity_disposition()` tests
`create_new_identity` first, so the mapping was already total. Dropped, with
the real question (what does `resolved_identity` mean when
`create_new_identity` is True? spec §7.4 never says) filed as issue #47 for
an owner ADR rather than settled by fiat inside a bug fix. Two tests now pin
the KGCS shape so the validator cannot come back silently. General lesson:
a narrowing that a consumer's normal output violates is a hypothesis about
the contract, not a tightening of it — check the consumers first.

**Verification note worth keeping.** 27 mutants, each run against its named
tests alone with an unmutated control in every batch. One survived: the
`curation_epoch`-preservation test also passed against a store that ignored
`REVOKE_IDENTITY` entirely, because `include_revoked=True` returns `ACTIVE`
records too — the assertion could not distinguish "revoked, epoch kept" from
"never revoked". Strengthened to assert the default read no longer returns
the entity and the stored status is `REVOKED`; the mutant then died. Also a
process lesson: `git checkout -- <file>` restores from HEAD, so mutation
testing against *uncommitted* work silently deletes it. Commit first.

Update 2026-09-18: **`import kgis` was broken for every consumer without the
`[dev]` extra** (issue #37, PR #39, version bumped 0.2.0 → 0.2.1).
`kgis/evidence/__init__.py` eagerly imported `kgis/evidence/contract.py`, a
reusable pytest suite, so the chain `kgis/__init__` → `extraction` → `runner` →
`kgis.evidence` reached `import pytest` and raised `ModuleNotFoundError` under
the runtime dependency set (`pydantic` alone). The fix is a PEP 562
`__getattr__`/`__dir__` pair on `kgis.evidence` that resolves the name **in
place**: the module stays where Plan 2 put it, both
`from kgis.evidence import EvidenceRegistryContract` and
`from kgis.evidence.contract import ...` keep working, and nothing is relocated.
Adding pytest to runtime dependencies was rejected outright.

**Process note worth keeping.** The first attempt at this PR *moved* the suite to
`src/kgis/testing/evidence.py` and justified it by citing spec §10.2 as
establishing a "reusable suites live in `testing` subpackages" convention.
Independent review found that convention **does not exist**: §10.2 says reusable
suites must exist, nothing about where they live, and
`llm/plans/2026-07-17-...` lines 43/1723/1744 prescribe the *old* location three
times. The move would have reversed a documented decision on a false citation
and shipped a breaking removal of `kgis.evidence.contract` under a frozen
version. It was reverted; laziness alone fixes the defect, and the layout
question is now issue #40 for an owner ADR decision rather than something a bug
fix settles by fiat.

The reason this survived 122 commits is a CI blind spot: the `test` job installs
`.[dev]`, so pytest is importable in it by construction and no in-process import
check could see the fault. Two guards close it. `tests/test_packaging.py` now
runs an exhaustive `pkgutil` sweep of **every** module in all three packages
inside a subprocess whose import hook is an **allowlist** — the stdlib plus the
distribution closure of the non-extra requirements, computed from installed
metadata so it tracks `pyproject.toml`. A denylist of `pytest`/`_pytest` was not
enough: a transitive dev dep such as `pluggy` walked straight through it. Two
modules are exempt by name (`kg_contracts.testing.contract`,
`kgis.evidence.contract`); `kgis/structured/testing.py` and
`kgis/ledger/contract.py` are reusable suites eagerly re-exported from runtime
packages and are deliberately **not** exempt, so the day either grows a
`pytest.raises` the sweep goes red.

Review pass 2 then broke that guard twice, and both lessons are worth keeping.
The exemption set had a rot-guard asserting `"pytest" in sys.modules` **in the
pytest process**, where it is unconditionally true — a test that could not fail,
which let a leaf module be exempted and silently dropped from every check.
Anything that must be able to fail now runs inside the sweep subprocess, and an
exemption must fail *specifically* because of `pytest` (the `[dev]` extra is
pytest + ruff + mypy; the latter two are CLIs nothing imports, so any other
missing dependency is an undeclared one). Enumeration also moved from
`pkgutil.iter_modules` to a filesystem walk, because `iter_modules` does not
descend into a PEP 420 namespace directory that the wheel ships happily. Ten
attacks now verified red-alone/green-after-revert. The
`runtime-import` CI job (`pip install .`, no extras, 3.11 + 3.12 matrix) is
defence in depth only — it is not a required status check, whereas `test` is, so
the sweep carries the enforcement.

754 passed (750 before), ruff and `mypy --strict` (78 files) green, governance
4/4. The sweep finds 78 modules, sweeps 76, and derives both exemptions as
`pytest`.

One scope limit, recorded because it is structural rather than an oversight: the
invariant is **import-time only**. A module-level `__getattr__` reaching a
dev-only dependency is invisible to it — and that is precisely the mechanism the
fix uses, so no guard can separate a good deferral from a bad one. Lazy-export
tables (`kgis/evidence/__init__.py`'s `_LAZY`, the only one) therefore carry the
same review burden as the exemption set.

Also surfaced, not fixed: **zero tags, zero releases, not on PyPI**, with
`version` frozen at `0.2.0` since commit `7e120f9` across 122 commits — 35 of
them (36 with merges) touching `src/kg_contracts`, including #33's observable
`FrozenMapping` serialization change. `agentic-kgcs` declares
`agentic-kgis>=0.2.0`, which therefore distinguishes nothing. Filed as issue #38
for an owner decision recorded as an ADR; the 0.2.1 bump here is a stopgap that
makes the importable tree nameable, not a resolution. Issue #41 tracks the
missing `py.typed` markers on `kgis` and `kg_eval`, which make both packages
untyped for every downstream consumer.

Update 2026-09-10: **Migrated to the agentic-governance v0.5 two-plane
layout** (PR #27, issue #26). The control plane moved out of `docs/` into
`llm/`, by `git mv` so history follows: the governance delta to
`llm/governance/governance-delta.md`, the 24 ADRs + index + `candidates/` to
`llm/governance/adr/`, the Sprint 1 report to `llm/sprints/`, the design spec
to `llm/specs/2026-07-09-kgis-kgcs-design.md`, and the three plans to
`llm/plans/`. `docs/superpowers/` was then deleted — it is the vendor default
agentic-governance ADR-0001 exists to eliminate. `docs/` now holds only
data-plane material (`docs/kgis-adopter-notes.md`, `docs/ai/`). The delta pin
is `v0.5`, it declares a `## Repository Layout` block binding seven slots, and
its L0 allowlist is rebound to the new paths. The two-plane routing rule is
installed in `CLAUDE.md` and `AGENTS.md`, which is what stops `superpowers`
recreating `docs/superpowers/`.

**Reading older entries in this file:** paths written before this date are left
exactly as they were, because they record where things were at the time. Map
them forward with the table above — `docs/superpowers/specs/` → `llm/specs/`,
`docs/superpowers/plans/` → `llm/plans/`, `docs/adr/` →
`llm/governance/adr/`, `docs/sprints/` → `llm/sprints/`,
`docs/governance-delta.md` → `llm/governance/governance-delta.md`. The same
applies to `projectbrief.md`'s `Authority:`/`Governance:` lines and to the
three relocated plans, whose bodies contain `git add docs/adr/...` transcripts
of commits already made.

Verification at migration:
`node ~/code/agentic-governance/plugin/scripts/governance-checks.mjs --layout`
→ 4 of 4 passed (`layout` a real PASS, not a SKIP); 748 tests, ruff and
`mypy --strict` green. CI now runs that same command in a `governance` job with
agentic-governance pinned by SHA.

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
