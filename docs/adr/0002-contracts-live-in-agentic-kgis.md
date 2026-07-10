# ADR-0002: Contracts live in agentic-kgis as kg_contracts

Status: Accepted (amended 2026-07-10)
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

## Amended 2026-07-10

Per the approved disposition of external review PR #1 (item R2, and A13
with owner confirmation): `agentic-kgis` ships **three** packages —
`kg_contracts`, `kgis`, and `kg_eval` (ADR-0009) — in one distribution.
The two-repo layout stands: `agentic-kgcs` still ships only `kgcs` and
depends only on `kg_contracts`. The feedback's four-package module
boundaries (contracts / ingestion / curation / eval) are accepted as
package boundaries, not as repos; extraction into more repos remains the
documented escape hatch. `kg_contracts` v2 is written fresh with
`vttsi-contracts`, `ts-kg`, and `vttsi-evidence` as reference reading —
no code vendoring (owner decision, 2026-07-10).

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §2.5, §4, §5, §10.1 (v2)
- `docs/ai/chatgpt-feedback-2026-07.md` (Response 2 §5, §12)
- `docs/ai/chatgpt-feedback-disposition.md` (R2, A13, A18/Phase 0)
- PR #1 (external design review capture + disposition)

## Supersedes

None.

## Superseded By

None.
