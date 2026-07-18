# ADR candidate: A public deterministic-ID helper on `kg_contracts`

Status: Proposed (candidate)
Date: 2026-07-14
Raised by: Sprint 1 — Core Ingestion Engine (kgis)

> Split note: this candidate was originally filed jointly with the
> `GraphDescriptor` attribute-vocabulary gap as `0003-contract-gaps-ulid-and-attributes`.
> Per the PR #9 review, the two are unrelated decisions with different blast
> radii — a small additive helper versus a registry/advisor-governed change to
> what a graph promises — and were split so each can be dispositioned on its own.
> The attribute-vocabulary half is now [0004](0004-graph-descriptor-attribute-vocabulary.md).

## Context

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

## Decision (proposed)

Promote a minimal, public ID surface on `kg_contracts` — e.g. an
`encode_crockford32(data: bytes, length: int) -> str` and/or a
`stable_id(*parts: str) -> str` — so both random (`_ulid.new_ulid`) and
deterministic (kgis) minting share one canonical encoder and one guaranteed
alphabet/length.

Sprint 1 workaround: `kgis.ids._encode_crockford`, a faithful reimplementation,
with a code comment pointing here and a drift-guard test
(`tests/kgis/test_ids.py`) that asserts byte-identical output against the
contract's private `_encode_base32`. That test is marked for deletion once
this public helper lands.

## Rationale

Reaching into another package's private module to save ten lines is the worse
trade — it couples `kgis` to an underscore-prefixed internal that its owner is
free to change without notice. But two independent copies of a base32 encoder
is a latent divergence: if the contract's alphabet or length ever changed, a
kgis ID would silently stop matching a contract ULID's shape. A single public
helper removes both hazards. Every future producer of deterministic IDs (ledger
row IDs in Plan 2, resolution keys later) will want it too.

## Consequences

### Positive

- One canonical ID encoder shared by random and deterministic minting.
- Removes the reimplementation and its drift-guard test.

### Negative / Tradeoffs

- Adds a small public surface to `kg_contracts` that must then be kept stable.

### Risks

- Low. Purely additive; changes no existing behavior.

## Impacted Areas

- [x] Domain model
- [x] Implementation

## Related Documents

- `src/kgis/ids.py` (workaround)
- `tests/kgis/test_ids.py` (drift guard, to be deleted on promotion)
- `kg_contracts/_ulid.py`

## Supersedes

None.

## Superseded By

None.
