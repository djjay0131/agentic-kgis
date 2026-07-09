# ADR-0003: Layered write path — inline deterministic gate + async probabilistic curation

Status: Accepted
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

## Supersedes

None.

## Superseded By

None.
