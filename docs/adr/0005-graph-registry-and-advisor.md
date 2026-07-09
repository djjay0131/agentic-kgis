# ADR-0005: Graph registry + extend-vs-new advisor, human-gated with automation path

Status: Accepted
Date: 2026-07-08

## Context

Nothing in the portfolio decides when new data warrants a new graph versus
extending an existing one. ADR-012 in the traffic constellation
(construction-platform) solved only the infrastructure layer (one shared
Spanner instance, many IAM-isolated graph databases), not the semantic
decision.

## Decision

A graph registry (one `GraphDescriptor` per graph: domain, backend,
ontology summary, policy, lineage) plus an advisor that scores incoming
data against registered graphs on four factors — domain overlap, ontology
compatibility, tenancy/access, lifecycle — and outputs a scored
`Recommendation` (extend X / create new) with reasons. In v1 every
recommendation routes to a human; the decision and outcome are recorded in
registry lineage. Automation later comes from raising confidence-policy
thresholds, not new code, calibrated on the recorded decision corpus.

## Rationale

The systems consuming KGIS/KGCS are learning systems; the human gate must
be removable by config. Registry lineage doubles as training data for that
transition. Auditable and low-risk now, automatable later.

## Alternatives Considered

### Fully automated decisions from day one

A wrong merge pollutes a graph and is expensive to unwind; no decision
corpus exists yet to calibrate thresholds.

### Documented rubric only (no code)

Zero implementation cost but nothing enforces or records decisions —
orphan decisions by construction.

## Consequences

### Positive

- Every graph's existence is explained by its lineage record.
- The same ConfidencePolicy mechanism serves entity-level and graph-level
  decisions.

### Negative / Tradeoffs

- A human is in the loop for every new-graph decision in v1 (low volume,
  acceptable).

### Risks

- Registry becomes stale if adopters bypass it; mitigated by KGIS
  consulting the registry in `plan`/`ingest` flows.

## Impacted Areas

- [x] Architecture
- [x] Data architecture
- [x] AI architecture
- [x] Implementation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §8
- construction-platform ADR-012 (infrastructure layer)

## Supersedes

None.

## Superseded By

None.
