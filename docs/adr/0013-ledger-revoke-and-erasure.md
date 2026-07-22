# ADR-0013: Ledger revoke and erasure as row-governance, orthogonal to ProcessingState

Status: Accepted
Date: 2026-07-21

## Context

The candidate ledger (ADR-0012) is designed to be durable, replayable, and
bitemporal — every submitted candidate is retained with a full transition
history. But Issue #2 (baseball-ai adoption gating) requires two data-subject
rights the ledger did not yet support:

- **Withdrawal ("revoke"):** a source retracts a candidate (e.g. a scout
  correction, a bad ingest) and it should stop appearing in normal ledger
  listings, without destroying the audit trail or the ability to look the
  record up directly.
- **Irrecoverable deletion ("erase"):** a data subject exercises a legal
  erasure right (e.g. GDPR) and the underlying payload must become
  unrecoverable, while the ledger still proves *that* a record existed and
  was erased, and by whom/why/when.

These are governance actions on a *row*, not points in the candidate's
processing lifecycle (`RECEIVED` → ... → terminal states in
`kg_contracts.curation.ProcessingState`). Conflating them with
`ProcessingState` would require editing the frozen `kg_contracts` enum (out
of scope for Plan 2 outside Task Group 0) and would mix two different
concerns: *what curation stage is this candidate at* vs. *is this row still
visible / does its payload still exist*.

## Decision

Model revoke and erase as row-governance columns on `ledger_entries`,
already reserved in the Task-4 schema (`revoked_at`, `revocation_reason`,
`erased_at`, `erasure_reason`), orthogonal to `ProcessingState`:

- **`revoke(candidate_id, reason, actor)`** sets `revoked_at` /
  `revocation_reason`. The payload and full row are retained. Default
  `ledger_entries()` listings exclude revoked rows (`revoked_at IS NULL`,
  wired in Task 8), but `ledger_entry(candidate_id)` / `row(candidate_id)`
  still resolve the row — the data is retained, only hidden from the default
  listing surface. `LedgerRow.is_revoked` exposes the state. Raises `KeyError`
  if the row does not exist or is already erased (nothing left to revoke).
- **`erase(candidate_id, reason, actor)`** — gated by
  `ConsumerProfile.erasure_enabled` (ADR-0014); raises `PermissionError`
  otherwise — NULLs `payload_json` irrecoverably, sets `erased_at` /
  `erasure_reason`, and keeps the pre-existing `payload_hash` as a hash-only
  tombstone. After erase, `ledger_entry(candidate_id)` returns `None` and
  `ledger_entries()` excludes the row (`payload_json IS NOT NULL`, wired in
  Task 8) because the full `Candidate` can no longer be reconstructed from a
  null payload. `LedgerRow.is_erased` proves existence-plus-erasure without
  exposing content.
- Both operations append a `ledger_transitions` row (`from_state ==
  to_state`, `reason="revoked: ..."` / `"erased: ..."`, `actor`) so the
  governance action is itself part of the append-only audit trail, and both
  follow the same rollback-on-failure transaction discipline as `submit()`
  (Task 7) and `transition()` (Task 9): wrap the write in `try`/`except`,
  roll back and re-raise on any failure, commit only on success.
- No new `ProcessingState` member is added.

## Rationale

- **Governance vs. lifecycle stay separate.** A candidate can be revoked or
  erased at any `ProcessingState` (received, quarantined, or terminal) — it
  is not a stage in curation, so it does not belong in the transition table
  `kgis.ledger.lifecycle` governs.
- **No frozen-contract edit.** `ProcessingState` lives in `kg_contracts`,
  frozen outside Task Group 0. Row-governance columns were already reserved
  in the Task-4 schema for exactly this purpose, so this decision needs zero
  contract changes.
- **Erasure must be provable, not just silent.** A hash-only tombstone
  (`payload_hash` survives; `payload_json` does not) combined with the
  `ledger_transitions` audit row lets an operator prove *that* erasure
  happened and *when*, without being able to reconstruct the erased content
  — satisfying both "right to erasure" and "must remain auditable."
- **Revoke is reversible in principle; erase is not.** Revoke only flips a
  visibility flag and retains the payload, so it could be un-set by a future
  operation if the data controller decides the retraction was wrong. Erase
  destroys the payload at the row level — reinstating it would require
  resubmitting the original candidate from source, which is the correct
  incentive shape for an irrecoverable-deletion primitive.

## Alternatives Considered

### Add `REVOKED`/`ERASED` members to `ProcessingState`

Rejected. This conflates a governance action with the curation lifecycle,
requires editing the frozen `kg_contracts.curation.ProcessingState` enum
outside the one permitted prerequisite (Task Group 0, Issue #7), and would
force every legal transition-table entry to reason about revoke/erase as if
they were curation outcomes rather than row-level governance metadata
orthogonal to *any* processing state.

### Physical row delete on erase

Rejected. Deleting the `ledger_entries` row outright destroys the audit
trail's ability to prove the row ever existed or that erasure occurred —
unacceptable for a compliance-driven erasure feature, which must remain
provable after the fact (spec's append-only audit stream, Task Group 3).

## Consequences

### Positive

- Erasure is provable via the retained hash tombstone and the audit
  transition row (Task 13), without needing to keep any of the original
  content.
- Revoke is non-destructive and reversible in principle since data is
  retained; only listing visibility changes.
- No `kg_contracts` edits; both operations layer entirely on the Task-4
  schema's already-reserved columns.

### Negative / Tradeoffs

- Two distinct "gone" states (revoked vs. erased) for consumers to reason
  about, in addition to terminal `ProcessingState` values — slightly more
  surface area than a single deletion flag.
- `erase` is a one-way operation per row; there is no built-in
  un-erase, by design (see Rationale).

### Risks

- A consumer that forgets `ledger_entries()` filters out revoked/erased rows
  by default could be surprised when a `ledger_entry(id)` direct lookup still
  resolves a revoked (but not erased) row — this is intentional (data
  retained) but must be documented clearly for adopters.

## Impacted Areas

- [ ] Product
- [ ] Domain model
- [x] Data architecture
- [ ] AI architecture
- [ ] Domain-specific systems (see governance delta)
- [ ] Integrations
- [ ] UX
- [x] Security/privacy
- [x] Implementation
- [x] Documentation

## Related Documents

- ADR-0012 (candidate ledger persistence via stdlib sqlite3)
- ADR-0014 (identity mode + consumer profile) — `erase` is gated by
  `ConsumerProfile.erasure_enabled` from that ADR
- Plan: `docs/superpowers/plans/2026-07-17-plan-2-candidate-ledger-evidence-registry.md`
  (Task Group 1, Task 10)
- Implementation: `src/kgis/ledger/store.py` (`revoke`, `erase`, `is_revoked`,
  `is_erased`), `src/kgis/ledger/row.py` (`LedgerRow.is_revoked`,
  `LedgerRow.is_erased`)

## Related Issues / PRs

- Issue #2 (baseball-ai adoption-gating: revoke/erasure + reject-only
  identity)

## Supersedes

None.

## Superseded By

None.
