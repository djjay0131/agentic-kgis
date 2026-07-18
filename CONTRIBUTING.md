# Contributing to agentic-kgis

Status: Active
Last updated: 2026-07-16

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

## Responsibilities

The workflow above has three roles. **A PR is the prerequisite for review,
so opening the draft PR is an author responsibility — it is what makes the
work reviewable.** It is never the reviewer's or the owner's job to open it.
(An AI agent acting as author carries the author responsibilities below.)

This section fixes *who does what*; it does not change *who may approve or
merge*. Approval authority stays with the reviewer, merge authority with the
owner.

### Author

- Implement the work.
- Commit the work.
- Push the branch.
- Open a draft PR.
- Keep the PR description current.
- Respond to review comments.
- Update the branch after review.

### Reviewer

- Review architecture.
- Review implementation.
- Approve or request changes.
- Verify governance compliance.

### Repository owner

- Merge approved semantic PRs.
- Decide when review is sufficient.
- Manage branch protection and repository settings.

## Definition of Done

See agentic-governance `docs/definition-of-done.md`. For this repo
additionally: `pytest`, `ruff check src tests`, and `mypy src` green.
