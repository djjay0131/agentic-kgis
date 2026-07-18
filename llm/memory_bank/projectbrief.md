# Project Brief — agentic-kgis

KGIS (Knowledge Graph Ingestion Service) is a reusable Python library that
ingests data into knowledge graphs for every project in this portfolio.
It ships two packages: `kg_contracts` (domain-neutral ports: schemas,
GraphStore protocol, ingestion/curation/registry contracts) and `kgis`
(ingestion implementations: deterministic structured sync + LLM extraction).

Non-negotiables: KGIS never writes to a raw GraphStore — always through
KGCS's CuratedGraphStore. Candidates (not writes) are the output of
ingestion. Contracts contain no engine, LLM, or I/O code.

Authority: docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md (spec v2)
Governance: agentic-governance v0.2 (docs/governance-delta.md) — levels L0–L3,
workflow-selection; steward INACTIVE. Workflow: Issue → Branch → Draft PR →
Review → Merge; no direct commits to main.
