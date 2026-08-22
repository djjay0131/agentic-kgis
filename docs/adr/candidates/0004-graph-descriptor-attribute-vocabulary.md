# ADR candidate: `GraphDescriptor` should declare an attribute vocabulary

Status: Proposed (candidate)
Date: 2026-07-14
Raised by: Sprint 1 — Core Ingestion Engine (kgis)

> Split note: this candidate was originally filed jointly with the public
> deterministic-ID helper as `0003-contract-gaps-ulid-and-attributes`. Per the
> PR #9 review, the two are unrelated decisions and were split. The ID-helper
> half is now [0003-A](0003-a-public-deterministic-id-helper.md). This half
> needs registry/advisor review because it changes what `GraphDescriptor`
> promises, so it is filed on its own.

## Context

Ontology coverage (spec §6: "unknown types reported, never hidden") is measured
against the terms a graph declares. `GraphDescriptor` (spec §8,
`kg_contracts.registry`) declares `node_types` and `edge_types` — so entity
types and relation types can be checked — but has **no** field for attribute
names. Yet `AttributeAssertionCandidate` carries an `attribute`, and the sprint
validates and reports attribute coverage.

`kgis.ontology.Ontology.from_descriptor()` can therefore populate entity and
relation vocabularies from a registered graph, but must leave `attributes`
unconstrained (empty = "accept anything"). Attribute ontology enforcement only
works when an `Ontology` is constructed by hand with an explicit attribute set;
it cannot be derived from the registry.

## Decision (proposed)

Add an `attribute_types: tuple[str, ...]` (or richer attribute schema) to
`GraphDescriptor`, so a graph's declared attribute vocabulary is registry-backed
like its node and edge types, and `from_descriptor()` can enforce it.

Sprint 1 workaround: attributes are unconstrained when read from a descriptor;
strict attribute checking requires a hand-built `Ontology`.

## Rationale

Attributes are first-class facts in this model — an `AttributeAssertionCandidate`
is a bitemporal claim with evidence and its own curation. A graph that can
declare which entity and relation types it accepts, but not which attributes,
has an asymmetric ontology: two of the three candidate-bearing term kinds are
governable from the registry and the third is not. Baseball-ai (Phase 1) will
want to say "a Player has height_cm and weight_kg, not shoe_brand" at the
registry level.

Because this changes what a `GraphDescriptor` promises, it is not a purely local
call — it wants registry/advisor review (spec §8) before promotion, which is why
it is dispositioned separately from the ID helper.

## Consequences

### Positive

- Symmetric ontology governance across all three candidate-bearing term kinds.
- `from_descriptor()` can enforce attributes without a hand-built `Ontology`.

### Negative / Tradeoffs

- Widens `GraphDescriptor` — a frozen, `extra="forbid"` model — so it is a
  contract-version-visible change (spec §5.8 compatibility class:
  BACKWARD_COMPATIBLE, an added optional field).

### Risks

- Low-to-moderate. Additive and backward-compatible, but it touches the
  registry surface and so should pass advisor review before promotion.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation

## Resolution in the Plan 7 registry (2026-08-21)

The persistent registry (`src/kgis/registry/store.py`) resolves this gap
without editing the frozen contract, using **registry extension attributes**:
a per-graph-version key/value sidecar persisted alongside each
`GraphDescriptor`. A graph declares its attribute vocabulary under the
reserved key `attribute_types` (a comma-separated list), and
`RegisteredGraph.attribute_types()` reads it back. The advisor's ontology
factor already scores against `node_types ∪ edge_types ∪ attribute_types`, so
attribute governance is symmetric with entity/relation governance *at the
registry layer* today.

This is the least-invasive resolution: no contract change, and if the owner
accepts this candidate the same data promotes cleanly into a
`GraphDescriptor.attribute_types` field. Until then, the vocabulary lives in
the extension sidecar rather than the frozen model. The Sprint 1
`from_descriptor()` workaround (attributes unconstrained) is unchanged for
callers that read a bare descriptor; a caller that reads the registry's
extension attributes can now enforce attributes.

The same extension-attribute mechanism carries the open backend identifier —
see candidate [0005](0005-open-backend-identifier.md).

## Related Documents

- `src/kgis/ontology.py` (workaround, `from_descriptor`)
- `src/kgis/registry/store.py`, `src/kgis/registry/models.py` (Plan 7 resolution)
- `kg_contracts/registry.py`

## Supersedes

None.

## Superseded By

None.
