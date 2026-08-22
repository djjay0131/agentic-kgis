# ADR candidate: `Recommendation` should carry four outcomes and an honest null

Status: Proposed (candidate)
Date: 2026-08-21
Raised by: Plan 7 — Registry / Advisor (kgis)

## Context

ADR-0005 (as amended 2026-07-10) and spec §8 upgraded the advisor's decision
model to **four outcome architectures** and preserved an honest treatment of
missing information. The frozen contract
`kg_contracts.registry.Recommendation`, however, still encodes only the
pre-amendment **binary**:

```python
action: Literal["extend", "create"]
```

Two gaps follow:

1. **Four outcomes, two actions.** The amended ADR-0005 / spec §8 four
   architectures are: (1) extend same logical+physical graph, (2) shared
   logical graph on separate physical partitions, (3) separate graphs behind a
   shared identity registry, (4) fully isolated graphs. The contract's
   `extend | create` cannot distinguish (1) from (2), nor (3) from (4) — a real
   architectural distinction (shared identity registry vs. full isolation)
   collapses on projection.

2. **No honest null.** When the automated factors cannot be scored (missing
   inputs), the honest answer is "insufficient information" (spec §8's
   honest-null discipline, mirroring ADR-0009 for `kg_eval`). The contract's
   `action` has no such member and `reasons` has `min_length=1`, so any
   contract `Recommendation` *must* assert extend or create — there is no way
   to represent "not enough information to say" without fabricating one.

## Decision (proposed)

Extend the contract `Recommendation` to represent the amended model directly:

- Replace the binary `action` with a four-member outcome enum (the four
  architectures), plus an explicit `INSUFFICIENT_INFORMATION` member — or add
  an `outcome` field beside `action` and relax the `reasons`/`action`
  coupling so the honest-null case is representable.
- Keep `factor_scores` scoped to `SCORED_FACTORS_V1` and the human `checklist`
  as-is; both already fit the amended model.

## Plan 7 workaround (implemented)

The advisor models the full amended decision in `kgis` as
`kgis.registry.AdvisorRecommendation` (a richer, frozen model with an `Outcome`
enum covering all four architectures plus `INSUFFICIENT_INFORMATION`), and
projects *down* to the contract via `.to_contract()`:

- `EXTEND_SAME_PHYSICAL`, `SHARED_LOGICAL_SEPARATE_PHYSICAL` → `action="extend"`
- `SEPARATE_SHARED_IDENTITY`, `FULLY_ISOLATED` → `action="create"`
- `INSUFFICIENT_INFORMATION` → **`None`** (deliberately: the contract cannot
  honestly represent it, so no fabricated extend/create is emitted)

The full four-way outcome and the honest null are preserved for the human in
the loop (who adjudicates every recommendation in v1 anyway) and recorded in
the decision corpus; only the lossy binary crosses the contract boundary. The
decision corpus stores the richer `AdvisorRecommendation`, so calibration data
is not degraded by the projection.

## Rationale

The amended ADR-0005 is Accepted; the frozen contract predates the amendment.
Routing still goes through `ConfidencePolicy` (the contract's design intent is
intact), but the *shape* of the advice the policy routes is now richer than the
frozen field can carry. A binary-only contract also forces the honest-null case
to masquerade as a real recommendation, which is exactly the failure mode
ADR-0009's honest-null policy exists to prevent.

## Consequences

### Positive

- The contract stops discarding a real architectural distinction on every
  recommendation.
- "Insufficient information" becomes representable end-to-end, not just inside
  kgis.

### Negative / Tradeoffs

- Widening `action` is a contract-visible change; a four-member enum is a
  larger surface than the binary and needs a compatibility class assigned
  (likely a minor/deliberate break if `action` is retyped, or
  BACKWARD_COMPATIBLE if an `outcome` field is added alongside).

### Risks

- Moderate: unlike candidates 0004/0005, this touches the *decision* surface
  consumers route on, so it wants explicit disposition before promotion. Until
  then the lossy projection is contained in `AdvisorRecommendation.to_contract`.

## Impacted Areas

- [x] Domain model
- [x] AI architecture
- [x] Implementation

## Related Documents

- `kg_contracts/registry.py` (`Recommendation`)
- `src/kgis/registry/models.py` (`Outcome`, `AdvisorRecommendation.to_contract`)
- `src/kgis/registry/advisor.py`
- ADR-0005 (amended 2026-07-10), spec §8
- ADR-0009 (kg_eval honest-null discipline)

## Supersedes

None.

## Superseded By

None.
