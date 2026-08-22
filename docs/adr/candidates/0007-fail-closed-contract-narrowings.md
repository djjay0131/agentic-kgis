# ADR candidate: three fail-closed narrowings of the frozen `kg_contracts`

Status: Proposed (candidate)
Date: 2026-08-21
Raised by: Contracts hygiene — Issue #8 safe subset (PR #20)

> Numbering note: this candidate is `0007` to avoid colliding with `0005`/`0006`,
> which are claimed by the parallel registry/advisor work (PR #18). It is
> unrelated to those.

## Context

Issue #8 (owner-requested, from the Plan 1 v2 whole-branch review) asked for
several fail-closed validation tightenings on `kg_contracts` v2. Three of them
are not pure additions — they **narrow the accepted domain** of models in the
frozen, cross-repo-consumed `kg_contracts`. A value that constructed
successfully before now raises `ValidationError`. Per the repo discipline
(document weaknesses / narrowings, do not silently redesign the frozen
contract), each is filed here for the owner to confirm before promotion, even
though the implementations are already in PR #20 as reviewed, owner-requested
hardening.

The three narrowings:

- **(a) `CommitResult` requires a reason on non-commit** (`stores.py`): a
  `committed=False` result must now carry `error` **or** a non-empty
  `failed_preconditions`. A reasonless non-commit is rejected at construction.
- **(b) `ConfidencePolicy` thresholds bounded to `[0, 1]`** (`policy.py`):
  `auto_min_extraction`, `auto_min_source_reliability`, `auto_max_policy_risk`,
  `assess_min_extraction`, and `auto_min_identity_confidence` gain `ge=0/le=1`
  (`human_min_policy_risk` already had them).
- **(c) `VersionChange.from_version` `min_length=1`** (`versioning.py`): the
  empty string is rejected rather than slipping past the `from_version is None`
  ⇒ `BACKWARD_COMPATIBLE` introduction rule while naming no prior version.

## Decision (proposed)

Accept the three narrowings as-is. They are conservative, fail-closed, and each
rejects a state no in-repo producer emits.

## Rationale

- **(c)** is a pure loophole/bug fix: `""` is never a legitimate version, and
  the introduction rule already intended `None` to be the only "no prior
  version" signal. There is no reasonable caller to break.
- **(b)** rejects a semantically meaningless configuration:
  `CandidateScores` fields are already bounded `[0, 1]`, so a `ConfidencePolicy`
  threshold outside `[0, 1]` can never discriminate anything — it is a config
  error, now caught at construction rather than silently distorting routing.
- **(a)** rejects a silent failure: a `committed=False` with neither an error
  nor a failed precondition gives the caller nothing to act on — neither a
  stale snapshot to re-evaluate nor an error to surface. Every in-tree
  `GraphMutationStore` (the memory adapter) already always populates one.

## External-adopter caveat (why this is a candidate, not a silent change)

`CommitResult` (a) is the **output type of any `GraphMutationStore` adapter**,
including KGCS and other external/out-of-tree implementations. Such an adapter
could today legitimately return a reasonless `committed=False` (e.g. a no-op or
an idempotent re-apply that neither errored nor failed a precondition); under
this narrowing that return now raises at construction inside the adapter.

**Owner action before promotion:** confirm that no KGCS or external
`GraphMutationStore` implementation relies on returning a reasonless
`committed=False`. If any does, either (i) require it to populate `error`
(e.g. `"no-op"`) — the recommended fix — or (ii) relax (a) to a warning. (b) and
(c) carry no comparable external-adopter risk: `ConfidencePolicy` and
`VersionChange` are constructed from config/authoring inputs, not produced by
external adapters.

## Consequences

### Positive

- Silent-failure and degenerate-config states become unrepresentable at
  construction, closer to the source.
- `(c)` removes a genuine correctness loophole in the introduction rule.

### Negative / Tradeoffs

- `(a)` is a behavioral narrowing on a cross-repo output type; an external
  adapter emitting a reasonless non-commit would begin to raise. Mitigated by
  the owner confirmation above and by the trivial `error="..."` fix.

## Status of the code

Implemented in PR #20 (`feat/contracts-hygiene`) as owner-requested Issue #8
hardening, with tests pinning each narrowing. This candidate records the
narrowing for owner sign-off; it does not gate the PR.
