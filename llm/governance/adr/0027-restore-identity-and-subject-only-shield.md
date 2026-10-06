# ADR-0027: `RESTORE_IDENTITY` reverses a revoke at the original epoch; the assertion shield is subject-only

Status: Proposed
Date: 2026-10-06
Raised by: Issue #51 — the reverse leg of `REVOKE_IDENTITY` loses the creation epoch, found by adversarial review of PR #46 (ADR-0025); owner decisions on PR #54's open questions (Jason, 2026-10-06)

## Context

ADR-0025 made `REVOKE_IDENTITY` the inverse of `CREATE_IDENTITY` and chose
the epoch-preserving direction that issue #44 needed. §6 of that ADR
recorded a bound it deliberately did not fix:

```
CREATE_IDENTITY   -> ACTIVE  @ epoch 1
REVOKE_IDENTITY   -> REVOKED @ epoch 1   (preserved)
CREATE_IDENTITY   -> ACTIVE  @ epoch 3   (original creation epoch LOST)
```

Replaying `CREATE_IDENTITY` to compensate a revoke restores the identity's
status and visibility but re-stamps `curation_epoch`, because
`CREATE_IDENTITY` means "this identity came into existence now". After the
round trip an epoch-scoped read of the original creation epoch no longer
finds the identity — precisely the failure the epoch-preservation rule
exists to prevent, reappearing on the reverse leg. ADR-0025 proved the
obvious cheap repair (letting `CREATE_IDENTITY` honour a payload epoch)
unsound: it would stop `CREATE_IDENTITY` assigning epochs at all and let
callers forge them, corrupting the forward-leg guarantee. ADR-0025 therefore
concluded that a distinct operation type that flips status without touching
the epoch is the only correct repair, and named it `RESTORE_IDENTITY` as
issue #51.

PR #54 fixed the two other `REVOKE_IDENTITY` semantics holes (#49/#50,
ADR-0026) and left two open questions for the owner:

1. Should an assertion on a **live** identity whose `object_identity` is
   revoked be shielded (object-side shielding)?
2. Is a future `RESTORE_IDENTITY` the intended un-revoke path that restores
   the read-shielded assertions?

The owner decided on 2026-10-06:

- **(a)** assertions on a live identity whose **object** identity is revoked
  are **not** hidden; they stay visible on default reads;
- **(b)** un-revoke must be an option: implement issue #51.

## Decision

### 1. `CurationOperationType.RESTORE_IDENTITY`

A new member that reverses a `REVOKE_IDENTITY`: it sets the entity's
`CurationStatus` back to `ACTIVE`, **retains the record and its original
`curation_epoch`**, and thereby lifts the ADR-0026 assertion shield — the
withdrawn identity's assertions become visible again, each with its own
status intact (a `SUPERSEDED` assertion stays `SUPERSEDED`; the shield was
never an assertion mutation).

Payload: `{"identity_id": <identity id>}`, plus an optional `"reason"` —
the same shape as `REVOKE_IDENTITY` and for the same reason. The executor
restores the entity actually in the graph, so a stale copy carried in the
plan cannot overwrite it; the pre-restore (`REVOKED`) entity belongs in the
operation's `reversal_data`.

The restore commits as **its own curation epoch** — the append-only
status-change entry — while the record keeps its original epoch stamp. This
is the same asymmetry ADR-0025 chose for revoke: the batch's new epoch is
the unit of "the graph changed"; the record's epoch is the epoch it was
created in. A revoke/restore cycle is therefore epoch-preserving in **both**
directions: `REVOKED @ E -> ACTIVE @ E`.

Restoring an identity that is **not** `REVOKED` does **not** commit. It
returns `CommitResult(committed=False, error=...)` naming the identity and
its current status, leaves the store unchanged, and allocates no epoch —
the exact mirror of ADR-0026 §3's double-revoke rule. Only `REVOKED` is
restorable; an `ACTIVE` identity (never revoked, or already restored) and a
`SUPERSEDED` identity are both non-commits. `REVOKE -> RESTORE -> REVOKE`
in sequence works, landing back on `REVOKED` at the original creation epoch.

### 2. `INVERSE_OPERATION_TYPES` retargets the reverse leg; the map is read-only

`INVERSE_OPERATION_TYPES[REVOKE_IDENTITY]` becomes `RESTORE_IDENTITY`, and
`INVERSE_OPERATION_TYPES[RESTORE_IDENTITY]` is `REVOKE_IDENTITY`.
`INVERSE_OPERATION_TYPES[CREATE_IDENTITY]` stays `REVOKE_IDENTITY`: a
genuine create is still undone by withdrawing it.

The identity row is therefore **deliberately not an involution**:
`CREATE -> REVOKE`, but `REVOKE -> RESTORE`, not `CREATE`. That asymmetry is
the whole point — it is what keeps the reverse leg epoch-preserving — and a
test pins it so a future "clean up the map into an involution" change cannot
silently reintroduce issue #51. Every other entry still pairs symmetrically.

The mapping is now an immutable `MappingProxyType`, closing issue #48:
`kg_contracts` declares an undo pairing as contract, and a process-wide
in-place mutation could otherwise paper over `PROMOTE_ONTOLOGY_TERM`'s
deliberate absence (issue #45) invisibly to every other module. In-place
writes now raise `TypeError`, matching the rest of the package's
immutable-at-rest containers.

### 3. Object-side shielding is rejected: the shield stays subject-only (owner decision (a))

An assertion on a **live** subject whose `object_identity` is revoked
**remains visible on default reads**. Withdrawing the object is not a
retraction of the relation: subject and object are different records, and a
`REVOKE_IDENTITY` on the object says nothing about the live subject's
assertion. Shielding it would silently hide facts stated by an identity no
one withdrew, and would force a reader to pass `include_revoked=True` to see
assertions that are not themselves revoked.

`neighborhood()` keeps its current behaviour and still **drops** the revoked
target: a revoked node is not a live neighbour. That is not in tension with
(a) — the assertion is still served by `assertions_for(subject)` on a
default read; the revoked object is reachable through it only with
`include_revoked=True`. The relation edge survives; the withdrawn endpoint
does not surface as a live node.

### 4. Conformance coverage

`GraphMutationStoreContract` — the published suite every adapter must pass —
gains, alongside the ADR-0025/0026 revoke tests:

- `test_restore_identity_undoes_a_revoke_and_preserves_creation_epoch` — the
  reverse leg, including that a default read *as of the creation epoch*
  finds the identity again;
- `test_restore_identity_lifts_the_assertion_shield` — the shield is lifted,
  assertion statuses untouched;
- `test_restore_identity_of_active_identity_does_not_commit` and
  `test_second_restore_of_already_restored_identity_does_not_commit` — the
  two loud no-op forms, each consuming no epoch;
- `test_revoke_restore_revoke_cycle_returns_to_revoked_at_the_creation_epoch`;
- `test_restore_identity_assertion_visibility_flag_cross_terms` — restoring
  lifts the *subject* shield but does not collapse `include_superseded` and
  `include_revoked`: after restore an assertion whose own status is `REVOKED`
  still needs `include_revoked`, and a `SUPERSEDED` one still needs
  `include_superseded`;
- `test_assertion_on_live_subject_with_revoked_object_stays_visible_by_default`
  — owner decision (a), plus the `neighborhood()` consequence.

### 5. Reference implementation

`MemoryGraphStore.apply()` implements `RESTORE_IDENTITY` as the exact mirror
of `REVOKE_IDENTITY`, so the pair can be demonstrated end to end rather than
asserted: a restored identity is visible again by default, at its creation
epoch, and its assertions return. An unknown identity, a missing string
`identity_id`, or a target that is not `REVOKED` does not commit and leaves
the store untouched.

## Rationale

**A status flip is not a create.** The bound in ADR-0025 §6 is structural,
not incidental: `CREATE_IDENTITY` stamping the committing epoch is what
makes a created identity belong to the epoch that created it. The repair
ADRs 0025 and 0027 both refuse — teaching `CREATE_IDENTITY` to honour a
payload epoch — trades the forward-leg guarantee for the reverse leg and
lets callers forge epochs. A dedicated operation that changes exactly one
thing (`status`) and leaves the epoch alone is the only repair that keeps
both legs consistent.

**Read-time shielding makes restore free.** ADR-0026 chose read-time
shielding over an executor cascade partly because un-revoking should restore
the assertions without replaying each one. `RESTORE_IDENTITY` is that
un-revoke: the shield is a function of the subject's current status, so
flipping it back restores every assertion at once, with every status
preserved. An executor cascade to `REVOKED` would have made restore lossy.

**The subject/object distinction is the one the contract already draws.**
ADR-0026 §Risks recorded object-side shielding as explicitly out of scope;
the owner has now decided it stays out. Keeping the shield subject-only is
also the only rule that is cheap to state: "an assertion is hidden iff its
subject is revoked", not "iff its subject or its object is revoked", which
would make a live subject's facts depend on a later operation on another
record — the same write-amplification objection ADR-0026 raised against the
executor cascade.

**Loud non-commits keep epochs meaningful.** An epoch means "the graph
changed". Restoring something that is not revoked changes nothing, so
committing a fresh epoch for it would make epoch arithmetic — and any
epoch-scoped consumer — lie. This is ADR-0026 §3's argument, applied to the
mirror operation.

## Alternatives Considered

### Keep `INVERSE_OPERATION_TYPES[REVOKE_IDENTITY] = CREATE_IDENTITY` and document the bound

The status quo. Rejected by the owner decision (b): the bound is a real
correctness gap on the reverse leg — an epoch-scoped read loses the identity
— and issue #51 exists precisely to close it. Leaving the wrong inverse in
the published contract would also keep `agentic-kgcs`'s compensator unable
to reverse a rollback correctly.

### Let `CREATE_IDENTITY` honour a payload `curation_epoch`

Provably wrong; ADR-0025 §6 measured it reddening three tests, two on the
forward leg, and it hands callers epoch forgery. Explicitly not attempted.

### Make the identity row a clean involution (`REVOKE <-> RESTORE`, `CREATE <-> RESTORE`)

Would require `CREATE_IDENTITY`'s inverse to be `RESTORE_IDENTITY`, which is
nonsensical: compensating a create by "restoring" a never-revoked identity
is the non-commit this ADR defines. The map is a compensation function, not
an equivalence relation, and the `CREATE -> REVOKE` entry is the forward leg
ADR-0025 exists to provide.

### Shield assertions whose `object_identity` is revoked (owner option rejected)

Rejected by decision (a). It would hide live subjects' facts because of a
later operation on a different record, and force `include_revoked` to read
assertions that are not themselves revoked.

### Cascade the restore to the assertions (write `ACTIVE` back over them)

Rejected for the same reason ADR-0026 rejected the revoke cascade: it would
overwrite each assertion's own status, destroying the `SUPERSEDED` fact. The
shield is a read rule; restore is a status flip on the subject.

## Consequences

### Positive

- The identity vocabulary is now reversible in both directions at the
  original creation epoch; issue #51's round trip is closed, not merely
  bounded.
- The published `INVERSE_OPERATION_TYPES` names the correct reverse leg, so
  `agentic-kgcs`'s compensator has a contract-level answer for undoing a
  revoke.
- The public pairing map is immutable, closing issue #48.
- Object-side behaviour is explicit and pinned: the shield is subject-only,
  and `neighborhood()` keeps dropping revoked targets.

### Negative / Tradeoffs

- The `INVERSE_OPERATION_TYPES` identity row is no longer an involution. That
  is intentional and tested, but it is a shape change consumers must not
  "correct".
- Adapters must now implement `RESTORE_IDENTITY` and pass its conformance
  tests; an adapter that does not will fail the published suite (the point).
- The bitemporal limitation ADR-0025 recorded for revoke applies to restore
  too: `CanonicalEntity` carries no status-time field, so an epoch-scoped
  read shows the record's *current* status, and the sequence of status
  changes lives in the append-only commit history (and the audit stream),
  not in a per-epoch status projection. This ADR does not add that field.

### Risks

- A non-memory `GraphMutationStore` — `agentic-kg`'s
  `Neo4jCanonicalGraphStore` — must add `RESTORE_IDENTITY`; until it does it
  raises on a new enum member (a loud failure, not a silent one). Listed as a
  follow-up, not done here.
- `agentic-kgcs`'s compensator inverse table (its ADR-0020) must adopt the
  retargeted reverse leg; until it does, an `agentic-kgcs` compensation of a
  `REVOKE_IDENTITY` would still choose the old path. Listed as a follow-up,
  not done here.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `src/kg_contracts/curation.py` (`CurationOperationType`,
  `INVERSE_OPERATION_TYPES`), `src/kg_contracts/stores.py`
  (`GraphReadOptions`), `src/kg_contracts/testing/contract.py`
  (`GraphMutationStoreContract`), `src/kg_contracts/testing/memory.py`
  (`MemoryGraphStore.apply`)
- `tests/contracts/test_curation.py`, `tests/contracts/test_memory_adapters.py`
- ADR-0025 (`REVOKE_IDENTITY` inverts `CREATE_IDENTITY`; §6 records the bound
  this ADR resolves), ADR-0026 (the assertion shield this ADR lifts on
  restore; double-revoke semantics this ADR mirrors), ADR-0013 (loud revoke),
  ADR-0021 (a non-commit must name a reason)

## Related Issues / PRs

- Issue #51 (`RESTORE_IDENTITY`) — fixed by this ADR. Issue #48
  (`INVERSE_OPERATION_TYPES` mutability) — fixed by this ADR.
- Raised from the open questions of PR #54; extends ADR-0025/0026.
- Related: #45 (`PROMOTE_ONTOLOGY_TERM` has no inverse), #47 (the
  `resolved_identity`/`create_new_identity` shape), #52 (published
  `find_entities`/`neighborhood` coverage).
- Follow-ups, deliberately not touched here: `agentic-kgcs`'s compensator
  inverse table (its ADR-0020) and `agentic-kg`'s
  `Neo4jCanonicalGraphStore` must adopt `RESTORE_IDENTITY`.

## Supersedes

ADR-0025 §6 in part — the reverse-leg bound is resolved by a dedicated
`RESTORE_IDENTITY` operation, exactly as that section anticipated. ADR-0025's
decision (the `CREATE_IDENTITY` -> `REVOKE_IDENTITY` direction) stands
unchanged.

## Superseded By

None.
