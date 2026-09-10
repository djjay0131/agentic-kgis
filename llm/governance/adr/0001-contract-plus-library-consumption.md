# ADR-0001: Contract + library consumption model

Status: Accepted
Date: 2026-07-08

## Context

Every portfolio project builds a knowledge graph and reinvented ingestion
and curation. KGIS/KGCS must be consumable by all of them (baseball-ai,
agentic-kg, ts-kg, construction-ai) without forcing shared infrastructure.

## Decision

KGIS and KGCS ship as installable Python libraries behind a shared
contracts package (ports-and-adapters), following the proven
vttsi-contracts pattern. Each project embeds the libraries against its own
graph backend. No always-on service in v1.

## Rationale

Cheapest to run, matches the portfolio's proven contract-first discipline,
and a service wrapper can be layered on later without churn to consumers.

## Alternatives Considered

### Deployed services (Cloud Run APIs)

Centralized queue/dashboards but adds ops cost and makes every project
network-dependent.

### Hybrid library + thin service

Best long-term flexibility but more upfront design than v1 needs; remains
the natural evolution path.

## Consequences

### Positive

- Zero standing infrastructure; adopters test fully in-memory.
- Backend swaps stay behind the GraphStore protocol.

### Negative / Tradeoffs

- No centralized review UI in v1 (CLI per project).
- Version skew across adopters must be managed via releases.

### Risks

- If adopters diverge on contract versions, coordination cost grows.

## Impacted Areas

- [x] Architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §2, §3

## Supersedes

None.

## Superseded By

None.
