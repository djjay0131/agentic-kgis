# ADR-0011: Canonical reads are canonical-only; ledger visibility is a separate read surface

Status: Accepted
Date: 2026-07-13

## Context

ADR-0006 established the three-store separation (candidate ledger / canonical
graph / derived projections) and specified that all reads take a
`GraphReadOptions` record whose field list included `include_provisional`
("opt-in ledger visibility"). Spec v2 §5 and the Plan 1 contract
(`kg_contracts.stores.GraphReadOptions`) both carried that field.

A PR #6 review flagged `include_provisional` on the canonical read surface as
an architectural leak. On inspection the criticism holds on ADR-0006's own
terms:

- ADR-0006's decision is that the three stores may share one physical database
  but **never one access path**, and that uncertain candidates **never appear
  as ordinary graph entities**. `GraphReader` is the canonical access path. A
  flag on that path that surfaces ledger (provisional) records makes the
  canonical reader an access path into the ledger — precisely the coupling the
  separation exists to forbid.
- `include_provisional` is a vestige of the superseded ADR-0003 model, in which
  provisional records lived *in the main graph* filtered by status. ADR-0006
  removed provisional data from the canonical graph entirely. Under ADR-0006
  the canonical graph contains no provisional records, so on a canonical reader
  the flag is either a leak (if an adapter interprets it as "reach into the
  ledger") or a dead no-op (the Plan 1 reference `MemoryGraphStore` never read
  it). Both are defects: a documented option that either violates the
  separation or does nothing.

## Decision

1. **Remove `include_provisional` from `GraphReadOptions`.** The canonical read
   surface (`GraphReader` / `TemporalGraphReader`) exposes no ledger-visibility
   option. With `extra="forbid"` on the model, reintroducing such a flag as a
   read option is unrepresentable rather than a silently ignored kwarg.
2. **Introduce a separate ledger read surface**, expressed in contracts as
   ADR-0006 requires ("separation enforced by contracts"):
   - `LedgerReader` — a runtime-checkable protocol, distinct from `GraphReader`,
     that returns candidate-ledger rows. Reads only; ledger writes go through
     `CandidateSink`.
   - `LedgerReadOptions` — filters over the ledger (`processing_states`,
     `graph_id`).
   - `LedgerEntry` — the minimal read projection: a `Candidate` paired with its
     ledger `ProcessingState` and receipt time. (The full persisted ledger row
     — dedup keys, retry counters, quarantine reasons — is modeled by the
     ledger store in Plan 2; this is only the read shape the separation needs at
     the contract layer.)
   A `GraphReader` and a `LedgerReader` are never the same protocol. One store
   may implement both (over one physical database, as the reference
   `MemoryCandidateSink` does: `CandidateSink` write + `LedgerReader` read), but
   the surfaces stay separate, so "uncertain candidates never appear in a
   canonical query" is a structural guarantee, not a flag a caller must
   remember to leave unset.

## Rationale

The three-store separation is only as strong as its narrowest access path. A
single boolean on the canonical reader would reintroduce, at the contract
boundary, exactly the "consumers must filter status" fragility ADR-0006 set out
to eliminate — the same class of weakness the external review identified in
ADR-0003. Making canonical and ledger reads two protocols pushes the guarantee
into the type system: an adapter cannot accidentally serve ledger data from a
canonical query, and a consumer holding a `GraphReader` has no method that could
return an uncertain record.

## Alternatives Considered

### Keep `include_provisional`, document it as ledger opt-in

Rejected. It keeps a ledger access path on the canonical reader — the leak — and
in Plan 1 it was a dead no-op no reference adapter honored. Documentation cannot
make a canonical reader safely dual-purpose.

### Remove the flag, defer any ledger reader to Plan 2

Rejected as too weak. ADR-0006 mandates that the separation be *contract*
-enforced, and Plan 1 is the contracts layer. Leaving no ledger read contract
would invite the next implementer to re-add a canonical-side flag. The Plan 1
addition is the protocol + options + minimal entry shape and a reference
implementation; the full ledger store remains Plan 2.

## Consequences

### Positive

- Canonical reads cannot surface ledger data — enforced structurally, not by
  caller discipline.
- Ledger visibility (review tooling, operator inspection) has an explicit,
  typed home with `ProcessingState` filtering.
- `extra="forbid"` makes a future re-leak a hard error.

### Negative / Tradeoffs

- Two read protocols instead of one; an adapter wanting both implements both
  (the reference does, over one dict).

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [ ] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §3.3, §5.6 (GraphReadOptions corrected; ledger read surface):
  `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Implementation: `src/kg_contracts/stores.py` (`GraphReadOptions`,
  `LedgerReader`, `LedgerReadOptions`, `LedgerEntry`),
  `src/kg_contracts/testing/memory.py` (`MemoryCandidateSink` as `LedgerReader`),
  `src/kg_contracts/testing/contract.py` (`LedgerReaderContract`).

## Related Issues / PRs

- PR #6 (Plan 1 v2 execution) review.

## Supersedes

ADR-0006, in part — the `include_provisional` field of the `GraphReadOptions`
record specified in its Decision section. The three-store separation, curation
epochs, and every other `GraphReadOptions` field are unchanged; this ADR only
replaces canonical-side ledger visibility with a separate `LedgerReader`
surface, which better satisfies ADR-0006's own "never one access path"
principle.

## Superseded By

None.
