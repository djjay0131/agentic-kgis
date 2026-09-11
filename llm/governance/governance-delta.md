# Governance Delta: agentic-kgis

Status: Approved
Last updated: 2026-09-10 (canon location declared and the canon citations in
`CLAUDE.md` and the check command below rebound to it, per agentic-governance
v0.7.0; the governance plugin registered in `.claude/settings.json`. Earlier
the same day: migrated to the v0.5 two-plane layout: control-plane
content relocated from `docs/` to `llm/`, `## Repository Layout` declared, L0
allowlist and governance check command rebound to the declared paths. Prior
revision 2026-07-10: principles 2, 3, 4, 6 reworded; adopter ordering and
milestone labels remapped — per the approved disposition of external review
PR #1, Consequences §2.)
Governance: agentic-governance v0.7 (canonical `VERSION` 0.7.0)

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

`llm/specs/2026-07-09-kgis-kgcs-design.md` — the KGIS/KGCS
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

## Repository Layout

The paths this repo binds. The canon prescribes the shape (agentic-governance
`llm/governance/project-operating-system.md` §Repository Areas); this block
binds it here, so nothing downstream hardcodes a path. Only the slots this repo
actually uses are declared — an absent slot is not a violation, an undeclared
path in use is.

- Governance directory: `llm/governance/`
- ADR directory: `llm/governance/adr/`
- Spec directory: `llm/specs/`
- Sprints directory: `llm/sprints/`
- Plans directory: `llm/plans/`
- Memory-bank path: `llm/memory_bank/`
- Artifacts directory (the data plane): `docs/`

Not declared, because this repo has no content for them: constitution
directory (the canonical executive charters are used unmodified — see
§Constitution Adjustments) and features directory (backlog is tracked as
GitHub issues plus the plan sequence, not as feature-spec files).

`docs/` holds only data-plane material: `docs/kgis-adopter-notes.md`
(adopter-facing deliverable) and `docs/ai/` (externally-sourced design review
and its disposition). `docs/superpowers/` was deleted at migration per
agentic-governance
`llm/governance/adr/0001-llm-control-plane-docs-data-plane.md`; the routing
rule in `CLAUDE.md` and `AGENTS.md` prevents its recreation.

## Roadmap

Path: none (the plan sequence in spec v2 §11 and `llm/plans/` serve as the
roadmap; no checkbox roadmap document exists).

## Canon Location

Where the canonical `agentic-governance` repo lives, declared once. **This is
the only machine-specific path this repo is permitted to contain** — every
canon citation in `CLAUDE.md`, `AGENTS.md` and the check command below resolves
against it, so it changes in one place instead of a dozen.

- Canon checkout: `~/code/agentic-governance`
- Canon repository: `https://github.com/djjay0131/agentic-governance`
- Plugin registered: `repo` (`.claude/settings.json`)

Skills and agents running as the installed plugin resolve canon from
`${CLAUDE_PLUGIN_ROOT}/..` and need none of this; the declaration exists for
everything that is read *without* the plugin loaded — static instructions in
`CLAUDE.md`, and a check command run from a plain shell.

**Deliberately not verified by `--layout`.** A canon checkout is
environment-specific: CI fetches canon into a runner temp directory and has no
such path, so asserting it would fail every CI run for a repo whose local
declaration is perfectly correct. Verify it yourself when you change it —
`ls <canon checkout>/VERSION`.

## Governance Check Command

`node "${CLAUDE_PLUGIN_ROOT}/scripts/governance-checks.mjs" --layout` when the
governance plugin is loaded — preferred, because it needs no declared path.
From a plain shell, the same script — `plugin/scripts/governance-checks.mjs
--layout` — under the `Canon checkout` declared in §Canon Location above. The
checkout path is deliberately **not** expanded here: the machine-specific value
must appear in exactly one place per repo, and twenty lines below the
declaration is still a second place. Both forms reach canon through that single
declaration.

Run from this repo's root. `--layout` enforces the two-plane rule and asserts
that every path declared in §Repository Layout exists, on every run rather than
only at onboarding; it is additive to the default checks. No `--delta` or
`--adr-dir` override is needed: this repo's delta and ADR directory now sit at
the canonical defaults the script already looks for. Cited by L0 fast-track
condition 9 (agentic-governance `llm/governance/l0-fast-track.md`).

CI runs the same command in the `governance` job of `.github/workflows/ci.yml`,
against agentic-governance pinned by commit SHA.

## L0 Path Allowlist

The fenced block below is an instance of the canonical rule set in
agentic-governance `llm/governance/l0-fast-track.md` §Template Allowlist,
which also defines the block grammar and the diff shapes. The check command
parses **this** block, and reads it from `origin/main`, never from a PR's tree.
Every path is one declared in §Repository Layout above.

```l0-allowlist
# Instance of agentic-governance `llm/governance/l0-fast-track.md`
# §Template Allowlist — the source of this rule set and its grammar.
allow llm/memory_bank/** path-only
allow llm/governance/adr/README.md index-table-rows
allow llm/governance/adr/[0-9][0-9][0-9][0-9]-*.md status-line-only
allow llm/** link-target-only
allow docs/** link-target-only
deny src/**
deny scripts/**
deny .github/**
deny llm/governance/governance-delta.md
deny llm/governance/adr/0000-template.md
deny llm/specs/**
```

(No `checkbox-only` roadmap rule: §Roadmap declares none. `deny llm/specs/**`
carries forward the pre-migration `deny docs/superpowers/specs/**` — the
design-authority document is rank 2 of the design authority hierarchy and is
never an L0 edit. The delta itself is denied both by this block and by the
checker's hard-deny set.)

## Platform Enforcement Reality

- Branch protection on `main`: **available and configured** (re-verified via
  `gh api repos/djjay0131/agentic-kgis/branches/main/protection` on 2026-09-10;
  the repo is now public, which lifted the 2026-07-09 free-plan 403 recorded in
  the prior revision). Active rules: PRs required, force pushes blocked,
  branch deletion blocked, conversation resolution required, stale reviews
  dismissed. `required_approving_review_count` is 0 and `enforce_admins` is
  off, so review is still convention-enforced even though the PR flow is not.
- Required status checks: **available and configured** — `test` only, with
  `strict` (branch must be current with `main`). The `governance` job added at
  the v0.5 migration is NOT yet a required context; adding it is the next
  hardening step and needs an owner settings change, not a repo change.
- Token/identity model: all agent sessions authenticate with the owner's
  token — steward/auditor/architect are procedural roles, not distinct
  identities; independence is temporal/artifactual.
- Hardening path: taken — public visibility enabled branch protection and
  required checks. What remains: raise
  `required_approving_review_count` above 0, enable `enforce_admins`, and add
  `governance` to the required status checks. All three are owner settings
  changes.

## Steward Activation Status

Status: INACTIVE

Steward merge authority ships inert (agentic-governance
`llm/governance/l0-fast-track.md` §Per-Repo Activation). No activation ADR or PR
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
  HERE in `llm/governance/adr/`; kgcs keeps only kgcs-local ADRs.
- Adopters, in the five-phase sequence (spec v2 §11): Phase 0 — VTTSI
  repos (`vttsi-contracts`/`ts-kg`/`vttsi-evidence`) as reference reading
  for kg_contracts v2 (written fresh, no vendoring); Phase 1 — baseball-ai
  (greenfield); Phase 2 — traffic shadow integration (fixtures, no
  rewrite); Phase 3 — agentic-kg research-paper retrofit (migration acid
  test; requires the six migration-minimum tools first); Phase 4 —
  construction-ai (derivation/artifact modeling). `vttsi-contracts` is
  eventually superseded by `kg_contracts` re-exports.
