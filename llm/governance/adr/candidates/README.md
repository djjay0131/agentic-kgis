# ADR candidates — all promoted

As of **2026-08-22**, every ADR candidate that was in this directory has been
reviewed by the architecture owner and **promoted to a numbered, accepted ADR**
in `llm/governance/adr/`. This directory is retained only for the mapping below
and for old links; a new architectural decision goes straight into
`llm/governance/adr/`, or is filed here first when it needs owner review before
acceptance.

| Former candidate | Promoted to |
|---|---|
| 0001 record-scoped-validation | [ADR-0015](../0015-record-scoped-validation.md) |
| 0002 source-adapter-composition | [ADR-0016](../0016-source-adapter-composition.md) |
| 0003-A public-deterministic-id-helper | [ADR-0017](../0017-public-deterministic-id-helper.md) |
| 0004 graph-descriptor-attribute-vocabulary | [ADR-0018](../0018-graph-descriptor-attribute-vocabulary.md) |
| 0005 open-backend-identifier | [ADR-0019](../0019-open-backend-identifier.md) |
| 0006 recommendation-outcomes-and-honest-null | [ADR-0020](../0020-recommendation-outcomes-and-honest-null.md) |
| 0007 fail-closed-contract-narrowings | [ADR-0021](../0021-fail-closed-contract-narrowings.md) |
| 0008 structured-snapshot-version-provenance | [ADR-0022](../0022-structured-snapshot-version-provenance.md) |
| 0009 candidate-model-and-extractor-version-fields | [ADR-0023](../0023-candidate-model-and-extractor-version-fields.md) |

None of these was actioned against the frozen `kg_contracts` at promotion time —
each accepted ADR records the in-code workaround that shipped and defers any
contract change. See each ADR body and the `llm/governance/adr/README.md` index
for the per-ADR status, including ADR-0021's pending external-adapter confirmation
(no external/KGCS `GraphMutationStore` may emit a reasonless `committed=False`).

> Historical note: 0003-A and 0004 (now ADR-0017 and ADR-0018) were split from
> a single joint candidate (`0003-contract-gaps-ulid-and-attributes`) per the
> PR #9 review.
