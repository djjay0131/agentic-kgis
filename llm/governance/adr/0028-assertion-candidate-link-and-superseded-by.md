# ADR-0028: An assertion names its source candidates; a superseded assertion names its successor

Status: Accepted
Date: 2026-10-08
Accepted: 2026-10-09 by the owner (Jason Cusati) on PR #63 — "Option A sounds good. Move forward with this change." The recommended semantics below (plural set-like `source_candidate_ids`; `superseded_by` as a partial invariant; `mark_superseded(..., replaced_by=None)`) are adopted as written.
Implemented (KGIS half): PR #69
Raised by: Issue #58 — the chain candidate → curation decision → canonical
assertion cannot be joined from contracts alone; surfaced by the KGPS (PA-AKG)
provenance audit, 2026-10-07 (agentic-kgps design spec §7 U3, tracking issue
<https://github.com/djjay0131/agentic-kgps/issues/1>)

## Context

The canonical graph is the only durable surface keyed by `assertion_id`. KGIS,
KGCS and KGPS all need to answer two questions **from that surface, without a
scan**, and neither is answerable today:

1. **Which candidate(s) produced this assertion?** — so a caller can reach the
   candidate's ledger entry and, on the structured path, the evidence registry,
   which is keyed by `candidate_id`.
2. **What replaced this assertion?** — supersession is `status = SUPERSEDED`
   plus `superseded_at`; the successor is not recorded anywhere on the record.

### The chain cannot be joined from contracts alone

- `Assertion` (`src/kg_contracts/assertions.py:92-146`) has no candidate
  reference. Its fields that do reach outward are `evidence_refs` (a tuple of
  `EvidenceRef`), `trace_id`, `provenance`, and `derivation`.
- `AuditRecord` (`src/kg_contracts/curation.py:447-470`) has no candidate link
  either: `audit_id, operation_id, decided_by, score_vector, evidence_ids,
  policy_version, trace_id, recorded_at`. It is **operation-scoped**, not
  assertion-scoped. KGCS ADR candidate 0002
  (`agentic-kgcs/llm/governance/adr/candidates/0002-audit-record-lacks-candidate-lineage.md`)
  records that KGCS reconstructs candidate lineage through a universal
  `trace_id` and `reversal_data["candidate_id"]` on every operation, and that
  the build plan sanctions keeping the audit record operation-scoped.
- **The evidence registry is keyed by `candidate_id`.** In
  `kgis/structured/evidence.py`, `StructuredEvidenceRecorder` links a built
  candidate's evidence with `registry.add_refs(candidate_id, ...)`, and
  `SqliteEvidenceRegistry.refs_for(subject_id)` /
  `resolve(subject_id)` (`src/kgis/evidence/store.py:72-116`) read it back by
  that id. On the **structured** path the candidate's `evidence_refs` is empty
  (KGCS ADR-0021 §Rationale measured this: the field is populated in exactly
  one place in all of `src/kgis`, the extraction runner). So for a structured
  candidate the assertion carries no `evidence_refs`, and without a candidate
  id there is no join to the registry at all.
- **Supersession has no successor pointer.** `plan_supersession`
  (`agentic-kgcs/src/kgcs/recuration/evolution.py:451-534`) emits
  `ATTACH_ASSERTION(new)` then `RETRACT_ASSERTION(old)`, and already writes
  `"superseded_by": new_assertion.assertion_id` into the **untyped RETRACT
  payload** (line 511) — but there is no contract field and no reader. KGCS
  ADR-0021 §Alternatives records the consequence precisely: "`superseded_by`
  appears **0** times in all of `kg_contracts`. It is a key in KGCS's own
  untyped RETRACT payload with **no reader in `src/`**." Asking "what replaced
  this?" therefore requires reading stored operations, i.e. a scan.

### The forces this decision must respect

- **Three-store separation (ADR-0006, ADR-0011).** The candidate ledger, the
  canonical graph, and derived projections may share one physical database but
  **never one access path**. Canonical reads are canonical-only; ledger
  visibility is the separate `LedgerReader` surface. ADR-0011's principle is
  about access paths, not about foreign-key *references*: canonical records
  already carry identifiers into other stores (`evidence_refs`, `trace_id`),
  and contracts already carry candidate ids across the boundary
  (`CurationPlan.candidate_ids`, `ValidationDecision.candidate_id`,
  `ResolutionDecision.candidate_id`).
- **Record vs fact identity (KGCS ADR-0021).** A fact's identity is the slot
  `(subject_identity, predicate)`, derived. A **record's** identity is a
  value minted from the record's own content. The record seed deliberately
  **excludes `candidate_id`** and the processor (`actor`, `model`,
  `prompt_version`, `authority`), while including the origin
  (`provenance.source` / `source_ref`) and the cited evidence. Anything added
  here must not enter that seed, or the ADR-0021 split is undone.
- **What KGPS needs (agentic-kgps design spec §7 U3).** Given an assertion id,
  reach its candidate(s), their ledger entries and evidence refs with **no
  scans**. KGPS holds `AssertionLookup` / `GraphReader` on the canonical
  surface; it does not hold the candidate ledger or the KGCS audit stream.
  Wave 1 (`evidence_chain`, `lineage`, `impacted_by`, `explain`) is built on
  that surface. The KGCS audit join is a **separate** upstream item (U5).
- **Frozen, cross-repo, multi-adapter contract.** `Assertion` is
  `frozen=True, extra="forbid"` and lives in `agentic-kgis`; `kg_contracts`
  ships to memory, Neo4j and Spanner adapters, and to the KGCS companion repo.

## Decision

**Option A. Put both pointers on the canonical record.** Add two optional
fields to `kg_contracts.assertions.Assertion`:

```python
source_candidate_ids: tuple[str, ...] = ()
superseded_by: str | None = None
```

1. **`source_candidate_ids`** names the candidate(s) a record was planned
   from. The KGCS planner sets it on `ATTACH_ASSERTION` at its single
   construction site, `CurationPlanner._assertion`
   (`agentic-kgcs/src/kgcs/planner.py:297-365`), as
   `(candidate.candidate_id,)`. It is **not** placed in the ADR-0021 record
   seed; it is read-only provenance metadata on the record, alongside
   `trace_id` and `evidence_refs`.
2. **`superseded_by`** names the record that replaced this one. It is set on
   the copy that carries `status = SUPERSEDED` and `superseded_at`, by the
   supersede/RETRACT path (KGCS `plan_supersession`, and the KGIS
   `GraphWriter.mark_superseded` primitive). It is likewise **not** in the
   seed. The existing untyped `superseded_by` in KGCS's RETRACT payload gets a
   contract home and a canonical reader.

### Semantics (adopted with Option A, 2026-10-09)

- **Multiplicity.** `source_candidate_ids` is a tuple because a plan is
  batch-scoped (`CurationPlan.candidate_ids`) and a future merge or
  re-curation op can have more than one origin; today the planner always sets
  a 1-tuple. It is a **set-like** lineage list: order is deterministic
  (first-seen), duplicates are forbidden, and an empty tuple is the honest
  null for a record with no candidate origin (an evolved record minted by
  `ConceptEvolutionPlanner.next_record` — its origin is the prior record, not
  a candidate).
- **`superseded_by` is a partial invariant, not a biconditional.**
  - `superseded_by is not None` **requires** `status is SUPERSEDED` **and**
    `superseded_at is not None`. A live or revoked record may not claim a
    successor; an assertion id that is set must be a well-formed assertion id.
  - The converse is **not** required: a `SUPERSEDED` record may carry
    `superseded_by = None`. This is the honest null for retirements that have
    no single successor record — an identity merge, or the ADR-0021 backfill
    whose old→new id mapping is explicitly **non-injective** (two legacy rows
    can collapse to one). A strict biconditional would make those
    unrepresentable. This chooses which states are constructible; adopted as written.
- **Retrofit / compatibility.** Both fields default (`()` / `None`), so every
  existing construction site and every serialized record from before the
  change validates unchanged under `extra="forbid"`. Persistence is where the
  change is real: every adapter must store and return the two fields, pinned
  by the shared `GraphMutationStoreContract`.

### The `GraphWriter` sub-decision

`GraphWriter.mark_superseded(assertion_id, at)` (`stores.py:245`) currently
sets only `status` and `superseded_at`. To carry the pointer through that
primitive, **decided**: extend it to
`mark_superseded(assertion_id, at, replaced_by: str | None = None)` — the
narrowest change, keeps retire-with-pointer atomic, and gives the pointer an
indexable write. The alternative — have executors `put_assertion` a full
superseded copy instead — pushes pointer bookkeeping onto every executor and
leaves the existing `mark_superseded` silently dropping `superseded_by`, which
is exactly the silent-loss shape this ADR exists to remove.

### Companion changes (separate PRs, one per repo)

- **KGCS:** planner sets `source_candidate_ids` on `ATTACH_ASSERTION`;
  supersede/RETRACT sets `superseded_by` on the retired copy and stops relying
  on the untyped payload key; a compensating retract clears it (the inverse
  ATTACH already carries the pre-retraction assertion, whose `superseded_by`
  is `None` — `retract_inverse_payload`, `planner.py:541-585`).
- **KGIS:** the contract fields; the memory store; contract tests for
  persistence and for the `include_superseded` read path.

Out of scope here, and tracked separately: KGIS should populate
`Candidate.evidence_refs` from its evidence registry (KGCS ADR-0021 §"What this
deliberately does NOT fix" filed this as an upstream KGIS gap). The candidate
pointer this ADR adds gives KGPS the join to the registry keyed by
`candidate_id`; populating the candidate's own `evidence_refs` is the
orthogonal, durable fix and is **not** absorbed here.

## Rationale

**Why Option A and not Option B (audit as the join table).**

1. **Option B fails the no-scan criterion as stated.** `AuditRecord` keys on
   `operation_id`, carries **no `assertion_id`**, and is a separate store with
   its own retention. To go assertion → candidate via audit you must first go
   assertion → operation; nothing in the contract provides that edge. Option B
   therefore needs a *second* new link (assertion → operation) before it works
   at all — which is Option A under a different name, placed in a third store.
2. **Option A is separation-consistent; Option B is the more coupling
   option.** ADR-0011 forbids one *access path* serving two stores. A
   candidate-id string on a canonical record is opaque lineage, not a ledger
   read; the canonical reader still returns no ledger row. Option B makes
   provenance over canonical data depend on the availability and indexing of
   the **audit stream** — a third store the canonical graph does not own. That
   is a tighter coupling to an append-only operational log than a foreign-key
   reference on the record it describes.
3. **KGPS already holds the canonical surface, not the audit stream.** The
   spec's §7 U3 asks for the link on the assertion because `explain` starts
   there. Making U3 depend on U5 (the durable KGCS `AuditSink`) would couple
   two independent upstream prerequisites.
4. **Record provenance belongs on the record.** ADR-0021 established that a
   record's identity is a value computed from its own content so that *anyone
   holding the row* can reason about it with no store cooperation. Carrying
   the row's origin on the row is the same discipline; scattering it into an
   operation log re-introduces "correctness lives in N adapters' indexing
   choices."

**Why the seed exclusion is load-bearing.** The naive reading of "put the
candidate id on the assertion" is to fold it into `record_seed`, which is what
the pre-ADR-0021 code did (`assertion_id = candidate_id + ":assertion"`) and
what silently destroyed re-assertions. `source_candidate_ids` and
`superseded_by` are therefore **read-only metadata, deliberately outside the
seed**. Two consequences the tests must pin: a new evidence set on the same
candidate still mints a new record (ADR-0021), and adding/changing the pointer
never changes a record id.

**Why `superseded_by` is on the record and not only in the payload.**
`plan_supersession` already knows the successor and already writes it into the
RETRACT payload. The only thing missing to answer "what replaced this?" from
the record is a reader — and a reader that does not scan requires the value to
be *on* the `Assertion`. The payload stays (it drives the operation and its
compensation); the field makes the committed record self-describing, which is
what the issue's acceptance criterion asks for.

**Why a plural candidate field.** A singular `source_candidate_id` would match
today's planner exactly, but the ledger and plan are already plural
(`CurationPlan.candidate_ids`, batch application), and corroboration/merge
paths can legitimately name more than one origin. A tuple costs nothing
(empty default) and avoids a second contract change when the plural case
arrives. It is not a licence to attach several candidates to one record in the
ordinary path: the planner still sets one, and record identity already keeps
corroboration as separate records (ADR-0021).

## Alternatives Considered

### Option B — `AuditRecord.candidate_ids` as the join table

Add `candidate_ids` to `AuditRecord` and recover the candidate from the
assertion through the audit stream.

**Rejected as the answer to this issue** for the reasons in §Rationale
(operation-scoped key, no `assertion_id` on the audit record, third-store
coupling, KGPS does not hold the audit surface). KGCS ADR candidate 0002
independently reached the same conclusion for v1: `AuditRecord` stays
operation-scoped and joins by `trace_id` / `reversal_data`.

This does **not** mean `AuditRecord.candidate_ids` is wrong in general. The
audit stream is the threshold-calibration corpus (spec §7.8); a self-describing
candidate link on it is independently plausible and remains available as a
separate, additive decision if the audit stream should stop depending on the
`trace_id` convention. It is simply not the surface that answers "given an
assertion id, reach its candidates without a scan," so it cannot be the
primary mechanism here.

### Strict biconditional for `superseded_by`

Enforce `superseded_by is not None ⟺ status is SUPERSEDED`. Rejected because
it makes a non-single-record retirement unrepresentable: ADR-0021 documents
merges and the non-injective re-id backfill where a retired record has no
single successor. The whole point of the pointer is to answer "what replaced
this?" when there *is* an answer; honest null must stay representable when
there is not.

### Singular `source_candidate_id`

Rejected: would need a second contract change for the plural case, and it
mis-states the plan's batch scope. Tuple with a 1-tuple today is strictly more
general at no extra cost.

### Derive the candidate link from `trace_id` (status quo)

Rejected. `trace_id` flows candidate → validation → resolution → operation →
audit (KGCS ADR candidate 0002), but it is not on the `Assertion` as a
*join*, and it is not unique to one candidate per assertion in a batch.
Recovering the candidate still requires the ledger/audit store and a lookup by
trace, i.e. the scan the criterion forbids. `trace_id` remains a useful
correlation key; it is not the candidate pointer.

### Store the successor only in the RETRACT payload (status quo)

Rejected: a reader would have to find and replay operations. The issue's
acceptance criterion is explicitly "superseded assertions point at their
replacement" on the record.

## Consequences

### Positive

- Given an `assertion_id`, a caller reaches `source_candidate_ids`, then the
  ledger entry (`LedgerReader.ledger_entry`) and, on the structured path, the
  evidence registry (`resolve(candidate_id)`) — no scan.
- Given a `SUPERSEDED` assertion, `superseded_by` names the replacement
  directly; KGPS `explain` and the ledger-history join both close.
- KGCS's existing untyped `superseded_by` payload key gains a contract home
  and a reader, removing an implicit convention.
- Both fields default, so the change is construction-compatible; the cost is
  confined to persistence and the shared contract suite.

### Negative / Tradeoffs

- A **cross-repo contract version bump** and an adapter-persistence
  obligation (memory, Neo4j, Spanner any other `GraphMutationStore`). The
  shared `GraphMutationStoreContract` is the guard.
- Two more fields on an already-wide `Assertion`; the canonical record now
  carries an explicit pointer into the ledger. This is a reference, not a read
  path — the separation argument is made above and should be re-checked if a
  future field would make the canonical reader *return* ledger rows.
- `source_candidate_ids` is empty on evolved records. That is honest, but a
  caller that assumes "every assertion has a candidate" is wrong and must
  handle the empty tuple; the field default makes this the quiet case, so the
  contract tests should pin it explicitly.
- The structured-path registry join still requires the caller to know the
  registry is keyed by `candidate_id`; the durable fix (populating
  `Candidate.evidence_refs`) remains upstream in KGIS.

### Risks

- **Adapter drift.** An adapter that ignores the new fields still passes
  construction and read tests unless the contract suite asserts the round
  trip. The contract tests must attach an assertion with both fields set, read
  it back (default and `include_superseded=True`), and assert equality —
  otherwise the fields are silently droppable. This is the reachable half of
  the risk and is testable.
- **`mark_superseded` silently dropping the pointer.** If the primitive is not
  extended (or executors do not `put_assertion` a full copy), the pointer is
  lost on the very path that sets it. Pinned by a contract/harness test on the
  supersede path, not just on a hand-attached superseded record.
- **The KGIS reference `MemoryGraphStore` is Plan 1 and does not apply
  `RETRACT_ASSERTION`** (`memory.py:332-335` raises `NotImplementedError`). So
  within `kg_contracts` the round-trip and read-visibility of `superseded_by`
  are testable by attaching a pre-superseded record; the execution path that
  *sets* it is KGCS's. Stated here so the contract coverage is not overclaimed.
- **No validator predicate today for a well-formed assertion id.** The
  identity model has `is_identity_id`; there is no `is_assertion_id`. The
  `superseded_by` format check is therefore a small new validator (a ULID /
  `as_` prefix check), and the ADR flags it rather than assuming it exists.

## Impacted Areas

- [x] Product
- [x] Domain model
- [x] Data architecture
- [ ] AI architecture
- [ ] Domain-specific systems (see governance delta)
- [x] Integrations (KGCS companion; KGPS consumer)
- [ ] UX
- [ ] Security/privacy
- [x] Implementation
- [x] Documentation

## Related Documents

- KGIS/KGCS design spec, §3.2 (three-store separation), §5.4 (bitemporal
  assertions), §5.5 (derivation lineage), §7.8 (audit):
  `llm/specs/2026-07-09-kgis-kgcs-design.md`
- ADR-0006 (three-store separation), ADR-0011 (canonical reads are
  canonical-only), ADR-0010 (write-path mechanism)
- KGCS ADR-0021 (fact identity vs record identity), and its §Alternatives
  table, which records that `superseded_by` has no contract home
- KGCS ADR candidate 0002 (`AuditRecord` has no candidate/validation/resolution
  linkage)
- KGPS design spec §7 U3 and tracking issue
  <https://github.com/djjay0131/agentic-kgps/issues/1>

## Related Issues / PRs

- Issue #58 (this repo) — `Refs`, not `Fixes`: the ADR decides, the
  implementation lands in follow-up PRs (KGIS first, then KGCS).
- `agentic-kgcs` companion change (planner + evolution) — separate PR.
- `agentic-kgps` tracking issue #1 — the consuming requirement.

## Supersedes

None.

## Superseded By

None.
