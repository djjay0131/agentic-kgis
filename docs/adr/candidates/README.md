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

> Note: 0003-A and 0004 were split from a single joint candidate (originally
> `0003-contract-gaps-ulid-and-attributes`) per the PR #9 review — the ID
> helper is a small additive change, the attribute vocabulary needs
> registry/advisor review, so they are dispositioned separately.

## Status (2026-08-21) — backlog execution adds 0005–0009

The remaining KGIS v1 backlog was executed as six independently reviewed,
owner-ready PRs (see `llm/memory_bank/activeContext.md`). Those branches carry
five new ADR candidates and one amendment; they land in this directory when the
PRs merge. **The full open set awaiting owner promotion is 0001, 0002, 0003-A,
0004, 0005, 0006, 0007, 0008, 0009** — none has been actioned against
`kg_contracts`.

| Candidate | Weakness / decision | Arrives with |
|---|---|---|
| 0004 (amend) | `GraphDescriptor` attribute vocabulary — amended for the persistent registry + extension-attribute sidecar | PR #18 |
| 0005 | Open backend-id for the registry (backend identity not pinned to one store) | PR #18 |
| 0006 | Advisor recommendation outcomes + `INSUFFICIENT_INFORMATION` honest-null | PR #18 |
| 0007 | Fail-closed contract narrowings (`CommitResult`/`VersionChange`/`ConfidencePolicy` reject reasonless failure) | PR #20 |
| 0008 | Snapshot-version provenance for structured sync | PR #21 |
| 0009 | Model/extractor version fields for LLM extraction | PR #22 |

Promoting 0007 is gated on confirming no external/KGCS `GraphMutationStore`
adapter emits a reasonless `committed=False` (see owner decision (b) in
`activeContext.md`). This steward PR does **not** renumber or promote anything.
