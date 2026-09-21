# ADR-0025: `REVOKE_IDENTITY` inverts `CREATE_IDENTITY`; REVOKED is hidden from canonical reads by default

Status: Accepted
Date: 2026-09-21
Raised by: Issue #44 — non-reversible curation run found by the `agentic-kg` adopter

## Context

`kg_contracts.curation`'s module docstring states the platform's rollback
model plainly: "Every `CurationOperation` logs enough to reverse itself
(`reversal_data`: pre-merge member set, lineage, affected projections) —
rollback is always a compensating operation, never deletion of history."

The v1 `CurationOperationType` vocabulary could not honour it. Its seven
members pair up as `ATTACH_ASSERTION` ↔ `RETRACT_ASSERTION`,
`MERGE_IDENTITIES` ↔ `SPLIT_IDENTITY`, `REASSIGN_ASSERTION` ↔ itself
(endpoints swapped), and `PROMOTE_ONTOLOGY_TERM` ↔ nothing — leaving
**`CREATE_IDENTITY` with no inverse at all**. A compensator handed a plan of
`CREATE_IDENTITY` operations has no operation to emit, so it emits none: the
`agentic-kg` adopter measured a committed plan of 8 `CREATE_IDENTITY`
operations compensating to `CompensationResult.plan is None`, all 8
`non_compensable`. First ingest is overwhelmingly creation, so the common
case was the irreversible one.

A second, quieter defect surfaced while characterising the first. Suppose an
inverse existed and set `CanonicalEntity.status` to `REVOKED`.
`MemoryGraphStore._is_visible` hid `SUPERSEDED` by default and deliberately
left `REVOKED` **visible**, pinned by
`test_revoked_record_visible_by_default`, whose own comment said auto-hiding
`REVOKED` "would be a durable read-semantics change (an ADR, not a
test-double tweak)". Under those semantics a revoke changes nothing any
reader can observe — a rollback that rolls nothing back, and a compensation
test that could only ever verify that a plan was *produced*, never that it
*worked*. The two must move together.

## Decision

### 1. `CurationOperationType.REVOKE_IDENTITY`

A new member whose effect is a **tombstone**: set the entity's
`CurationStatus` to `REVOKED`, retain the record, and **retain its original
`curation_epoch`**.

Payload: `{"identity_id": <identity id>}`, plus an optional `"reason"`.
Deliberately not a whole entity dump — the executor revokes the entity
actually in the graph, so a stale copy carried in the plan cannot overwrite
it. The pre-revoke entity belongs in the operation's `reversal_data`, which
is what makes `REVOKE_IDENTITY` itself compensable by a `CREATE_IDENTITY`.

Not a supersession, which would be wrong twice over: nothing *replaces* a
reversed identity, and `GraphReadOptions.include_superseded` would then
resurrect it in exactly the history views that must show it as withdrawn.
Not a deletion, which the append-only model forbids outright.

`curation_epoch` is **not** advanced by a revoke. Advancing it would make the
identity vanish from every epoch-scoped read of the epoch that *created* it
(`_is_visible` excludes `record_epoch > options.curation_epoch`) — a rollback
that erases the record of what it rolled back. The commit still allocates a
new epoch, as every mutation batch does; it is the record's own epoch stamp
that is preserved. Assertion supersession already works this way
(`mark_superseded` changes status and `superseded_at`, never the epoch).

### 2. `INVERSE_OPERATION_TYPES`

A published mapping in `kg_contracts.curation` from each operation type to
the type that compensates it. The compensator itself lives in
`agentic-kgcs`; the *vocabulary* half is published here so the two repos
cannot disagree about which type reverses which, and so "is this operation
compensable at all?" is a lookup against the contract rather than a
judgement re-made in each executor.

`PROMOTE_ONTOLOGY_TERM` is **absent** from the map (issue #45). Absence is
the honest statement that a plan containing it is not fully compensable, and
a named test pins it as an exclusion rather than letting it be papered over
with a plausible-looking entry.

### 3. `GraphReadOptions.include_revoked: bool = False`, and REVOKED hidden by default

The durable read-semantics change the old comment said this needed.
`include_superseded` and `include_revoked` are two independent switches over
two different `CurationStatus` values, and **neither reveals the other**: a
record replaced by a newer one and a record withdrawn outright are different
facts, and a consumer asking to see graph history must not thereby be shown
retractions it did not ask for.

History is preserved, not hidden: nothing is deleted, the record keeps its
original `curation_epoch`, and `include_revoked=True` is the history surface
that returns it — including under an epoch-scoped read of the creation
epoch. *When* and *by whom* a revoke happened lives in the audit stream
(`AuditRecord`), which is where operation-level transaction time belongs;
`CanonicalEntity` carries no `revoked_at` and this ADR does not add one.

### 4. Reference implementation

`MemoryGraphStore.apply()` implements `REVOKE_IDENTITY` so the pair can be
*demonstrated* rather than asserted: a committed run of 8 `CREATE_IDENTITY`
operations is compensated by 8 `REVOKE_IDENTITY` operations, after which the
canonical read returns none of them and `include_revoked=True` returns all 8,
each `REVOKED`, each at its creation epoch. A `REVOKE_IDENTITY` naming an
unknown identity, or carrying no string `identity_id`, does not commit and
leaves the store untouched.

## Rationale

"Compensable" is load-bearing in the `CurationOperationType` docstring; an
operation type with no inverse makes the claim false for any plan containing
it. Adding the inverse is the minimum that makes the vocabulary's own
promise true.

Tombstone beats the alternatives on this platform's own terms. Supersession
misuses a status that means "replaced", and would be actively harmful given
`include_superseded`. Deletion contradicts the append-only model and destroys
the audit trail that ADR-0013 protects for the ledger and that `AuditRecord`
protects here. A tombstone retains everything and changes exactly one thing —
whether the identity is live.

Hiding `REVOKED` by default is what makes the tombstone mean anything. It
also matches the shape ADR-0013 already chose for the ledger: revoked rows
are excluded from the default surface while the data is retained and
reachable. The canonical graph gets the symmetric treatment with an explicit
flag, rather than the ledger's listing/lookup asymmetry, because
`include_superseded` already works uniformly across this read surface and a
second, differently-shaped rule would be a trap.

## Alternatives Considered

### Delete the entity

Simplest to reason about, and wrong: it destroys the record that a curation
run created something, which is the one thing a rollback must not do. The
module docstring rules it out in as many words.

### Reuse `SUPERSEDED` for a reversed identity

No new status, no new flag — but it lies about what happened (nothing
replaced this identity) and `include_superseded=True` would then return
reversed identities to every caller reading graph history, silently mixing
retractions into a supersession view.

### Add the operation type but leave REVOKED visible by default

Smaller diff, and it produces a rollback whose only observable effect is a
field nobody filters on. The compensation test would then verify that a plan
was produced, not that reversing worked — the "checks that verify nothing"
failure mode, shipped as a feature.

### Give `CanonicalEntity` a `revoked_at` transaction-time field

Would allow true status time-travel (`transaction_at` reads showing the
identity `ACTIVE` before the revoke). Deferred: entities carry no
transaction-time fields at all today and the memory store does no
transaction-time filtering for them, so this is a larger bitemporal change
than the defect requires. The audit stream already records when the revoke
happened. Recorded here as a known limitation: an epoch-scoped read of the
creation epoch finds the identity, but shows its *current* status.

## Consequences

### Positive

- A committed curation run is reversible, and the reversal is demonstrable
  end to end rather than asserted in prose.
- `INVERSE_OPERATION_TYPES` gives KGCS a contract-level answer to "can this
  be compensated?", and names the one gap that remains.
- Canonical reads now mean "live records" by default, which is what callers
  already assumed.

### Negative / Tradeoffs

- `REVOKED` records disappear from default canonical reads. This is a
  behaviour change for any adopter that wrote `REVOKED` entities or
  assertions directly and relied on seeing them; they add
  `include_revoked=True`. No in-platform operation produced `REVOKED`
  records before this change, so the affected set is records an adopter
  constructed by hand.
- `test_revoked_record_visible_by_default` is replaced. It pinned the old
  behaviour and named an ADR as the way to change it; this is that ADR.
- A revoked identity's status is its current status under every epoch-scoped
  read, not its status as of that epoch (see the deferred alternative).

### Risks

- An adopter's non-memory `GraphMutationStore` will raise on
  `REVOKE_IDENTITY` until it implements the operation. It is a new member of
  an existing enum, so the failure is loud (`NotImplementedError` / adapter
  error), not silent.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `src/kg_contracts/curation.py`, `src/kg_contracts/stores.py`,
  `src/kg_contracts/testing/memory.py`
- `tests/contracts/test_curation.py`, `tests/contracts/test_memory_adapters.py`
- `llm/specs/2026-07-09-kgis-kgcs-design.md` §7.1, §3.3
- ADR-0006 (three-store separation, curation epochs), ADR-0010 (write-path
  mechanism), ADR-0013 (ledger revoke as row-governance)

## Related Issues / PRs

- Issue #44; follow-up issue #45 (`PROMOTE_ONTOLOGY_TERM` has no inverse)

## Supersedes

ADR-0006 in part — the canonical read surface now hides `REVOKED` records by
default and exposes `GraphReadOptions.include_revoked`, where previously
`include_superseded` was the only status-visibility option.

## Superseded By

None.
