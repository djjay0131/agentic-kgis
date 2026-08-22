# ADR-0012: Candidate ledger persistence via stdlib sqlite3

Status: Accepted
Date: 2026-07-21

## Context

Plan 1 shipped only an in-memory `MemoryCandidateSink` / `MemoryGraphStore`
reference adapter behind the frozen `CandidateSink` (write-in) and
`LedgerReader` (read-back) ports (ADR-0011). That adapter is sufficient to
prove the contracts and to drive the reusable contract-suite tests, but it is
not durable: process restart loses every candidate, its `ProcessingState`,
dedup history, and retry/quarantine bookkeeping.

The candidate ledger is ADR-0006 store 1 — the durable record of proposed
assertions/entities awaiting or having passed curation, each carrying its own
processing state, distinct from the canonical graph and from derived
projections. Plan 2 also hardens `kg_contracts` at-rest immutability for dict
payload fields (Issue #7, Task Group 0, this branch). That guarantee is only
meaningful — and only testable end-to-end — against a store that actually
persists bytes at rest; an in-memory dict has no "at rest" to violate or
verify, so Issue #7 needs a real backing store to exercise before Plan 2's
other tasks (bitemporal rows, lifecycle transitions, revoke/erase, audit
stream) can build on it.

## Decision

Persist the candidate ledger in SQLite, accessed through Python's stdlib
`sqlite3` module — no new runtime dependency — behind the unchanged, frozen
`CandidateSink` and `LedgerReader` ports. Concretely (this task):

- `src/kgis/ledger/schema.py` defines the full DDL as a single `SCHEMA_SQL`
  string, applied idempotently (`CREATE TABLE IF NOT EXISTS`) — tables
  `ledger_meta`, `ledger_entries`, `ledger_transitions`, `audit_records`. The
  `audit_records` table is created now (schema single-sourced in one place)
  even though it is not populated until Task Group 3.
- `open_ledger_db(path)` opens (creating if absent) a connection with
  `row_factory = sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA
  journal_mode=WAL`, applies the DDL, and records `SCHEMA_VERSION` (currently
  `1`) into `ledger_meta`.
- One physical SQLite file per graph deployment; `:memory:` for tests and
  ephemeral use. `ledger_entries.graph_id` scopes rows within a shared file if
  a deployment ever colocates graphs, but the default is one file per graph.
- Bitemporal columns (`valid_from`/`valid_to` domain time, `recorded_at`
  transaction time) are part of `ledger_entries` from this first schema
  version, per spec §5.4 — later tasks populate and query them; this task only
  reserves the columns.

Later Task Group 1 tasks build the persisted row model (`LedgerRow`), the
`ProcessingState` transition table, the `SqliteCandidateLedger` write/read
implementation, and revoke/erase — all on top of this schema, with zero edits
to `kg_contracts`.

## Rationale

- **No new dependency.** `sqlite3` ships with the Python standard library;
  adopting it costs nothing on the dependency surface the global constraints
  forbid growing (no ORMs, no heavier embedded/server databases at this
  stage).
- **Real at-rest guarantee.** A file-backed store gives Issue #7's frozen
  dict-payload fields something to actually be immutable *at rest* against —
  serialized JSON that survives a restart — rather than only in-process
  object identity.
- **WAL mode** allows concurrent readers while a single writer append-only
  transitions the ledger, matching the append/transition-heavy access pattern
  (candidates rarely deleted, transitions and audit rows appended).
- **Idempotent bootstrap** (`CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`
  for the schema-version row) makes `open_ledger_db` safe to call on every
  process start without a separate migration-runner for this first schema
  version.

## Alternatives Considered

### Ephemeral in-memory dict (status quo, extended)

Rejected. Plan 1's `MemoryCandidateSink` already proves the contracts; keeping
it as the *only* ledger implementation would leave Issue #7's at-rest
immutability requirement unverifiable (there is no "at rest" for a live Python
dict) and would mean every restart silently discards ingested candidates —
unacceptable for a candidate ledger that must support cross-run idempotent
replay (spec §5.4).

### Postgres or another server-hosted RDBMS

Deferred, not rejected outright. A server backend would add real dependencies
(driver, connection pool, a running server process) and operational surface
this plan does not need yet — a single ingestion service writing to its own
ledger has no multi-writer coordination requirement that `sqlite3` + WAL can't
satisfy. Full temporal query support is explicitly capability-declared (spec
§5.7) rather than required of every backend, so a future backend swap remains
possible behind the same `CandidateSink`/`LedgerReader` ports without
revisiting this decision.

## Consequences

### Positive

- Durable, replayable candidate ledger: process restarts no longer lose
  ingested candidates or their processing state.
- A real substrate for Issue #7 at-rest immutability, ADR-0013's revoke/erase
  surface, and the append-only audit stream (spec §7.8).
- WAL mode supports concurrent reads without blocking the writer.
- Zero new runtime dependencies.

### Negative / Tradeoffs

- SQLite is single-writer; a future multi-process ingestion topology would
  need to either serialize writers or swap backends (permitted by the port
  boundary, not free).
- Schema evolution now needs explicit version bookkeeping (`ledger_meta`,
  `SCHEMA_VERSION`) rather than an ORM-managed migration tool.

### Risks

- WAL-mode `.db-wal`/`.db-shm` sidecar files must be included in any backup or
  deployment file-copy strategy, or a copy can silently miss uncommitted WAL
  contents.

## Impacted Areas

- [ ] Product
- [ ] Domain model
- [x] Data architecture
- [ ] AI architecture
- [ ] Domain-specific systems (see governance delta)
- [ ] Integrations
- [ ] UX
- [ ] Security/privacy
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §3.2, §5.4, §5.7 (candidate ledger, bitemporal rows, capability-
  declared temporal query): `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- ADR-0006 (three-store separation), ADR-0011 (canonical reads are
  canonical-only; ledger read surface)
- Plan: `docs/superpowers/plans/2026-07-17-plan-2-candidate-ledger-evidence-registry.md`
  (Task Group 1, Task 4)
- Implementation: `src/kgis/ledger/schema.py`

## Related Issues / PRs

- Issue #7 (at-rest immutability) — this store is the substrate that makes it
  testable.

## Supersedes

None.

## Superseded By

None.
