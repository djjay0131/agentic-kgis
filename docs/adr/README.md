# Architecture Decision Records — KGIS/KGCS system

ADRs for durable decisions. System-level decisions (spanning agentic-kgis
and agentic-kgcs) live here; agentic-kgcs holds only kgcs-local ADRs.
Lifecycle: Proposed → Accepted → Superseded/Deprecated. Use
`0000-template.md`.

ADRs 0001–0005 back-fill the decisions made during the 2026-07-07/09
design brainstorm (recorded in the design spec) under the no-orphan-decisions
rule.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-contract-plus-library-consumption.md) | Contract + library consumption model | Accepted |
| [0002](0002-contracts-live-in-agentic-kgis.md) | Contracts live in agentic-kgis as kg_contracts | Accepted |
| [0003](0003-layered-write-path.md) | Layered write path: inline deterministic gate + async probabilistic curation | Accepted |
| [0004](0004-dual-ingestion-modes.md) | Both ingestion modes in v1 (structured sync + LLM extraction) | Accepted |
| [0005](0005-graph-registry-and-advisor.md) | Graph registry + extend-vs-new advisor, human-gated with automation path | Accepted |
