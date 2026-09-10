# ADR-0003: Layered write path — inline deterministic gate + async probabilistic curation

Status: Accepted (superseded in part — see ADRs 0006, 0007, 0010 and ADR-0004 amendment)
Date: 2026-07-08

## Context

Curation steps differ in nature: canonical-ID/ontology/versioning checks
are deterministic and cheap; entity resolution, LLM disambiguation, and
human review are probabilistic, expensive, or slow. A single write path
cannot treat them uniformly without either blocking ingestion or letting
uncurated data land.

## Decision

Split curation by nature. Deterministic gates run synchronously and
unbypassably in a `CuratedGraphStore` wrapper (canonical-ID
repair-or-reject, data-backed ontology validation, versioned
provenance-stamped writes). Probabilistic curation runs asynchronously:
sub-1.0-confidence entities land `PROVISIONAL` and are promoted/merged by
confidence-routed resolution (auto / LLM evaluator / consensus / human
queue). Lifecycle: `PROVISIONAL → ACTIVE → SUPERSEDED/REVOKED`.

## Rationale

Matches how agentic-kg (the most mature KG) already behaves; the
provisional→promoted seam is exactly where human gating becomes automation
via threshold config. Construction-ai's versioning states extend naturally
with `PROVISIONAL`.

## Alternatives Considered

### Strict synchronous gateway (all curation inline)

Strongest invariant but ingestion blocks on human review SLAs (up to days).

### Post-hoc curation (write freely, sweep later)

Easiest retrofit but permits uncurated data into graphs — the exact failure
mode of the agentic-tskg 0/18 post-mortem.

## Consequences

### Positive

- Ingestion latency stays bounded by deterministic checks only.
- Consumers can filter by CurationStatus.
- Every merge reversible via version chains.

### Negative / Tradeoffs

- Consumers must understand PROVISIONAL data exists.
- Two moving parts (gate + plane) instead of one.

### Risks

- A stalled curation plane accumulates PROVISIONAL backlog — needs
  monitoring in adopters.

## Impacted Areas

- [x] Architecture
- [x] Data architecture
- [x] AI architecture
- [x] Implementation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §3, §7
- `docs/ai/chatgpt-feedback-disposition.md` (A1, A5, A6, A8, A9, A10; Consequences §3)

## Supersedes

None.

## Superseded By

Superseded in part on 2026-07-10, per the approved disposition of external
review PR #1. The core principle survives: deterministic admission runs
synchronously; probabilistic curation runs asynchronously; the gate is
unbypassable. The following clauses of the Decision are dead, each routed
to its superseding ADR:

- "Deterministic gates run synchronously and unbypassably in a
  `CuratedGraphStore` wrapper" → **ADR-0010** (pure curation core →
  CurationPlan → executor; two-level store contracts; the wrapper
  mechanism is replaced, the gate property strengthened).
- "sub-1.0-confidence entities land `PROVISIONAL`" — insofar as
  provisional entities live in the main graph → **ADR-0006** (three-store
  separation: uncertain candidates live in the candidate ledger, never as
  ordinary graph entities; the implied converse, confidence-1.0 structured
  syncs entering `ACTIVE` directly, is superseded by the **ADR-0004
  amendment**: entry policy evaluates the `CandidateScores` set, and
  method determinism is not factual confidence).
- "promoted/merged by confidence-routed resolution (auto / LLM evaluator /
  consensus / human queue)" — insofar as embedding-similarity confidence
  bands are the decision mechanism and multi-agent consensus is a standard
  tier → **ADR-0007** (calibrated ER pipeline, bounded LLM adviser,
  deterministic policy gate; debate demoted to a `kg_eval` arm).
- "Lifecycle: `PROVISIONAL → ACTIVE → SUPERSEDED/REVOKED`" — as a
  whole-node status carrying all uncertainty → **ADR-0006** and spec v2
  §5.2/§7.2 (curation status attaches at assertion level; candidate
  processing states are a separate machine).
