# KGIS Remaining Backlog — Orchestrated Execution Plan

**Date:** 2026-08-21  
**Repository:** `djjay0131/agentic-kgis`  
**Execution owner:** Claude Code acting as author/orchestrator  
**Human owner:** repository owner  
**Governance:** Issue → Branch → Draft PR → Review → Merge; authors open PRs, reviewers approve/request changes, owner merges semantic PRs.

## 1. Mission

Finish the remaining **KGIS-repository backlog** as far as implementation can responsibly go in one concentrated execution session, while preserving the approved KGIS/KGCS v2 architecture and governance boundaries.

This is an **implementation and backlog-closure program**, not an architecture rewrite.

The orchestrator must maximize safe parallelism, keep changes reviewable, and avoid turning one afternoon into one giant PR. The desired result is a set of clean, independently reviewable PRs with green gates, explicit dependency ordering, and the repository memory bank/backlog reconciled to reality.

### Definition of “done this afternoon”

For work the agent is allowed to perform autonomously, “done” means:

- implementation complete;
- tests written first or concurrently under the established TDD discipline;
- `pytest`, `ruff check src tests`, and `mypy src` green;
- documentation and memory bank current;
- author branch pushed;
- draft PR opened and kept current;
- independent subagent review/fix loop complete;
- PR marked ready only when its own review findings are resolved.

**Owner-only merge decisions are not a reason to stop the orchestrator.** Where a downstream workstream depends on an unmerged upstream PR, use a clearly documented stacked branch/PR only when necessary; otherwise prefer independent branches from `main`. Never self-merge.

---

## 2. Live repository baseline (2026-08-21)

The orchestrator must re-verify this baseline before changing anything.

### On `main`

- Plan 1 / `kg_contracts` v2 is merged.
- Sprint 1 / Core Ingestion Engine is merged via PR #9.
- `main` currently ends at merge commit `b2ff131` (2026-07-18) unless it changed after this plan was written.

### Open implementation PR

**PR #15 — Plan 2: candidate ledger + evidence registry**

Branch: `plan/plan-2-ledger-evidence`

Implemented there:

- frozen mapping support for persisted contract payloads;
- persistent SQLite candidate ledger;
- `CandidateSink` + `LedgerReader` implementation;
- persisted processing-state lifecycle;
- revoke / logical-erasure row governance;
- evidence registry with `PRESENT` / `ABSENT` / `ERROR`;
- append-only ledger audit stream;
- persistent-ledger integration with the Sprint 1 ingestion pipeline;
- ADRs 0012–0014.

Latest recorded gates: 553 tests, ruff clean, strict mypy clean.

### Open Plan 2 review issue

**Issue #16 — Plan 2 review round 2** contains pre-merge guarantee gaps that must be reconciled before PR #15 is considered done:

1. Correct erasure wording to **logical erasure**, not forensic/at-rest destruction or GDPR-complete erasure.
2. Fix dry-run/execution divergence for revoked/erased semantic keys by making live-key uniqueness and duplicate checks agree.
3. Preserve the owner decision that revoked keys are resubmittable; split any net-new “changed content + resubmission reason” semantics into a separate follow-up unless already explicitly decided.

### Other open backlog

- **Issue #14** — Plan 2 non-blocking minors + Plan 3 audit-schema seam.
- **Issue #8** — `kg_contracts` v2 cleanup/minors.
- **Issue #10** — document programmer-error vs data-error tradeoff at build boundary.
- **Issue #11** — adopter docs for all-or-nothing `CompositeCandidateBuilder` row semantics.
- **Issue #2** — baseball-ai compatibility findings; some items are already addressed, others belong in registry/advisor or adoption alignment.
- **PR #12** — stale post-Sprint-1 docs/memory draft; likely superseded by newer Plan 2 memory updates.
- **PR #13** — unrelated bot PR with placeholder implementation; should not be merged and should be closed/rejected if still open.

### Approved roadmap still relevant to this repository

The v2 design sequence is:

1. Bootstrap + `kg_contracts` v2 — **done**
2. Candidate ledger + evidence registry — **implemented in PR #15, not yet closed**
3. Curation core + executor — **KGCS repo, external dependency**
4. Ingestion modes — **KGIS repo, remaining**
5. Entity resolution — **KGCS-centered, external dependency**
6. `kg_eval` + review API — **`kg_eval` belongs here; review API belongs to KGCS**
7. Registry + advisor — **KGIS/platform work remaining here**

Do not accidentally implement KGCS curation, ER, or review-queue behavior inside `kgis` just to make the roadmap look complete.

---

## 3. Orchestration model

Create one **Orchestrator Agent** that owns sequencing, dependency tracking, branch/PR hygiene, and final reconciliation. It delegates to specialist agents using isolated worktrees.

### Required agents

1. **Orchestrator / Repository Steward**
   - verifies live repo state;
   - owns execution graph and task board;
   - assigns worktrees/branches;
   - prevents overlapping file ownership;
   - keeps PR bodies and memory bank current;
   - stops architecture drift;
   - performs final backlog reconciliation.

2. **Plan 2 Remediation Agent**
   - works only on PR #15 branch;
   - resolves Issue #16 and any true blockers;
   - triages Issue #14 items that are cheap and safe to include before merge;
   - does not broaden Plan 2 into later-roadmap features.

3. **Contracts Hygiene Agent**
   - resolves safe, non-semantic or narrowly semantic items from Issue #8 plus #10/#11 documentation;
   - proposes ADR candidates rather than silently changing durable semantics;
   - must not collide with Plan 2 edits to `kg_contracts` until those changes are reconciled.

4. **Ingestion Modes Agent**
   - owns Plan 4 KGIS work: deterministic structured sync + LLM document extraction;
   - consumes the existing pipeline/ledger/evidence contracts rather than inventing a parallel pipeline.

5. **KG Eval Agent**
   - owns the `kg_eval` package implementation that can be completed without KGCS ER/review internals;
   - implements reusable evaluation primitives and extraction evaluation now;
   - leaves KGCS-specific ER arms as extension points if KGCS is not yet available.

6. **Registry / Advisor Agent**
   - owns Plan 7 repository work: durable graph registry implementation, extend-vs-new recommendation logic, decision/outcome corpus, and unresolved registry-related contract gaps.

7. **Independent Review Agent**
   - never authors the code it reviews;
   - runs after each task group and again on each whole branch;
   - reviews spec/ADR compliance, invariants, failure modes, and test quality;
   - produces findings categorized as BLOCKER / IMPORTANT / MINOR / NIT.

8. **Integration / Steward Agent**
   - runs the final cross-branch/backlog audit;
   - verifies no stale plan/status claims remain;
   - reconciles issues/PRs/memory bank;
   - identifies only genuinely deferred work.

---

## 4. Execution waves

## Wave 0 — Preflight and cleanup triage

**Owner:** Orchestrator  
**Parallelism:** none; finish before implementation fan-out.

1. Fetch `main`, PR #15, open issues, open PRs, branches, design spec, ADR index, and memory bank.
2. Verify whether any work landed after this plan was written.
3. Build a live dependency board with columns: `Ready`, `Blocked`, `In Progress`, `Review`, `Owner Merge`, `Deferred`.
4. Determine whether PR #12 is fully superseded. If yes, close it with a concise reason; if unique content remains, salvage only the unique parts in a later docs PR.
5. Close/reject PR #13 if it is still the placeholder bot contribution and does not satisfy repository standards.
6. Record all owner-only decisions that truly block code. Do **not** ask the owner questions that can be answered from accepted ADRs/spec/issues.

**Exit gate:** clean, current execution graph; no stale PR accidentally treated as backlog.

---

## Wave 1 — Finish Plan 2 / PR #15

**Owner:** Plan 2 Remediation Agent  
**Reviewer:** Independent Review Agent

### 1A. Resolve Issue #16 blockers

Implement and test the already-recorded decisions:

- Replace all claims of “irrecoverable”, “unrecoverable”, “at-rest destruction”, or implied GDPR-complete deletion with the precise guarantee: **logical erasure of the live payload plus retained hash tombstone; not forensic storage scrubbing**.
- Make dry-run and execution agree for revoked/erased semantic keys.
- Use a partial live-row uniqueness constraint or equivalent schema/index mechanism so revoked/erased tombstones can coexist with a new live row of the same semantic identity.
- Ensure duplicate lookup uses the same “live row” predicate as the unique constraint and dry-run ledger view.
- Add migration/bootstrap behavior that handles an existing Plan 2 database safely; do not only make fresh databases pass.
- Add regression tests covering submit → revoke → plan → resubmit and submit → erase → plan → resubmit under the documented semantics.

Do **not** silently add the unresolved “must change content + must supply reason” feature unless an accepted owner decision exists. If it remains open, create/retain a focused issue with explicit acceptance criteria.

### 1B. Triage Issue #14

Fix in this PR only when the item is small, directly adjacent, and does not enlarge semantics:

- remove or intentionally document dead `frozen_dict()` helper;
- make `put_many` atomic if the change is localized and testable;
- consider idempotent revoke/erase metadata preservation if it does not conflict with Issue #16 semantics.

Defer intentionally front-loaded query columns and Plan-3 curation-audit schema decisions.

### 1C. Re-review PR #15

Run:

- full tests;
- ruff;
- strict mypy;
- reusable contract suites;
- SQLite reopen/restart tests;
- concurrent/idempotency tests;
- audit append-only tests;
- logical-erasure wording audit across ADR/PR/docs/code comments.

Update PR #15 body so its guarantee claims exactly match implementation.

**Exit gate:** PR #15 is ready for owner review/merge with zero unresolved blockers.

---

## Wave 2 — Parallel backlog closure after Plan 2 stabilizes

Wave 2 work may begin once the **Plan 2 contract/storage semantics are stable**, even if the owner has not yet clicked Merge. Use separate worktrees and avoid overlapping files.

### Stream A — Contracts/documentation hygiene

**Owner:** Contracts Hygiene Agent

Resolve the safe remainder of Issues #8, #10, #11.

Expected tasks:

- deduplicate entity-type pattern constant;
- deduplicate alias-check logic if behavior remains identical;
- strengthen `CommitResult` invalid-state validation;
- close the empty-string `VersionChange.from_version` loophole;
- bound confidence thresholds to `[0, 1]` while preserving ordering rules;
- explicitly test/document REVOKED canonical read visibility;
- add the Issue #10 build-boundary tradeoff comment/doc;
- add adopter-facing documentation for `CompositeCandidateBuilder` all-or-nothing row rejection.

Leave `GraphDescriptor` naming/attribute/backend questions to Stream D because they affect registry semantics.

**PR shape:** one focused hygiene PR; split semantic contract changes from docs-only changes if reviewability demands it.

### Stream B — Plan 4: ingestion modes

**Owner:** Ingestion Modes Agent

Build on the existing Sprint 1 pipeline plus Plan 2 ledger/evidence surfaces. Do not create a second ingestion architecture.

#### B1. Structured synchronization mode

Implement a reusable deterministic structured-sync layer suitable for databases without binding KGIS to one vendor driver.

Minimum surface:

- DB-API/row-provider style injected source port;
- query/page/batch adapter with stable source coordinates;
- explicit mapping/config from source fields to existing builders;
- repeatable reads or snapshot semantics sufficient for `plan()` vs `run()` honesty;
- deterministic source version / cursor metadata;
- reference implementation using stdlib SQLite fixtures;
- persistent-ledger idempotency integration;
- evidence production/reference for source records where appropriate;
- no direct graph writes.

Do not add PostgreSQL/Spanner/Neo4j runtime drivers to the core library merely to demonstrate structured sync.

#### B2. LLM document extraction mode

Implement the approved config-driven extractor model:

- document/chunk source abstraction with stable source coordinates;
- per-entity-type extractor config: target candidate type/schema, prompt/template, model identifier, model/extractor version, policy metadata;
- injected `CompletionClient`; no vendor SDK in core contracts;
- parallel execution by extractor/entity type with bounded concurrency;
- structured-output parsing and validation;
- failure isolation: one extractor/type/document failure is represented and reported without corrupting successful siblings;
- first-class evidence creation and resolvable `EvidenceRef`s to source passages/chunks;
- candidate producer/model/extractor version capture;
- artifact candidate support for source documents when useful;
- dry-run semantics that are honest about nondeterminism: `plan()` must mean “extract and show what would be submitted without submission”, not falsely promise identical future model output unless responses are pinned/replayed;
- deterministic replay mode using recorded model responses/fixtures for tests;
- extractor contract suite reusable by future adapters.

#### B3. Resolve deferred ingestion seams only when a real consumer now requires them

Revisit ADR candidates:

- record-scoped validation — keep local unless multiple modes prove the shared shape should move to `kg_contracts`;
- `Source.fetch()` facade — implement/promote only if Plan 4 creates a real consumer for the contract surface;
- public deterministic-ID helper — promote if duplication now exists across modes and tests demonstrate the common contract;

Never change the contract merely to remove aesthetic friction.

**Exit gate:** both v1 ingestion modes produce valid candidates through `CandidateSink`, persist through the ledger/evidence path, and have reusable invariant tests.

### Stream C — `kg_eval` v1

**Owner:** KG Eval Agent

Implement the portion of Plan 6 owned by this repository.

Minimum deliverables:

- named evaluation arms;
- deterministic arm configuration + metadata;
- extraction gold-set representation;
- entity/relation/attribute extraction precision/recall metrics;
- evidence-span / evidence-reference validity checks;
- ontology-violation and unsupported-assertion/hallucination metrics where measurable;
- abstention/failure-rate metrics;
- cost/latency hooks that can be `None` when not measured;
- ablation comparisons;
- bootstrap confidence intervals where statistically meaningful;
- honest-null conclusions when evidence is insufficient or an enhanced arm does not beat baseline;
- JSON + Markdown reports;
- extension interfaces for later KGCS ER/review metrics without importing `kgcs`.

Use VTTSI evaluation patterns as reference behavior, not code vendoring.

**Exit gate:** KGIS structured and LLM extraction modes can be compared through `kg_eval` without special-case test harness code.

### Stream D — Registry + extend-vs-new advisor

**Owner:** Registry / Advisor Agent

Implement the repository-owned part of Plan 7.

Minimum deliverables:

- persistent `RegistryStore` implementation (SQLite reference is acceptable behind the existing contract);
- graph descriptor CRUD/versioning and ownership/lineage fields already in contract;
- resolve `GraphDescriptor` attribute-vocabulary gap from Sprint 1;
- resolve open-backend-identifier concern from baseball-ai Issue #2 without forcing every backend into a closed enum if the accepted design supports extension;
- recommendation engine over the approved factors;
- structured 12-factor checklist with the v1 automated subset clearly distinguished from human-assessed factors;
- return more than binary extend/new where the approved v2 design calls for logical/physical separation or shared identity options;
- human-gated recommendation decision record;
- decision + outcome corpus persisted for later threshold calibration;
- no automatic graph creation/extension in v1;
- tests proving recommendations are deterministic for a fixed registry snapshot/config;
- explicit “insufficient information” result rather than fabricated scores.

Audit Issue #2 after this stream and close only the items truly satisfied; leave downstream baseball adoption work in baseball-ai.

**Exit gate:** a consumer can register graphs, request an explainable recommendation, record the human decision/outcome, and retrieve the history for future calibration.

---

## Wave 3 — Cross-stream integration

**Owner:** Integration / Steward Agent  
**Starts after:** Streams A–D have implementation-complete branches.

1. Run the full repo quality gates against each branch and, where practical, an integration branch containing all non-conflicting accepted work.
2. Validate these end-to-end flows with memory/SQLite reference adapters:

### Deterministic path

`structured source → KGIS normalize/validate/build → evidence registry → CandidateSink → persistent ledger`

### LLM path

`document/chunks → parallel configured extractors → evidence registry → CandidateSink → persistent ledger`

### Evaluation path

`gold fixtures → baseline extractor arm + enhanced arm → kg_eval report`

### Registry path

`new workload descriptor → registry snapshot → advisor recommendation → human decision/outcome record`

3. Verify hard invariants:

- KGIS never writes canonical graph state;
- canonical `GraphReader` never reads ledger candidates;
- evidence refs resolve or fail loudly;
- absent/error evidence is not silently collapsed;
- same deterministic input produces stable semantic identity;
- dry-run and execution agree on submission set for deterministic sources;
- LLM dry-run wording does not overclaim reproducibility;
- no single confidence float is reintroduced;
- source reliability remains distinct from extraction confidence;
- no bare `Label:key` identity is reintroduced;
- all persisted mutable-looking payloads remain deep-frozen through round-trip;
- no domain-specific reasoning has leaked into KGIS.

4. Reconcile ADR candidates and create new ADRs only for durable decisions actually proven necessary by implementation.

---

## Wave 4 — Backlog and repository closure

**Owner:** Orchestrator / Repository Steward

Perform an explicit backlog reconciliation, not a celebratory summary.

### Required actions

- Re-scan all open issues and PRs.
- For each issue, mark one of: `closed by PR`, `superseded`, `moved to KGCS`, `moved to adopter repo`, `intentionally deferred`, `still actionable`.
- Close stale/superseded branches/PRs where authorized.
- Update `llm/memory_bank/activeContext.md`, `progress.md`, and any roadmap/backlog artifact used by the repo.
- Update ADR index/status and candidate README.
- Ensure PR descriptions identify dependencies and merge order.
- Produce a final “remaining after today” list containing **only** owner merges, KGCS-owned work, adopter rollouts, or explicitly deferred v1 scope.

### Expected remaining work that should NOT be mislabeled as unfinished KGIS core

- KGCS Plan 3 curation core + executor;
- KGCS Plan 5 entity resolution;
- KGCS review API portion of Plan 6;
- adopter-specific baseball/traffic/research/construction rollout;
- polished review UI;
- streaming ingestion;
- full service wrapper;
- full temporal query support on every backend;
- experimental multi-agent debate arm.

---

## 5. PR strategy and dependency order

Use separate PRs. Recommended order:

1. **PR #15 remediation** — finish existing Plan 2 branch.
2. **Contracts/docs hygiene PR** — Issues #8/#10/#11 safe subset.
3. **Plan 4 ingestion modes PR** — may be split into `structured sync` and `LLM extraction` if either exceeds a reviewable size.
4. **`kg_eval` PR** — independent where possible.
5. **Registry/advisor PR** — independent where possible.
6. **Final steward/reconciliation PR** — docs/status only, after implementation PRs are ready.

Do not bundle all streams into one PR to save clicks. The owner should be able to review and merge one concern at a time.

When a stream truly depends on unmerged PR #15, either:

- wait for owner merge while other independent streams proceed; or
- create a clearly labeled stacked branch based on PR #15 head and retarget/rebase after #15 merges.

Never copy Plan 2 code into another branch to avoid the dependency.

---

## 6. Review protocol for every implementation stream

For every task group:

1. **Implementer agent** writes failing tests / acceptance test, implements, runs focused gates.
2. **Task reviewer agent** reads spec/ADR + diff without relying on implementer summary.
3. **Fix loop** resolves BLOCKER/IMPORTANT findings; MINORs may become tracked follow-ups only when genuinely non-blocking.
4. **Whole-branch reviewer** performs cross-cutting review for architecture leaks and invariant violations.
5. **Author/orchestrator** updates PR description and marks ready.
6. **Owner/reviewer** retains merge authority; Claude never self-merges.

A reviewer disagreeing with the plan must not “fix” the architecture silently. If the current ADR/spec is wrong, file an ADR candidate with evidence and continue using the least-invasive compliant implementation possible.

---

## 7. Time-boxing guidance for this afternoon

Optimize for **completed, reviewable work**, not maximum lines changed.

### First hour

- Wave 0 complete.
- PR #15 Issue #16 fixes implemented + tests running.
- Streams C and D can begin design-to-tests if their file ownership does not overlap Plan 2.

### Middle block

- PR #15 fully reviewed and ready.
- Stream A cleanup complete.
- Plan 4 structured sync implementation underway.
- `kg_eval` and registry/advisor proceed in parallel.

### Final block

- LLM extraction implementation/fix loop.
- whole-branch reviews;
- cross-stream integration tests;
- PR descriptions/memory bank/backlog reconciliation;
- final list of owner-merge order and any genuinely deferred work.

If time becomes constrained, prioritize in this order:

1. correctness and closure of PR #15;
2. Plan 4 ingestion modes;
3. `kg_eval` usable against ingestion;
4. registry/advisor;
5. hygiene/nits that do not block adopters.

Do not sacrifice review/fix loops to claim all work is “done.”

---

## 8. Final acceptance criteria

The orchestrator may declare the KGIS-repository backlog implementation-complete only when:

- Plan 2 has no known correctness blocker and PR #15 is review-ready;
- both v1 ingestion modes exist and feed the candidate ledger/evidence registry;
- KGIS has no canonical graph write path;
- `kg_eval` can evaluate KGIS extraction arms with honest-null reporting;
- registry/advisor has a persistent reference implementation and human-gated decision/outcome recording;
- open KGIS issues have explicit dispositions;
- stale PRs are closed or explained;
- quality gates are green on every ready PR;
- memory bank reflects the actual repository state;
- remaining work is clearly separated into KGCS-owned, adopter-owned, or intentionally deferred scope.

The goal is not to erase the backlog by relabeling it. The goal is to finish the KGIS-owned v1 work, surface real blockers honestly, and leave a clean execution trail for review and merge.
