# Governance Delta: agentic-kgis

Status: Approved
Last updated: 2026-07-10 (principles 2, 3, 4, 6 reworded; adopter ordering
and milestone labels remapped — per the approved disposition of external
review PR #1, Consequences §2)
Governance: agentic-governance v0.2

This file localizes [agentic-governance](https://github.com/djjay0131/agentic-governance)
for this project.

## Mission

KGIS (Knowledge Graph Ingestion Service) is a reusable Python library that
ingests data into knowledge graphs for every project in this portfolio. It
ships `kg_contracts` (the domain-neutral ports layer), `kgis` (ingestion
implementations: deterministic structured sync + LLM extraction), and
`kg_eval` (the evaluation harness — ADR-0009). It is a library, not a
deployed service. It exists so no project reinvents ingestion again.
Together with KGCS it manages knowledge admission, identity, evidence, and
graph state — never domain reasoning.

## Design-Authority Document

`docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` — the KGIS/KGCS
design spec (covers this repo and `agentic-kgcs`).

## Project Principles

1. Contracts first: `kg_contracts` contains no engine, LLM, or I/O code;
   everything crosses a Protocol.
2. Canonical identity at every write boundary: immutable internal identity
   IDs plus namespaced external aliases (`EntityRef{entity_type, namespace,
   key}`); repair-or-reject, never silently coerce (agentic-tskg 0/18
   lesson; ADR-0008).
3. No application-facing surface can mutate canonical graph state; only
   KGCS executors apply mutation batches. The admission path is
   structurally unbypassable (ADR-0010).
4. Candidates, not writes: every ingestion mode emits typed candidates
   (proposal + `CandidateScores` + provenance + evidence refs). Provenance
   and evidence are never dropped.
5. Rejections are data, not exceptions; failures are reported, never
   silent (`IngestReport.incomplete`).
6. Idempotency everywhere: stable source coordinates + semantic keys make
   re-ingestion a safe no-op (content hashes are a supplementary signal
   only).
7. Engine-agnostic: no Cypher/GQL on contracts (ADR-010 lineage); Spanner,
   Neo4j, and memory backends are interchangeable adapters.
8. LLM-provider-agnostic: providers injected behind `CompletionClient`.
9. Confidence-routing is the automation path: human gates become automated
   by config (threshold) change, never by code change.

## Domain Review Questions

- Does this keep `kg_contracts` free of engine/LLM/I/O code?
- Does this preserve the unbypassable admission path (no application-facing
  canonical mutation; executors only)?
- Do new data paths carry provenance, evidence refs, and stable source
  coordinates + semantic keys?
- Is any new decision surface confidence-routed rather than hard-coded?
- Does this stay engine- and LLM-provider-agnostic?
- Would this change break an existing adopter (baseball-ai, agentic-kg)?

## Memory Bank

Path: `llm/memory_bank/`

## Roadmap

Path: none (the plan sequence in spec v2 §11 and `docs/superpowers/plans/`
serve as the roadmap; no checkbox roadmap document exists).

## Governance Check Command

`node ~/code/agentic-governance/governance/scripts/governance-checks.mjs`
(canonical script from the agentic-governance checkout; CI wiring pending.)

## L0 Path Allowlist

```l0-allowlist
allow llm/memory_bank/** path-only
allow docs/adr/README.md index-table-rows
allow docs/adr/[0-9][0-9][0-9][0-9]-*.md status-line-only
allow docs/** link-target-only
deny src/**
deny scripts/**
deny .github/**
deny docs/adr/0000-template.md
deny docs/superpowers/specs/**
```

## Platform Enforcement Reality

- Branch protection on `main`: unavailable (private repo, free plan —
  verified via `gh api` 403 on 2026-07-09). Merge discipline is
  convention-enforced.
- Required status checks: unavailable (same constraint).
- Token/identity model: all agent sessions authenticate with the owner's
  token — steward/auditor/architect are procedural roles, not distinct
  identities; independence is temporal/artifactual.
- Hardening path: GitHub Pro or public visibility would enable branch
  protection and required checks; blocked on owner's plan decision.

## Steward Activation Status

Status: INACTIVE

Steward merge authority ships inert (agentic-governance
`docs/l0-fast-track.md` §Per-Repo Activation). No activation ADR or PR
exists; all merges are human-owner-only.

## Milestone Labels

(remapped 2026-07-10 to the spec v2 §11 plan sequence)

- `phase-1-contracts` (bootstrap + kg_contracts v2)
- `phase-2-ledger-evidence` (candidate ledger + evidence registry)
- `phase-3-curation-core` (curation core + executor)
- `phase-4-ingestion` (structured sync + LLM extraction)
- `phase-5-entity-resolution` (blocking/features/matcher/golden sets; LLM
  adviser, cluster validation, Splink/dedupe benchmark)
- `phase-6-eval-review` (kg_eval + review API)
- `phase-7-registry` (registry + advisor)

## Special Labels

- `contracts` (changes to `kg_contracts` — highest review scrutiny)

## Constitution Adjustments

None.

## Related Repos

- `agentic-kgcs` — the curation service; depends only on `kg_contracts`
  from this repo. System-level ADRs (decisions spanning both repos) live
  HERE in `docs/adr/`; kgcs keeps only kgcs-local ADRs.
- Adopters, in the five-phase sequence (spec v2 §11): Phase 0 — VTTSI
  repos (`vttsi-contracts`/`ts-kg`/`vttsi-evidence`) as reference reading
  for kg_contracts v2 (written fresh, no vendoring); Phase 1 — baseball-ai
  (greenfield); Phase 2 — traffic shadow integration (fixtures, no
  rewrite); Phase 3 — agentic-kg research-paper retrofit (migration acid
  test; requires the six migration-minimum tools first); Phase 4 —
  construction-ai (derivation/artifact modeling). `vttsi-contracts` is
  eventually superseded by `kg_contracts` re-exports.
