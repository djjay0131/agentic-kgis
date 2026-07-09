# Governance Delta: agentic-kgis

Status: Approved
Last updated: 2026-07-09
Governance: agentic-governance v0.1

This file localizes [agentic-governance](https://github.com/djjay0131/agentic-governance)
for this project.

## Mission

KGIS (Knowledge Graph Ingestion Service) is a reusable Python library that
ingests data into knowledge graphs for every project in this portfolio. It
ships `kg_contracts` (the domain-neutral ports layer) and `kgis` (ingestion
implementations: deterministic structured sync + LLM extraction). It is a
library, not a deployed service. It exists so no project reinvents
ingestion again.

## Design-Authority Document

`docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` — the KGIS/KGCS
design spec (covers this repo and `agentic-kgcs`).

## Project Principles

1. Contracts first: `kg_contracts` contains no engine, LLM, or I/O code;
   everything crosses a Protocol.
2. Canonical `Label:key` IDs at every write boundary; repair-or-reject,
   never silently coerce (agentic-tskg 0/18 lesson).
3. KGIS never writes to a raw GraphStore — only through KGCS's
   CuratedGraphStore. The gate is structurally unbypassable.
4. Candidates, not writes: every ingestion mode emits `Candidate`
   (proposal + confidence + Provenance). Provenance is never dropped.
5. Rejections are data, not exceptions; failures are reported, never
   silent (`IngestReport.incomplete`).
6. Idempotency everywhere: content hashes make re-ingestion a safe no-op.
7. Engine-agnostic: no Cypher/GQL on contracts (ADR-010 lineage); Spanner,
   Neo4j, and memory backends are interchangeable adapters.
8. LLM-provider-agnostic: providers injected behind `CompletionClient`.
9. Confidence-routing is the automation path: human gates become automated
   by config (threshold) change, never by code change.

## Domain Review Questions

- Does this keep `kg_contracts` free of engine/LLM/I/O code?
- Does this preserve the unbypassable gate (no raw GraphStore writes)?
- Do new data paths carry Provenance and a content hash?
- Is any new decision surface confidence-routed rather than hard-coded?
- Does this stay engine- and LLM-provider-agnostic?
- Would this change break an existing adopter (baseball-ai, agentic-kg)?

## Memory Bank

Layout: `llm/memory_bank/`

## Milestone Labels

- `phase-1-contracts`
- `phase-2-gate`
- `phase-3-ingestion`
- `phase-4-curation-plane`
- `phase-5-registry`

## Special Labels

- `contracts` (changes to `kg_contracts` — highest review scrutiny)

## Constitution Adjustments

None.

## Related Repos

- `agentic-kgcs` — the curation service; depends only on `kg_contracts`
  from this repo. System-level ADRs (decisions spanning both repos) live
  HERE in `docs/adr/`; kgcs keeps only kgcs-local ADRs.
- Adopters: baseball-ai (first), agentic-kg (second), then ts-kg /
  construction-ai. `vttsi-contracts` is eventually superseded by
  `kg_contracts` re-exports.
