# ADR candidate: Two small `kg_contracts` gaps — public ULID helper, attribute vocabulary

Status: Proposed (candidate)
Date: 2026-07-14
Raised by: Sprint 1 — Core Ingestion Engine (kgis)

Two unrelated but similarly-sized contract gaps, filed together to keep the
candidate list short. Either can be promoted independently.

## Gap A — no public deterministic-ID helper

### Context

Idempotency and replay require the pipeline to mint **deterministic**,
ULID-shaped identifiers (`candidate_id`, `trace_id`) — same fact, same ID,
across processes. `kg_contracts` has exactly the encoder needed
(`kg_contracts._ulid`: a Crockford base32 encoder producing 26-char
ULID-shaped strings), but it is private: leading underscore, no re-export in
`kg_contracts.__init__`, docstring "internal helper".

`kgis.ids` needs to produce IDs that are drop-in wherever a contract ULID is
expected, but derived from a content digest rather than time+randomness. It
therefore reimplemented the Crockford base32 encoder (~10 lines) rather than
importing a private symbol from another package.

### Decision (proposed)

Promote a minimal, public ID surface on `kg_contracts` — e.g. an
`encode_crockford32(data: bytes, length: int) -> str` and/or a
`stable_id(*parts: str) -> str` — so both random (`_ulid.new_ulid`) and
deterministic (kgis) minting share one canonical encoder and one guaranteed
alphabet/length.

Sprint 1 workaround: `kgis.ids._encode_crockford`, a faithful reimplementation,
with a code comment pointing here.

### Rationale

Reaching into another package's private module to save ten lines is the worse
trade — it couples `kgis` to an underscore-prefixed internal that its owner is
free to change without notice. But two independent copies of a base32 encoder
is a latent divergence: if the contract's alphabet or length ever changed, a
kgis ID would silently stop matching a contract ULID's shape. A single public
helper removes both hazards. Every future producer of deterministic IDs (ledger
row IDs in Plan 2, resolution keys later) will want it too.

## Gap B — `GraphDescriptor` declares no attribute vocabulary

### Context

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

### Decision (proposed)

Add an `attribute_types: tuple[str, ...]` (or richer attribute schema) to
`GraphDescriptor`, so a graph's declared attribute vocabulary is registry-backed
like its node and edge types, and `from_descriptor()` can enforce it.

Sprint 1 workaround: attributes are unconstrained when read from a descriptor;
strict attribute checking requires a hand-built `Ontology`.

### Rationale

Attributes are first-class facts in this model — an `AttributeAssertionCandidate`
is a bitemporal claim with evidence and its own curation. A graph that can
declare which entity and relation types it accepts, but not which attributes,
has an asymmetric ontology: two of the three candidate-bearing term kinds are
governable from the registry and the third is not. Baseball-ai (Phase 1) will
want to say "a Player has height_cm and weight_kg, not shoe_brand" at the
registry level.

## Consequences

### Positive

- One canonical ID encoder; symmetric ontology governance across all term kinds.

### Negative / Tradeoffs

- Gap B widens `GraphDescriptor` — a frozen, `extra="forbid"` model — so it is a
  contract-version-visible change (spec §5.8 compatibility class:
  BACKWARD_COMPATIBLE, an added optional field).

### Risks

- Low. Both are additive; neither changes existing behavior.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Implementation

## Related Documents

- `src/kgis/ids.py` (Gap A workaround)
- `src/kgis/ontology.py` (Gap B workaround, `from_descriptor`)
- `kg_contracts/_ulid.py`, `kg_contracts/registry.py`

## Supersedes

None.

## Superseded By

None.
