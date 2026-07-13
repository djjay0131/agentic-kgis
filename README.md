# agentic-kgis

Knowledge Graph Ingestion Service. Ships three packages (ADR-0002 as amended):

- **kg_contracts** — domain-neutral ports layer v2 (identity, candidates,
  evidence, bitemporal assertions, derivation, two-level store contracts,
  curation/ingestion/registry/policy contracts, contract test suites).
  No engine, LLM, or I/O code.
- **kgis** — ingestion implementations (structured sync + LLM extraction;
  Plan 4).
- **kg_eval** — evaluation harness with honest-null discipline (ADR-0009;
  Plan 6).

Design: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` (v2)
Companion repo: `agentic-kgcs` (curation service; depends on kg_contracts).

## Dev setup

    python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    .venv/bin/pytest
