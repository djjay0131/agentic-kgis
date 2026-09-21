# Architecture Decision Records — KGIS/KGCS system

ADRs for durable decisions. System-level decisions (spanning agentic-kgis
and agentic-kgcs) live here; agentic-kgcs holds only kgcs-local ADRs.
Lifecycle: Proposed → Accepted → Superseded/Deprecated. Use
`0000-template.md`.

ADRs 0001–0005 back-fill the decisions made during the 2026-07-07/09
design brainstorm (recorded in the design spec) under the no-orphan-decisions
rule. ADRs 0006–0010 record the decisions from the approved disposition of
the external design review (PR #1, 2026-07-10); spec v2 is the companion
rewrite.

ADRs 0015–0023 were promoted from ADR candidates on 2026-08-22 (surfaced
during Sprint 1 and the remaining-backlog execution). Each records a decision
the shipped implementation already reflects through an in-code workaround that
respects the frozen `kg_contracts`; where an ADR proposes a future contract
change, that change remains deferred as the ADR states. The former candidate
files under `candidates/` are mapped to their ADR numbers in
`candidates/README.md`.

## Index

| ADR | Title | Status | Notes |
|---|---|---|---|
| [0001](0001-contract-plus-library-consumption.md) | Contract + library consumption model | Accepted |  |
| [0002](0002-contracts-live-in-agentic-kgis.md) | Contracts live in agentic-kgis as kg_contracts | Accepted | amended 2026-07-10: three packages — kg_contracts, kgis, kg_eval |
| [0003](0003-layered-write-path.md) | Layered write path: inline deterministic gate + async probabilistic curation | Accepted | superseded in part — see ADRs 0006, 0007, 0010 and ADR-0004 amendment |
| [0004](0004-dual-ingestion-modes.md) | Both ingestion modes in v1 (structured sync + LLM extraction) | Accepted | amended 2026-07-10: CandidateScores replaces single confidence |
| [0005](0005-graph-registry-and-advisor.md) | Graph registry + extend-vs-new advisor, human-gated with automation path | Accepted | amended 2026-07-10: 12 factors, four outcome architectures |
| [0006](0006-three-store-separation.md) | Three-store separation: candidate ledger / canonical graph / derived projections, with curation epochs | Accepted | superseded in part by ADR-0011 (the `GraphReadOptions.include_provisional` field) and by ADR-0025 (default REVOKED visibility) |
| [0007](0007-entity-resolution-architecture.md) | Entity-resolution architecture: calibrated pipeline, bounded LLM adviser, deterministic policy gate | Accepted |  |
| [0008](0008-identity-model.md) | Identity model: immutable internal identity IDs plus namespaced aliases | Accepted |  |
| [0009](0009-kg-eval-and-honest-null.md) | kg_eval package and the honest-null policy | Accepted |  |
| [0010](0010-write-path-mechanism.md) | Write-path mechanism: pure curation core, plan-applying executor, two-level store contracts | Accepted |  |
| [0011](0011-canonical-reads-are-canonical-only.md) | Canonical reads are canonical-only; ledger visibility is a separate read surface | Accepted | supersedes ADR-0006 in part |
| [0012](0012-candidate-ledger-persistence.md) | Candidate ledger persistence via stdlib sqlite3 | Accepted |  |
| [0013](0013-ledger-revoke-and-erasure.md) | Ledger revoke and erasure as row-governance, orthogonal to ProcessingState | Accepted |  |
| [0014](0014-identity-mode-and-consumer-profile.md) | Identity mode and consumer profile as the adoption-gating surface | Accepted |  |
| [0015](0015-record-scoped-validation.md) | Record-scoped validation has no contract type (two-tier validation) | Accepted | promoted from candidate 2026-08-22 |
| [0016](0016-source-adapter-composition.md) | `Source` yields candidates, so ingestion stages compose inward | Accepted | promoted from candidate 2026-08-22 |
| [0017](0017-public-deterministic-id-helper.md) | A public deterministic-ID helper on `kg_contracts` (kgis re-implements, drift-tested) | Accepted | promoted from candidate 2026-08-22 |
| [0018](0018-graph-descriptor-attribute-vocabulary.md) | `GraphDescriptor` should declare an attribute vocabulary (registry carries extension attributes) | Accepted | promoted from candidate 2026-08-22 |
| [0019](0019-open-backend-identifier.md) | `GraphDescriptor.backend` should be an open identifier | Accepted | promoted from candidate 2026-08-22 |
| [0020](0020-recommendation-outcomes-and-honest-null.md) | `Recommendation` should carry four outcomes and an honest null | Accepted | promoted from candidate 2026-08-22 |
| [0021](0021-fail-closed-contract-narrowings.md) | Three fail-closed narrowings of the frozen `kg_contracts` | Accepted | promoted from candidate 2026-08-22; owner to confirm no external `GraphMutationStore` emits a reasonless `committed=False` |
| [0022](0022-structured-snapshot-version-provenance.md) | A candidate has no first-class home for its source snapshot version | Accepted | promoted from candidate 2026-08-22 |
| [0023](0023-candidate-model-and-extractor-version-fields.md) | First-class model / extractor-version fields on the candidate envelope | Accepted | promoted from candidate 2026-08-22 |
| [0024](0024-identity-disposition-is-an-input-to-adjudication.md) | The identity disposition is an input to the adjudication gate | Accepted | issue #43 — fixes the `AUTO` deadlock |
| [0025](0025-revoke-identity-inverts-create-identity.md) | `REVOKE_IDENTITY` inverts `CREATE_IDENTITY`; REVOKED hidden from canonical reads by default | Accepted | issue #44 — supersedes ADR-0006 in part |
