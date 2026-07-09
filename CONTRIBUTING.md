# Contributing to agentic-kgis

Status: Active
Last updated: 2026-07-09

This project follows [agentic-governance](https://github.com/djjay0131/agentic-governance)
(see `docs/governance-delta.md` for project specifics).

## Before You Start

1. `llm/memory_bank/activeContext.md`
2. `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` (design authority)
3. `docs/governance-delta.md`
4. agentic-governance: `docs/architecture-governance.md`,
   `docs/project-operating-system.md`

## Contribution Rules

- No direct commits to `main`. Issue → Branch → Draft PR → Review → Merge.
- Branch prefixes: `docs/`, `architecture/`, `feature/`, `research/`,
  `spike/`, `governance/`, ...
- ADRs for durable decisions (`docs/adr/`, use `0000-template.md`).
  System-level ADRs (spanning kgis + kgcs) live here.
- Update `llm/memory_bank/` when project context changes.
- AI agents: follow assigned scope, identify ADR candidates, never merge
  your own PR.

## Definition of Done

See agentic-governance `docs/definition-of-done.md`. For this repo
additionally: `pytest`, `ruff check src tests`, and `mypy src` green.
