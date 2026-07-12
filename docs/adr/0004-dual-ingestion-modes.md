# ADR-0004: Both ingestion modes in v1 (structured sync + LLM extraction)

Status: Accepted (amended 2026-07-10)
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

## Amended 2026-07-10

Per the approved disposition of external review PR #1 (A2, A8):

- **`CandidateScores` replaces the single `confidence` float.** Both modes
  emit candidates carrying the score set `{extraction_confidence,
  identity_confidence, assertion_confidence, source_reliability,
  corroboration_score, policy_risk}`. A single confidence conflates
  "did we read the source correctly" with "is the fact true" — an exact
  database import is not proof the database's fact is correct.
- The Decision's clause "structured sync at confidence 1.0" is dead.
  Structured sync records high extraction confidence and method
  determinism (`Derivation`), while source reliability and authority are
  scored separately. Consequently this amendment supersedes ADR-0003's
  entry-policy implication in the clause "sub-1.0-confidence entities land
  `PROVISIONAL`" — i.e., that confidence-1.0 structured syncs enter
  `ACTIVE` directly. Entry policy now evaluates the score set (extraction
  certainty vs. source reliability vs. authority); deterministic sync is
  no longer auto-`ACTIVE`.
- `Candidate` is now a discriminated union of nine variants sharing a
  `CandidateEnvelope` (spec v2 §5.2); both modes still converge on the one
  candidate seam, submitted via `CandidateSink` (ADR-0010) rather than "the
  KGCS gate" wrapper. The dual-mode decision itself is unchanged.

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §2.2, §5.2, §5.5, §6 (v2)
- `docs/ai/chatgpt-feedback-2026-07.md` (Response 2 §3, §8)
- `docs/ai/chatgpt-feedback-disposition.md` (A2, A8; Consequences §3)
- PR #1 (external design review capture + disposition)

## Supersedes

ADR-0003, in part (via the 2026-07-10 amendment) — the entry-policy
implication of the clause "sub-1.0-confidence entities land
`PROVISIONAL`": that confidence-1.0 structured syncs enter `ACTIVE`.
Entry policy now uses the `CandidateScores` set.

## Superseded By

None.
