# ADR-0002: Contracts live in agentic-kgis as kg_contracts

Status: Accepted
Date: 2026-07-08

## Context

The shared contracts (GraphStore protocol, schemas, ingestion/curation/
registry interfaces) need a home. `vttsi-contracts` exists but is
traffic-safety-branded; KGIS/KGCS need domain-neutral contracts that all
projects adopt.

## Decision

`agentic-kgis` hosts a `kg_contracts` subpackage (one distribution, two
packages: `kg_contracts` + `kgis`). `agentic-kgcs` depends only on
`kg_contracts`. `vttsi-contracts` is eventually superseded by re-exports
from `kg_contracts`.

## Rationale

Two repos instead of three; matches the folders already created; contracts
still cleanly separated at the package level (no engine/LLM/I/O code).

## Alternatives Considered

### Dedicated third contracts repo

Cleanest symmetry but adds a repo and cross-repo CI overhead.

### Generalize vttsi-contracts in place

Avoids a new package but entangles traffic-safety consumers in the
migration.

## Consequences

### Positive

- Fewer repos; single release train for contracts + ingestion.

### Negative / Tradeoffs

- Asymmetry: KGCS depends on KGIS's distribution.
- Contracts changes ride KGIS releases even when kgis code is untouched.

### Risks

- If the asymmetry becomes painful, extraction into a third repo is the
  documented escape hatch (contracts are already a distinct package).

## Impacted Areas

- [x] Architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §2.5, §5

## Supersedes

None.

## Superseded By

None.
