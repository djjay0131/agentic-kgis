# Concepts

This page defines the KGIS vocabulary. It is the reference the usage guides point
back to. For authoritative depth, each concept links to the relevant ADR in the
repository's `llm/governance/adr/`.

## Candidate

A `Candidate` is a **proposed** assertion — never a committed fact. It is the
universal seam between ingestion (KGIS) and curation (KGCS). The candidate model
is a union of variants for the different things ingestion can propose, including:

- `EntityCandidate` — a proposed entity.
- `AttributeAssertionCandidate` — a proposed attribute value on an entity.
- `RelationCandidate` — a proposed relationship between two entities.
- `ObservationCandidate`, `IdentityLinkCandidate`, `DerivedAssertionCandidate`,
  `ArtifactCandidate`, `OntologyCandidate`, `PlanCandidate` — the remaining
  variants for richer proposals.

Every candidate carries source coordinates, versions, `CandidateScores`, and
(optionally) evidence references. `candidate_id`s are content-addressed, which is
what makes re-ingestion idempotent.

## CandidateSink

`CandidateSink` is the **only write surface anywhere in KGIS**. Its contract is
`submit(candidates) -> SubmissionResult`. Application code gets this surface and
nothing else — there is no direct graph-upsert method to reach for (ADR-0010).
Implementations include:

- `MemoryCandidateSink` — in-memory, for demos and tests.
- `SqliteCandidateLedger` — the durable, persistent ledger (below).

Graph *mutation* happens behind a separate, executor-only `GraphMutationStore`
that KGIS never exposes and KGCS drives.

## The candidate ledger

The persistent candidate ledger (`SqliteCandidateLedger`, ADR-0006 store 1,
ADR-0012) is a durable, replayable, bitemporal record of every submitted
candidate: source coordinates, extractor/model/ontology versions, normalized
payload, evidence refs, quality signals, and a **processing state**. Uncertain
candidates live *here* and never appear as ordinary graph nodes — that is the
whole point of the three-store separation.

### Row governance: revoke and erase

Two governance actions sit on a *row*, orthogonal to its processing state
(ADR-0013):

- **`revoke(candidate_id, reason, actor)`** — a **logical** withdrawal. The row
  and payload are retained; revoked rows are excluded from the default listing
  but still resolve on direct lookup. `LedgerRow.is_revoked` exposes the state.
- **`erase(candidate_id, reason, actor)`** — a **logical** erasure: it nulls the
  live payload so it can't be read back, while keeping a **hash tombstone** that
  proves a record existed and was erased (by whom / why / when).

!!! warning "Erasure is logical, not forensic"
    `erase` is *not* an at-rest or forensic scrub. It withdraws the live payload
    and keeps an auditable tombstone. Treat it as a governance/visibility
    operation, not as guaranteed byte-level destruction on disk.

## Evidence

Evidence makes KGIS *evidence-first*. A candidate can cite the passage, row, or
document it came from via an `EvidenceRef` that resolves through a
`SqliteEvidenceRegistry`. Evidence availability is always one of three states:

- **PRESENT** — the evidence is there (content or a payload hash).
- **ABSENT** — it is genuinely not there, with an `AbsenceReason` (an *honest
  null*, not a fake zero).
- **ERROR** — an error occurred fetching it, captured explicitly.

A **dangling `EvidenceRef` raises** — evidence is never silently dropped
(ADR-0009). This is what lets a downstream consumer trust that a cited fact can
actually be checked.

## Scores: two confidence axes

`CandidateScores` keeps two axes distinct and never collapses them into one
float (ADR-0004 as amended):

- **`source_reliability`** — how trustworthy the source is. **Required**, no
  default.
- **`extraction_confidence`** — how sure this extraction was. Defaults to `1.0`
  (legitimate for an exact structured read).

An exact CSV read from a so-so source and a shaky LLM guess from an authoritative
source have very different score profiles, and KGIS keeps them distinguishable.

## Identity

Identity is structural and namespaced: `EntityRef{entity_type, namespace, key}`,
rendered `Label:namespace:key` (e.g. `Athlete:usssa:12345`) only at adapter
boundaries. The bare `Label:key` form is **forbidden** for cross-project use
because it hides the identifier authority (ADR-0008). Every canonical entity also
has an immutable internal identity ID that survives key corrections, merges, and
splits. `semantic_key` (`entity_semantic_key`) gives an entity's stable
`type/namespace/key` identity.

### Identity mode

`IdentityMode` (ADR-0014) is a per-consumer toggle on the ledger:
`AUTO_MERGE` (default) or `REJECT_ONLY`, the latter rejecting ambiguous identity
matches at `submit()` time rather than auto-linking them. An injected
`IdentityResolver` (a yes/no `is_ambiguous` oracle) decides ambiguity; full
entity resolution is deferred to a later plan.

## Determinism

A pipeline is deterministic when you inject a `FixedClock` and a
`DeterministicIdStrategy`: same input → byte-identical output. This is a property
of *configuration*, not of the harness — the defaults (`SystemClock`,
`RandomIdStrategy`) are non-deterministic on purpose. Combined with
content-addressed `candidate_id`s and the durable ledger, determinism gives you
idempotent, replayable, auditable runs.

## Ontology and two-tier validation

An `Ontology` declares the allowed entity types, relation types, and attributes.
Validation happens at **two tiers** (ADR-0015):

1. **Record-scoped** (`RecordValidator`) — is this raw row usable at all?
2. **Candidate-scoped** (`CandidateValidator`, e.g. `OntologyCandidateValidator`)
   — does the built candidate fit the ontology?

Record-scoped validation deliberately has no contract type; it is an in-engine
concern.
