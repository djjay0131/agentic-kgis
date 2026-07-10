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

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-contract-plus-library-consumption.md) | Contract + library consumption model | Accepted |
| [0002](0002-contracts-live-in-agentic-kgis.md) | Contracts live in agentic-kgis as kg_contracts | Accepted (amended 2026-07-10: three packages — kg_contracts, kgis, kg_eval) |
| [0003](0003-layered-write-path.md) | Layered write path: inline deterministic gate + async probabilistic curation | Accepted (superseded in part — see ADRs 0006, 0007, 0010 and ADR-0004 amendment) |
| [0004](0004-dual-ingestion-modes.md) | Both ingestion modes in v1 (structured sync + LLM extraction) | Accepted (amended 2026-07-10: CandidateScores replaces single confidence) |
| [0005](0005-graph-registry-and-advisor.md) | Graph registry + extend-vs-new advisor, human-gated with automation path | Accepted (amended 2026-07-10: 12 factors, four outcome architectures) |
| [0006](0006-three-store-separation.md) | Three-store separation: candidate ledger / canonical graph / derived projections, with curation epochs | Accepted |
| [0007](0007-entity-resolution-architecture.md) | Entity-resolution architecture: calibrated pipeline, bounded LLM adviser, deterministic policy gate | Accepted |
| [0008](0008-identity-model.md) | Identity model: immutable internal identity IDs plus namespaced aliases | Accepted |
| [0009](0009-kg-eval-and-honest-null.md) | kg_eval package and the honest-null policy | Accepted |
| [0010](0010-write-path-mechanism.md) | Write-path mechanism: pure curation core, plan-applying executor, two-level store contracts | Accepted |
