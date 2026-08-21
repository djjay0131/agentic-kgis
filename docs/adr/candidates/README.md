# ADR candidates

Proposed ADRs surfaced during implementation, awaiting owner review and
promotion to a numbered, accepted ADR in `docs/adr/`.

Per `CONTRIBUTING.md` and the Sprint 1 brief: when implementation reveals an
architectural weakness, the implementer **documents it, files an ADR
candidate, and continues** — the implementer does not redesign the frozen
contracts. Everything here is a proposal for the architecture owner to accept,
amend, or reject; none of it has been actioned against `kg_contracts`.

These arose from building `kgis` (structured ingestion) against the merged
`kg_contracts` v2. None of them blocked Sprint 1 — each has an in-code
workaround that respects the current contract — but each names a seam that a
future plan will hit again.

| Candidate | Weakness | Sprint 1 workaround |
|---|---|---|
| [0001](0001-record-scoped-validation.md) | `ValidationDecision` is keyed on `candidate_id`, but records are rejected before candidates exist | Two-tier validation: record-tier `RecordValidation` (kgis) + candidate-tier `ValidationDecision` (contract) |
| [0002](0002-source-adapter-composition.md) | `Source.fetch()` yields `Candidate`, so the read/normalize/validate/build stages cannot sit upstream of a `Source` | Stages compose *inward*; `IngestPipeline` is the composition, `Source` conformance deferred |
| [0003-A](0003-a-public-deterministic-id-helper.md) | No public deterministic-ID helper on `kg_contracts` (the Crockford encoder is private) | Reimplemented Crockford encoder in `kgis.ids`, guarded by a drift test |
| [0004](0004-graph-descriptor-attribute-vocabulary.md) | `GraphDescriptor` declares node and edge types but no attribute vocabulary | Ontology attributes left unconstrained when read from a descriptor |
| [0008](0008-structured-snapshot-version-provenance.md) | No first-class field records a candidate's source snapshot version/cursor (structured sync) | Snapshot version encoded in `SourceCoordinates.locator` (toggleable), also exposed on the reader |

> Note: 0003-A and 0004 were split from a single joint candidate (originally
> `0003-contract-gaps-ulid-and-attributes`) per the PR #9 review — the ID
> helper is a small additive change, the attribute vocabulary needs
> registry/advisor review, so they are dispositioned separately.
