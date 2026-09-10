# ADR-0008: Identity model — immutable internal identity IDs plus namespaced aliases

Status: Accepted
Date: 2026-07-10

## Context

The v1 contracts made canonical `Label:key` strings the entity identity at
every write boundary (ts-kg `canonical.py` lineage, introduced after the
agentic-tskg 0/18 failure where human-readable labels landed where
canonical identifiers were required). External review (PR #1) showed
identity frequently outlives labels and natural keys: titles change,
athletes change teams, organizations rename, ontology labels rename,
source keys are wrong or reused across systems, and one real entity holds
several legitimate identifiers. Bare `Player:123` says nothing about who
issued the key; the existing format establishes no graph namespace, source
namespace, key type, identifier authority, escaping, versioning, or
alias model.

## Decision

Every canonical entity has an **immutable internal identity ID** (e.g.
`kg://<graph-id>/identity/01J...`) that never changes, plus **namespaced
external aliases** represented structurally as
`EntityRef{entity_type, namespace, key}` and rendered as
`Label:namespace:key` (e.g. `Paper:doi:10.1145/...`, `Athlete:usssa:12345`)
only at adapter boundaries. Bare `Label:key` is deprecated for
cross-project use. A corrected natural key updates aliases, never the
identity. The repair-or-reject discipline is preserved unchanged: repair
if unambiguous, reject naming the offending ID, never silently coerce.

Cross-graph identity is contract-complete in v1: global identity ID,
graph-local identity ID, aliases, `SAME_AS` / `POSSIBLY_SAME_AS` /
`RELATED_TO` semantics, and authority + provenance on every mapping.
Implementation stays minimal until the retrofit phases need it.

## Rationale

Merges, splits, and key corrections are core KGCS operations; they are
only reversible and auditable if identity is stable under all of them.
Namespacing makes the identifier authority explicit — the strongest single
signal in both entity resolution and the extend-vs-new decision. The
proven repair gate is kept; only the format it enforces is upgraded.

## Alternatives Considered

### Keep bare `Label:key` as the identity (v1 model)

Readable and already implemented in ts-kg, but unsafe across projects
(key collisions between issuers) and brittle under renames and key
corrections — repairing a key would change the entity's identity.

### Opaque UUIDs only, no readable aliases

Maximally stable but destroys the readability that made `Label:key`
valuable for debugging, review queues, and reports; forces every consumer
through a lookup service.

### Mandatory namespace inside the key string only (`Label:ns:key`, no internal ID)

Fixes issuer ambiguity but still couples identity to a mutable natural
key; a wrong-key repair still rewrites identity and every edge.

## Consequences

### Positive

- Merges/splits/key repairs preserve identity; SUPERSEDED_BY and audit
  chains stay coherent.
- Identifier authority is explicit and machine-checkable at admission.
- Cross-graph mappings have a stable anchor on both ends.

### Negative / Tradeoffs

- Two-level identity (internal ID + aliases) is more to implement and
  explain than one string.
- Existing `vttsi-contracts` consumers must migrate formats during the
  supersession (Phase 2/3 shadow + retrofit work).

### Risks

- Adopters could treat a favorite alias as the identity again —
  mitigated by contracts exposing `EntityRef` structurally and rendering
  strings only at adapter boundaries.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §5.1: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Feedback: `docs/ai/chatgpt-feedback-2026-07.md` (Response 1 §2 "Canonical
  ID repair risk", Response 2 §1)
- Disposition: `docs/ai/chatgpt-feedback-disposition.md` (A4, A14)

## Related Issues / PRs

- PR #1 (external design review capture + disposition)

## Supersedes

None (upgrades the canonical-ID contract carried in the spec and the
governance delta; no prior ADR fixed the ID format).

## Superseded By

None.
