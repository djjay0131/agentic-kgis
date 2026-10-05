# ADR-0026: A revoked identity shields its assertions; single-batch ordering; double revoke fails loudly

Status: Accepted
Date: 2026-10-05
Raised by: Issues #49 and #50 — adversarial review of PR #46 (ADR-0025)

## Context

ADR-0025 made `CurationOperationType.REVOKE_IDENTITY` a real inverse of
`CREATE_IDENTITY`: it tombstones the `CanonicalEntity` (status `REVOKED`,
record and original `curation_epoch` retained, hidden from default reads)
and added the independent `GraphReadOptions.include_revoked` switch. It
left three consequences of that design uncharacterised, all found by
adversarial review of the PR that shipped it.

**#49 — a revoked identity's assertions stay visible.** `REVOKE_IDENTITY`
flips the *entity*; its `Assertion` records are untouched and keep
`status=ACTIVE`, so `assertions_for(<revoked identity>)` still returns
them on a default read. A rolled-back curation run therefore leaves live
assertions hanging off an identity no reader can see, and `neighborhood()`
drops the entity but can still reach assertions through its subject. The
issue asked whether the executor should cascade the revoke to the
assertions or whether a compensating plan must enumerate a
`RETRACT_ASSERTION` for each — and noted the latter cannot be demonstrated
end to end because `RETRACT_ASSERTION` is still `NotImplementedError` in
the reference store (Plan 3).

**#50a — create-then-revoke in one batch fails.** `MemoryGraphStore.apply()`
builds every operation before applying any (deliberate: this is what makes
a failed precondition leave the store unchanged), so a `REVOKE_IDENTITY`
in the same batch as the `CREATE_IDENTITY` that mints its target looks the
target up in `self._entities`, does not find it, and returns
`committed=False` with "names an unknown identity" — misattributing the
cause.

**#50b — double revoke commits silently.** A second `REVOKE_IDENTITY` of
an already-`REVOKED` identity found the entity, wrote another `REVOKED`
copy, bumped the entity version, and returned `committed=True` with a
fresh epoch: a no-op that consumes an epoch and looks like it did
something. ADR-0013's ledger `revoke()` takes the opposite position,
raising `KeyError` when there is nothing left to revoke.

The issues were reachable only in edge cases, not from the compensation
path PR #46 targeted (a compensator revokes identities a *previously
committed* plan created, once). But the published
`GraphMutationStoreContract` is the surface every adapter is held to, and
these are contract questions, so they are settled here rather than left to
each adapter.

## Decision

### 1. A revoked identity shields its assertions from default reads (#49)

A canonical read of a revoked identity's assertions returns nothing by
default. `assertions_for(<revoked identity>)` is empty unless
`include_revoked=True`, and `include_revoked=True` is the history surface
that returns them — mirroring exactly how the identity itself is served.

This is a **read rule, not an assertion mutation**. The assertions keep
their own `CurationStatus`; the executor does not rewrite them to
`REVOKED`. The distinction is load-bearing: a `SUPERSEDED` assertion on a
revoked identity is still known to have been *superseded*, which is a
different fact from the identity being withdrawn, and the two switches
stay independent — a `SUPERSEDED` assertion on a `REVOKED` identity is
returned only when **both** `include_revoked` and `include_superseded`
are set. Collapsing the flags into one "show everything" switch would
erase the distinction ADR-0025 created them for.

History is not deleted: the assertions are retained in place, their status
is preserved, and `include_revoked=True` (plus `include_superseded` where
relevant) returns them. The mechanism deliberately does **not** enumerate
a `RETRACT_ASSERTION` per assertion: a compensating plan that names each
one still cannot be demonstrated (Plan 3), the enumeration is unbounded
work for the compensator, and a retraction is a *stronger* claim than a
`REVOKE_IDENTITY` makes — it says the fact was withdrawn, not that the
identity that asserted it was. Shielding at read time keeps one operation's
meaning: the identity is withdrawn, and what hung off it is withdrawn with
it. Un-revoking the identity (issue #51's `RESTORE_IDENTITY`) automatically
restores its assertions, which an assertion-level retraction would not.

### 2. A batch's operations apply in order (#50a)

`apply()` builds a **staged** view of the entities as it walks
`batch.operations`, so a later operation sees an earlier one in the same
batch. A `REVOKE_IDENTITY` naming an identity created earlier in the same
batch is therefore coherent and commits: the batch produces a tombstone at
its own epoch. The target may be pre-existing *or* created earlier in the
batch; a revoke that appears before its target's create is still the
honest "unknown identity" failure, and the store is left untouched.

The ordering constraint is part of the contract, not an implementation
detail: operations are significant in sequence, and a compensator that
wants to create-and-withdraw must order the operations create-then-revoke.
The "unknown identity" error is retained for the genuinely-unknown case,
which is now distinguishable from the same-batch case.

### 3. Double revoke fails loudly and consumes no epoch (#50b)

A `REVOKE_IDENTITY` whose target is already `REVOKED` — whether set before
the batch or earlier in the same batch — does **not** commit. It returns
`CommitResult(committed=False, error=...)` naming the already-revoked
identity, leaves the store unchanged, and allocates no new epoch. This is
the `CommitResult` analogue of ADR-0013's ledger `revoke()`, which raises
`KeyError` when there is nothing left to revoke: the operation is not
idempotent-and-silent, because a silent no-op with a fresh epoch is
precisely the "looks like it did something" failure the issue names.

`committed=False` — rather than an exception — is the contract's own
failure channel (`CommitResult` requires a non-commit to name a reason by
ADR-0021), and it keeps `apply()` total for an executor that must report,
not crash on, a stale plan.

## Rationale

**The shield makes ADR-0025's rollback observable at the assertion
layer.** ADR-0025 hid the entity so a revoke would change what a reader
sees; leaving the assertions visible re-opened the same hole one level
down. A revocation that still leaves the withdrawn identity's facts
queryable has not, in practice, withdrawn them.

**Read-time shielding beats an executor cascade.** The obvious executor
alternative — flip attached assertions to `REVOKED` — destroys the
supersession fact (a `SUPERSEDED` assertion would become `REVOKED`),
makes the reverse leg harder, and does work proportional to the degree of
the node at revoke time. Read-time shielding is O(1), preserves every
assertion's own status, and keeps `include_superseded` and
`include_revoked` independent.

**Ordered staging is the truthful reading of a batch.** A batch is a
sequence of operations that share one epoch. Treating it as a set forced
`apply()` to reject a coherent create-then-revoke pair with a message that
was wrong about why. Staging makes the implemented semantics match the
stated ones without weakening atomicity: the whole batch is still built
before anything is written, so any failure — unknown identity, already
revoked, bad payload — leaves the store entirely unchanged.

**Failing loudly on double revoke keeps epochs meaningful.** An epoch is
the unit of "the graph changed". Advancing it for a write that changed
nothing makes epoch arithmetic and any epoch-scoped consumer lie.

## Alternatives Considered

### Enumerate `RETRACT_ASSERTION` per assertion in the compensating plan

Auditable at the assertion level, and the issue's first suggestion. Rejected
for now: `RETRACT_ASSERTION` is unimplemented (Plan 3), so the pair cannot
be demonstrated; the compensator would have to read the graph to enumerate
the assertions, reintroducing the read-modify-write the executor-only
contract exists to avoid; and a retraction overstates a revoke by claiming
the fact itself was withdrawn. If assertion-level retraction is ever wanted
it is a separate, additive operation, not a prerequisite for the identity
shield.

### Executor cascade: rewrite attached assertions to `REVOKED`

Rejected. It mutates history to `REVOKED`, losing the `SUPERSEDED` fact the
cross-term depends on; it is O(degree) at revoke time; and it makes the
status of an assertion depend on a later operation on a *different* record,
which is a write-amplification and audit problem for no read-side benefit.

### Silent idempotent double revoke (`committed=True`, no new epoch)

Rejected. A success that changes nothing and names the same epoch is
ambiguous to the caller — it cannot tell "already revoked, fine" from
"the revoke landed" — and the issue's comparison to ADR-0013 points the
other way. If a future caller genuinely wants idempotent revoke, it can
treat the specific error as success; the primitive should not guess.

### Silent idempotent double revoke with a new epoch

The status quo the issue reports. Rejected: it consumes an epoch for a
no-op and returns `committed=True`, the exact "looks like it did
something" shape.

### Reject create-and-revoke in one batch (document the failure)

A defensible smaller change. Rejected because the pair is coherent — it
means "mint and immediately withdraw", a tombstone at creation — and once
`apply()` stages operations it costs nothing to support. Rejection would
also leave the misleading error message in place.

## Consequences

### Positive

- A rolled-back curation run is now unreadable at the assertion layer too:
  no live assertions hang off a withdrawn identity on any default read.
- `include_superseded` and `include_revoked` remain independent at both the
  entity and assertion layers, now pinned by cross-term conformance tests.
- Create-then-revoke in one batch works and commits a tombstone; the
  ordering rule is documented in the contract, not discovered by an
  adopter.
- A double revoke is a loud, actionable non-commit that consumes no epoch.

### Negative / Tradeoffs

- Adapters must implement the assertion shield and the double-revoke
  non-commit; the published `GraphMutationStoreContract` now fails an
  adapter that does not. This is the point — the suite is what holds the
  `agentic-kg` Neo4j store to the same semantics — but it is a conformance
  break for an existing adapter.
- `assertions_for` now consults the subject entity's status, a small extra
  lookup per read; an adapter that keys assertions without their subject
  entity will need to join to it.
- A batch is order-sensitive. That was already true in effect; it is now
  contractual.

### Risks

- An adapter that stores assertions by predicate rather than by subject may
  find the shield awkward to implement efficiently; the contract does not
  prescribe storage, only the read result.
- The shield is defined on the *subject* identity only. An assertion on a
  live identity that points at a revoked identity as its `object_identity`
  is not shielded by this ADR; `neighborhood()` already drops the revoked
  target. If object-side shielding is wanted it is a separate decision.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `src/kg_contracts/testing/memory.py` (`MemoryGraphStore.apply`,
  `assertions_for`, `_subject_visible`)
- `src/kg_contracts/testing/contract.py` (`GraphMutationStoreContract`)
- `tests/contracts/test_memory_adapters.py`
- ADR-0025 (`REVOKE_IDENTITY` inverts `CREATE_IDENTITY`; this ADR extends
  it), ADR-0013 (ledger revoke fails when nothing is left to revoke),
  ADR-0021 (a non-commit must name a reason)

## Related Issues / PRs

- Issues #49 (a revoked identity's assertions stay visible) and #50
  (single-batch ordering; double revoke) — both fixed by this ADR.
- Related: #51 (`RESTORE_IDENTITY`, the reverse leg), #45
  (`PROMOTE_ONTOLOGY_TERM` has no inverse), #48 (`INVERSE_OPERATION_TYPES`
  mutability), #52 (published `find_entities`/`neighborhood` coverage).

## Supersedes

None. Extends ADR-0025.

## Superseded By

None.
