# ADR-0006: Three-store separation — candidate ledger / canonical graph / derived projections, with curation epochs

Status: Accepted
Date: 2026-07-10

## Context

ADR-0003 had uncertain extractions land in the main graph as `PROVISIONAL`
nodes, filtered by consumers via `CurationStatus`. External design review
(PR #1) identified this as the design's biggest weakness: uncertainty
becomes operational contamination. Graph traversals accidentally treat
provisional nodes as real; provisional duplicates inflate degree and
community structure; GraphRAG summaries amplify uncertain facts; every
consumer must remember to filter status; provisional nodes acquire
relationships before identity is resolved; a later merge changes
neighborhoods and derived metrics unpredictably. Filtering on
`status = ACCEPTED` is also insufficient for consistency: without a
snapshot or watermark, one query can observe a partially promoted batch.

## Decision

Separate three logical stores, with the separation enforced by contracts
(they may share one physical database, never one access path):

1. **Candidate ledger** — immutable, replayable proposed assertions and
   entities (source coordinates, extractor/model/ontology versions,
   normalized payload, evidence refs, quality signals, dedup keys,
   processing state). Uncertain candidates live here and never appear as
   ordinary graph entities.
2. **Canonical graph** — only accepted identities and assertions, with
   explicit validity, scores, and provenance.
3. **Derived projections** — disposable, reproducible artifacts (search
   indices, GraphRAG communities/summaries, embedding caches, aggregates,
   views). Never canonical facts unless independently curated.

Canonical mutations commit as atomic **curation epochs**: resolve/validate
→ prepare batch → commit → advance the visible curation watermark →
rebuild/invalidate affected projections. All reads take explicit
`GraphReadOptions{curation_epoch, valid_at, transaction_at,
include_provisional, include_superseded, minimum_evidence_policy}` and
default to canonical-only at a published epoch.

Spec invariant: **derived projections are built only from canonical data
at a published curation epoch.**

## Rationale

A candidate is an assertion about the world, not yet an entity in the
world; the store layout must make that distinction unavoidable rather than
convention-dependent. Epoch publication gives consumers a consistency
contract instead of per-project ad-hoc status filters, and makes GraphRAG
artifacts reproducible and disposable by construction.

## Alternatives Considered

### Single graph with PROVISIONAL status filtering (ADR-0003 model)

Simplest storage story and matches agentic-kg's current behavior, but
pushes correctness onto every consumer query, contaminates derived
structure, and cannot prevent torn reads of partially promoted batches.

### Fully separate physical databases per store

Strongest isolation, but forces every adopter to run three datastores and
complicates small deployments. The contracts enforce separation; physical
co-location stays a deployment choice.

### Post-hoc cleanup sweeps over a freely written graph

Already rejected in ADR-0003 (agentic-tskg 0/18 post-mortem); listed for
completeness — the ledger model is the opposite discipline.

## Consequences

### Positive

- Uncertainty can never leak into traversals, projections, or GraphRAG
  summaries.
- Readers get repeatable results pinned to an epoch; projection rebuilds
  are deterministic.
- The ledger is immutable and replayable — reprocessing with a new
  extractor or ontology version is a re-run, not surgery.

### Negative / Tradeoffs

- More moving parts than one graph: ledger, epoch publication, and
  projection invalidation must all be built and operated.
- Canonical visibility of new data is delayed until an epoch publishes
  (bounded by curation SLOs, ADR-0003's surviving async-plane principle).

### Risks

- Ledger backlog growth and priority inversion — mitigated by explicit
  backlog controls, SLOs, and backpressure (spec §7.7).
- Adopters could co-locate stores and then bypass the access-path
  separation; the two-level store contracts (ADR-0010) are the guard.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §3 (three-store separation, epochs, GraphReadOptions), §7.7:
  `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Feedback: `docs/ai/chatgpt-feedback-2026-07.md` (Response 1 §2, Response 2 §6)
- Disposition: `docs/ai/chatgpt-feedback-disposition.md` (A1, A22 invariant)

## Related Issues / PRs

- PR #1 (external design review capture + disposition)

## Supersedes

ADR-0003, in part — the clause "Probabilistic curation runs
asynchronously: sub-1.0-confidence entities land `PROVISIONAL` and are
promoted/merged by confidence-routed resolution", insofar as it places
provisional entities in the main graph. The layered-write-path principle
itself (deterministic admission synchronous, probabilistic curation async)
survives; provisional data now lives in the candidate ledger.

## Superseded By

ADR-0011, in part — the `include_provisional` field of the `GraphReadOptions`
record specified in this ADR's Decision section. Canonical reads are now
canonical-only, and ledger visibility is a separate `LedgerReader` surface. The
three-store separation, curation epochs, and every other `GraphReadOptions`
field stand unchanged; ADR-0011 follows directly from this ADR's own "never one
access path" principle.
