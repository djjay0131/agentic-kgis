# ADR candidate: `GraphDescriptor.backend` should be an open identifier

Status: Proposed (candidate)
Date: 2026-08-21
Raised by: Plan 7 — Registry / Advisor (kgis)

## Context

`kg_contracts.registry.Backend` is a closed `StrEnum` with exactly three
members: `SPANNER`, `NEO4J`, `MEMORY`. `GraphDescriptor.backend: Backend` is a
required field on a `frozen`, `extra="forbid"` model, so a graph *cannot* be
registered against any backend outside that enum.

Baseball-ai's compatibility sprint flagged this directly (Issue #2 item 3,
PC-6 / finding G6): the closed enum excludes the Postgres / Apache AGE class of
backends, which are exactly what a non-Spanner, non-Neo4j adopter would use.
Spec §8 itself says "SQLite for v1, Postgres optional" for the registry store —
so the portfolio already anticipates backends the enum cannot name.

## Decision (proposed)

Make the backend an **open identifier**. Options, least to most invasive:

1. Widen `Backend` to a plain `str` (or a `str`-subtype with a documented
   convention), keeping the current three as recommended constants.
2. Keep `Backend` for the well-known classes but add an optional
   `backend_uri: str | None` free-form field for anything the enum cannot
   express.

Either keeps existing descriptors valid (the three enum values are still
legal), so the change is **BACKWARD_COMPATIBLE** (spec §5.8): a widened type
and/or an added optional field.

## Plan 7 workaround (implemented)

The registry does **not** edit the frozen contract. It carries the open backend
identifier as a **registry extension attribute** (`backend.open_id`), persisted
per graph version alongside the descriptor:

```python
store.register(descriptor, backend_ref="postgres+age")
graph = store.snapshot()[0]
graph.resolved_backend  # -> "postgres+age" (falls back to the enum when unset)
```

`descriptor.backend` still holds a coarse enum bucket to satisfy the contract;
`RegisteredGraph.resolved_backend` prefers the open identifier when present.
This is the same extension-attribute mechanism that resolves the attribute
vocabulary gap (candidate 0004), so both promote cleanly if accepted.

## Rationale

A closed backend enum makes the contract, not the deployment, decide which
storage engines exist. That inverts the intended layering: ADR-0006's
three-store separation and ADR-012's infrastructure layer are about *where*
data lives, and the set of stores is an operational fact that outlives any one
frozen contract version. An open identifier lets a Postgres/AGE adopter join
without a contract revision.

## Consequences

### Positive

- Postgres / Apache AGE and future backends are registrable without a contract
  change.
- Removes a baseball-ai-flagged adoption blocker (Issue #2 item 3 / G6).

### Negative / Tradeoffs

- An open string loses the enum's closed-set validation; a typo'd backend id
  would register. Mitigated by keeping recommended constants and (optionally)
  a registry-side validation list.

### Risks

- Low. Additive/back-compatible; the workaround already isolates the concern to
  a registry attribute, so promotion is a mechanical lift.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation

## Related Documents

- `kg_contracts/registry.py` (`Backend`, `GraphDescriptor.backend`)
- `src/kgis/registry/store.py`, `src/kgis/registry/models.py` (workaround)
- Issue #2 item 3 (baseball-ai compatibility, PC-6 / G6)
- ADR-0006 (three-store separation), construction-platform ADR-012

## Supersedes

None.

## Superseded By

None.
