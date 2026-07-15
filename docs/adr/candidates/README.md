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
| [0003](0003-contract-gaps-ulid-and-attributes.md) | No public deterministic-ID helper on `kg_contracts`; `GraphDescriptor` declares no attribute vocabulary | Reimplemented Crockford encoder in `kgis.ids`; ontology attributes left unconstrained from a descriptor |
