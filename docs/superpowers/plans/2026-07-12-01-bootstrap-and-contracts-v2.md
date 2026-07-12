# KGIS/KGCS Plan 1 v2: Bootstrap Completion + kg_contracts v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the bootstrap of both repos (packaging, src layout, quality gates, CI — the memory banks and governance docs already exist) and deliver a complete, tested `kg_contracts` v2 package per spec v2 §5: namespaced identity, the nine-variant typed candidate union with `CandidateEnvelope` + `CandidateScores`, first-class evidence, bitemporal assertions, derivation lineage, two-level store contracts (`CandidateSink` / `GraphMutationStore`), split reader/writer protocols with capability declarations, curation/ingestion/registry/policy/security/versioning contracts, in-memory reference adapters, and reusable contract test suites.

**Supersedes:** `docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md` (Plan 1 v1 — written against spec v1; obsoleted by the approved disposition of external review PR #1, `docs/ai/chatgpt-feedback-disposition.md`).

**Architecture:** `agentic-kgis` ships **three** packages from one distribution (ADR-0002 as amended): `kg_contracts` (pure ports layer — Pydantic models and `typing.Protocol` interfaces; no engine/LLM/network code), `kgis` (ingestion implementations, Plan 4), and `kg_eval` (evaluation harness, Plan 6; skeleton only here). `agentic-kgcs` depends only on `kg_contracts`. In-memory reference adapters and the contract test suites live under `kg_contracts.testing` so both repos test against them with no extra dependencies.

**Tech Stack:** Python ≥3.11, Pydantic v2, pytest, ruff, mypy --strict, hatchling build backend.

**Spec (design authority):** `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` **v2** — §5 (contracts) is primary; §3.2–3.3 (three-store separation, epochs), §10.2 (contract test suites) also bind. Disposition: `docs/ai/chatgpt-feedback-disposition.md` (items A2–A17, D2). Constraining ADRs: 0006 (three-store separation, no PROVISIONAL nodes in canonical graph, curation epochs), 0007 (ER architecture), 0008 (identity model), 0009 (kg_eval + honest null), 0010 (write-path mechanism, two-level store contracts).

**Phase-0 reference reading (lessons, not code):** `kg_contracts` v2 is written **fresh**; `vttsi-contracts`, `vttsi-evidence`, and `ts-kg` are reference reading only — no vendoring (owner decision 2026-07-10, spec §11 Phase 0). Lessons already harvested into this plan are called out inline as *Phase-0 lesson* notes.

**Plan sequence** (this is Plan 1 of 7 — spec v2 §11; later plans are written after their predecessors complete):
1. **This plan** — bootstrap completion + `kg_contracts` v2
2. Candidate ledger + evidence registry
3. Curation core + executor
4. Ingestion modes (structured sync + LLM extraction)
5. Entity resolution (5a blocking/features/calibrated matcher + golden sets; 5b LLM adviser, cluster validation, Splink/dedupe benchmark)
6. `kg_eval` + review API
7. Registry + advisor

## Global Constraints

- Python `>=3.11`; sole runtime dependency of `kg_contracts` is `pydantic>=2.0`
- `kg_contracts` contains NO engine code, NO LLM code, NO network/file I/O (spec §5); in-memory adapters under `kg_contracts.testing` are allowed (pure dicts)
- **Identity (ADR-0008):** every canonical entity has an immutable internal identity ID (`kg://<graph-id>/identity/<ulid>`) plus namespaced external aliases `EntityRef{entity_type, namespace, key}` rendered `Label:namespace:key` only at adapter boundaries. Bare `Label:key` is deprecated for cross-project use and MUST NOT appear in any v2 contract. Entity types PascalCase `^[A-Z][A-Za-z0-9]*$`; relation types UPPER_SNAKE `^[A-Z][A-Z0-9_]*$` (ts-kg lineage, format upgraded)
- **Candidates (A2/D2):** `Candidate` is a discriminated union of ALL NINE variants (entity, relation, attribute-assertion, observation, derived-assertion, artifact, plan, ontology, identity-link) on discriminator `candidate_kind`. v1 IMPLEMENTS (full validation + tests) entity / relation / attribute-assertion / artifact; the other five are defined spec-level with placeholder validation and explicit `SPEC-LEVEL` docstrings
- **A single `confidence` float is banned.** All scoring uses `CandidateScores` (extraction_confidence, identity_confidence, assertion_confidence, source_reliability, corroboration_score, policy_risk)
- **Evidence is first-class** (vttsi-evidence lineage): availability is explicit `present | absent | error`; evidence is never silently dropped
- **Bitemporal assertions:** every assertion contract carries valid time AND transaction time (spec §5.4); curation status attaches at assertion level, not only whole-node level
- **Store contracts (ADR-0010):** `CandidateSink` is the ONLY application-facing write surface; `GraphMutationStore` is executor-only. No `upsert_nodes`-style raw writes on any consumer-facing protocol. Read/write protocols are split; adapters declare capabilities. No Cypher/GQL on core contracts
- **No PROVISIONAL nodes in the canonical graph (ADR-0006):** candidate/processing states live on candidates in the ledger, not as a canonical-graph node status; `CurationStatus` in v2 applies to canonical assertions/entities as ACTIVE/SUPERSEDED/REVOKED lifecycle only
- **Idempotency:** stable source coordinates + semantic keys; content hashes are a supplementary signal only (spec §5.8)
- All contract models are frozen (immutable) Pydantic models unless a task explicitly says otherwise (accumulators)
- TDD for every behavior-bearing module; run commands from the repo root; venv at `.venv`
- Commit after every task (frequent commits)

## Task Overview

| # | Task | Module |
|---|------|--------|
| 1 | agentic-kgis packaging (three packages) | pyproject, src layout |
| 2 | agentic-kgcs packaging completion | sibling repo |
| 3 | Security/policy stub + universal trace ID | `security.py` |
| 4 | Identity model | `identity.py` |
| 5 | Evidence contract | `evidence.py` |
| 6 | Derivation lineage | `derivation.py` |
| 7 | Versioning + compatibility classes | `versioning.py` |
| 8 | Bitemporal assertions + conflict representation | `assertions.py` |
| 9 | CandidateScores + CandidateEnvelope | `candidates.py` |
| 10 | Implemented candidate variants (4) | `candidates.py` |
| 11 | Spec-level variants (5) + discriminated union | `candidates.py` |
| 12 | Score-set-aware ConfidencePolicy | `policy.py` |
| 13 | Reader/writer protocols + capabilities | `stores.py` |
| 14 | CandidateSink + GraphMutationStore | `stores.py` |
| 15 | Curation operations, decisions, plan, states, review | `curation.py` |
| 16 | Ingestion contracts | `ingestion.py` |
| 17 | Registry contracts | `registry.py` |
| 18 | Memory adapters + contract test suites | `testing/` |
| 19 | Public API, quality gate, CI, cross-repo verification | `__init__.py`, CI |

---

(Tasks 1–19 detailed below.)
