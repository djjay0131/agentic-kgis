# ADR candidate: `Source` yields candidates, so ingestion stages compose inward

Status: Proposed (candidate)
Date: 2026-07-14
Raised by: Sprint 1 — Core Ingestion Engine (kgis)

## Context

The sprint brief describes the pipeline as a linear sequence of stages:

```
Source → Read → Normalize → Validate → Create Candidate(s) → CandidateSink
```

which reads as though `Source` sits at the *top* and the remaining stages run
downstream of it. But the contract's `Source` protocol (spec §5/§6,
`kg_contracts.ingestion`) is:

```python
class Source(Protocol):
    def fetch(self) -> Iterator[Candidate]: ...
```

`Source.fetch()` already yields fully-built, fully-scored `Candidate`s. So the
read/normalize/validate/build stages cannot run *after* a `Source` — by the
time anything is a `Candidate`, all of that work is already done. A `Source` is
not the pipeline's input stage; it is the pipeline's output contract, an
already-assembled candidate producer.

This is not a contradiction in the design — the spec's own module list resolves
it (`sources/base.py: SourceAdapter wrapping a kg_contracts.Source`). But it
does mean the intuitive reading of the diagram is inverted, and an implementer
who takes "Source → Read → …" literally will try to build the stages in the
wrong relationship.

## Decision (proposed)

Treat the named stages as composing **inward** into a `Source`, not as running
downstream of one:

```
RecordReader → Normalizer → RecordValidator → CandidateBuilder → CandidateValidator
└──────────────────────── together form a Source ────────────────────────┘
```

The stages are the *implementation* of `Source.fetch()`, not consumers of its
output. `IngestPipeline` (`src/kgis/pipeline.py`) is that composition: it holds
the injected stages and drives them to produce and submit candidates.

Sprint 1 deliberately does **not** yet expose a class that structurally
satisfies `kg_contracts.Source` (a `fetch() -> Iterator[Candidate]` facade over
the pipeline). It ships the composition as `IngestPipeline` (satisfying
`IngestJob`) instead, because the pipeline needs the report, the sink, and
dry-run — none of which fit through `fetch()`'s bare iterator. Adding a thin
`StructuredSource.fetch()` adapter that yields the pipeline's built candidates
is a small, additive follow-up when a consumer actually needs the `Source`
shape (e.g. feeding another `Source`-typed API).

## Rationale

Building the stages as independently injected ports — each testable alone — and
composing them in one orchestrator is what the sprint's "each stage
independently testable / stages composable" requirement asks for anyway. The
`Source`-returns-`Candidate` shape makes that the *only* correct structure, so
naming it explicitly protects the next implementer from the inverted reading.

Deferring the `fetch()` facade avoids inventing a second entry point (a `Source`
that discards the report) before there is a caller for it. The pipeline is the
honest surface: it can tell you what it read, rejected, suppressed, and
submitted; a bare `Iterator[Candidate]` cannot.

## Alternatives Considered

### Make `IngestPipeline` itself implement `Source`

`fetch()` would run the pipeline and yield the submitted candidates. But
`fetch()` returns an iterator with nowhere to put the `IngestReport`,
dry-run, or failure signalling — the whole reason the pipeline exists. It would
force the report out to a side channel and make the honest "10,000 emitted, 40
accepted" reporting impossible through that surface. Rejected for Sprint 1.

### Wrap each ingestion mode as a `Source` and drop the pipeline

Push everything behind `fetch()` and let a generic runner consume the iterator.
This is plausible for the *streaming* future (spec's batch-of-one → event), but
it discards per-stage reporting and dry-run today. Deferred with streaming.

## Consequences

### Positive

- The stage relationship is stated correctly; no implementer rebuilds it inverted.
- Stages stay independently injectable and testable.

### Negative / Tradeoffs

- Sprint 1 does not ship a `kg_contracts.Source`-typed object, so a consumer
  wanting the bare `fetch()` shape must wait for the (small) adapter.

### Risks

- A future `Source`-typed facade must reuse the pipeline's build path, not
  fork it, or the two could diverge. Mitigated by keeping candidate
  construction entirely in `builders.py`, which both would call.

## Impacted Areas

- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §5, §6 (module list)
- `src/kgis/pipeline.py`

## Supersedes

None.

## Superseded By

None.
