# ADR candidate 0010: Erasure cascades from the ledger to the evidence registry

Status: Proposed (awaiting owner promotion)
Date: 2026-10-08
Raised by: Issue #61 (KGPS upstream prerequisite U8)

## Context

`SqliteCandidateLedger.erase()` (ADR-0013) is **logical erasure of one ledger
row**: it NULLs `payload_json`, keeps a hash-only tombstone, and records an
`erase` transition plus an audit row. The passage text a candidate cites does
not live in the ledger, though — it lives in the evidence registry
(`kgis.evidence`, spec §5.3), where `SqliteEvidenceRegistry` stores up to
`_MAX_INLINE_CHARS` (4000) characters of source text per `Evidence` plus the
candidate's `evidence_refs`.

So a ledger-only `erase()` erased the `Candidate` and left the passage it was
extracted from fully readable (and still resolvable through
`registry.resolve(candidate_id)`). The 2026-10-07 KGPS provenance audit filed
this as upstream prerequisite **U8** in
`agentic-kgps/llm/specs/2026-10-07-kgps-design.md` §7. ADR-0013 already
disclaims at-rest destruction but promises "the payload is no longer readable
through the ledger API"; the registry was an unstated second payload store, so
that promise was incomplete.

The two stores are separate SQLite databases in the ordinary deployment, but a
consumer may hand one `sqlite3.Connection` to both. Any fix has to define its
atomicity in both shapes.

## Decision

Add `kgis.erasure.ErasureCoordinator`, a cross-store erasure operation over a
`(SqliteCandidateLedger, SqliteEvidenceRegistry)` pair, rather than teaching the
ledger about the evidence registry.

`ErasureCoordinator.erase(candidate_id, reason, actor)`:

1. removes every `evidence_ref` whose `subject_id` is the erased candidate;
2. for each evidence id that now has **zero** remaining refs, redacts it:
   `content=None`, `payload_hash` retained (derived from the content if the
   evidence never had a hash), availability still `PRESENT`, plus durable
   `redacted_at` / `redaction_reason` columns on the `evidence` row;
3. appends one `kind='redact'` row per redaction to the ledger's append-only
   `audit_records` stream, keyed to the erased candidate and carrying the
   retained evidence hash.

Evidence still referenced by any other subject is left untouched. "Orphan"
means *zero refs*, not *zero live-candidate refs*: a revoked (but not erased)
candidate keeps its refs by ADR-0013, so evidence it shares must stay readable.

`ErasureCoordinator.revoke(...)` delegates to `ledger.revoke(...)` and changes
nothing else. Revoke stays ledger-only and **retains** evidence refs, so
`registry.resolve(candidate_id)` still returns the cited evidence after a
revoke. This is the deliberate answer to the issue's open question: revoke is
non-destructive visibility control, not erasure, and is reversible in principle;
only `erase` removes refs and redacts content.

### Connection shapes and atomicity

- **Same connection** (both stores wrap one `sqlite3.Connection`): the erase
  transition, ref removal, redaction, and audit rows run in a single
  transaction and commit together. Fully atomic; any failure rolls back all of
  it.
- **Separate connections** (the ordinary case, usually separate files): the
  registry writes are staged first, then the ledger writes, then the registry
  commits and the ledger commits. A failure before either commit rolls both
  back. The residual window — registry committed, ledger commit failing — is
  surfaced as `ErasureIncompleteError`: the passage is already redacted (the
  privacy objective holds) and only the ledger half is unfinished.
- **Separate connections to the same file**: unsupported. SQLite admits one
  writer at a time, so staging both transactions fails closed before any commit;
  the coordinator rolls both back and re-raises. Consumers sharing a file must
  pass the same connection.

## Rationale

**Why a coordinator, not a ledger collaborator.** The cascade is a cross-store
reconciliation: orphan detection needs the whole ref table, redaction belongs to
the evidence store, and the audit row belongs to the ledger. Putting it on the
ledger would make the ledger package depend on `kgis.evidence`, couple row
governance to evidence policy, and create a second code path that behaves
differently depending on whether a registry was wired. A dedicated operation
names the thing being done and keeps each store's existing, tested primitives
(`erase`, `_remove_subject_refs_stmt`, `_redact_evidence_stmt`) as the
transaction participants.

**Why keep the redaction marker at rest, not on the `Evidence` contract.**
`Evidence` (`kg_contracts.evidence`) is a frozen contract; adding a `redacted`
field is a contract change with an ADR of its own (cf. ADR-0021/0023) and is
unnecessary. The redacted record is already `PRESENT` with `content=None` and a
`payload_hash` — exactly the "PRESENT-by-hash" shape KGPS already recognises as
its `HASH_ONLY_EVIDENCE` gap. The durable marker is two nullable columns on the
`evidence` table, added idempotently to existing databases when the registry
opens them.

**Why registry-first commits.** In the only shape where true atomicity is
unavailable, committing the registry first guarantees the passage text is
unreadable even if the ledger commit then fails — the privacy guarantee is the
one that must hold first. The failure is reported, never swallowed.

## Alternatives Considered

### The ledger takes an optional `registry` collaborator

Rejected. It couples the ledger package to the evidence store, makes `erase`
behave differently depending on wiring, and gives orphan detection (a registry
concern) a home in the ledger. It also does not remove the cross-store
transaction problem; it just hides it inside `erase`.

### Redact a candidate's evidence only if *no live candidate* references it

Rejected as unsound. A revoked candidate is not "live" under
`LIVE_ROW_PREDICATE` but retains its payload and refs (ADR-0013); redacting its
shared evidence would break `resolve()` for a record whose data is supposed to be
retained. The precise orphan test is "no references remain at all".

### Add a `redacted` field to `kg_contracts.evidence.Evidence`

Rejected (deferred at most). It is a frozen-contract change, and the
`content=None` + `payload_hash` shape already carries the semantic. Kept out of
an L2 implementation PR.

### Physical delete of refs/evidence

Rejected. Deleting the evidence row destroys the hash tombstone that makes the
erasure provable, the same reason ADR-0013 rejects deleting the ledger row.
Deleting refs is necessary (the citation is the erasure target), but the
evidence record and its hash survive.

## Consequences

### Positive

- A data-subject erasure no longer leaves up to 4000 characters of passage text
  and a live `resolve()` path behind.
- Erasure stays provable: hash tombstones on the ledger row and on each redacted
  evidence row, plus `kind='redact'` audit entries.
- No `kg_contracts` edit.

### Negative / Tradeoffs

- Erasure is now a two-store operation with a documented atomicity boundary for
  separate connections; same-file separate connections must be reconfigured.
- The `evidence` table gains two columns (auto-migrated) and the audit stream
  gains a `kind`.

### Risks

- An adopter that keeps calling `ledger.erase()` directly still gets ledger-only
  erasure. Mitigated by docstrings on `erase`/`revoke` and the adopter notes
  pointing at `ErasureCoordinator`; a future ADR could deprecate the bare call.

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

- ADR-0013 (ledger revoke and erasure as row-governance) — the ledger-only
  primitive this extends
- ADR-0006 (three-store separation) / ADR-0011 (ledger read surface)
- KGPS design spec §7, upstream prerequisite U8:
  <https://github.com/djjay0131/agentic-kgps/blob/main/llm/specs/2026-10-07-kgps-design.md>
- Implementation: `src/kgis/erasure.py`, `src/kgis/evidence/store.py`,
  `src/kgis/evidence/schema.py`, `src/kgis/ledger/store.py`
- Tests: `tests/kgis/test_erasure_coordinator.py`

## Related Issues / PRs

- Issue #61 (this repo)
- KGPS tracking issue djjay0131/agentic-kgps#1

## Supersedes

None.

## Superseded By

None.
