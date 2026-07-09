# ADR-0004: Both ingestion modes in v1 (structured sync + LLM extraction)

Status: Accepted
Date: 2026-07-08

## Context

The portfolio has two proven, very different ingestion modes: deterministic
structured sync (ts-kg's idempotent Postgres→graph upsert) and unstructured
LLM extraction (agentic-kg's PDF → parallel typed-entity extraction).
Scoping v1 to one mode would leave the other project-local.

## Decision

KGIS v1 supports both modes, converging on one pipeline: both emit
`Candidate` streams (structured sync at confidence 1.0; extraction at
model-reported confidence) that flow through the KGCS gate identically.
Extractors are configuration (entity schema + prompt + model config), not
code.

## Rationale

Both modes are already proven in production/prototype code; generalizing
them under one Candidate seam is consolidation, not invention. First
adopters need both (baseball-ai: documents; agentic-kg retrofit: both).

## Alternatives Considered

### LLM extraction only in v1

Defers the cleanest, most testable path and blocks ts-kg-style adopters.

### Structured sync only in v1

Defers the hardest, most-repeated need across research projects.

## Consequences

### Positive

- One pipeline, one report format, one gate for both modes.

### Negative / Tradeoffs

- Larger v1 scope (accepted deliberately).

### Risks

- LLM-extraction quality varies by domain; mitigated by confidence routing
  and the review queue rather than by blocking v1.

## Impacted Areas

- [x] Architecture
- [x] AI architecture
- [x] Implementation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §2.2, §6

## Supersedes

None.

## Superseded By

None.
