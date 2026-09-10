# ADR-0009: kg_eval package and the honest-null policy

Status: Accepted
Date: 2026-07-10

## Context

The v1 design treated evaluation as project-level testing (§10 fixtures
and end-to-end scenarios) with no shared evaluation framework. External
review (PR #1) called evaluation "absolutely v1": extraction quality,
resolution quality, and graph usefulness all need measurable baselines
before LLM-enhanced pipelines earn default status. The portfolio already
proved the pattern in `vttsi-eval`: named interchangeable arms,
deterministic-vs-LLM comparison, ablations, agreement/correlation metrics,
bootstrap confidence intervals, structured reports, and explicit support
for a null conclusion when the LLM does not help.

## Decision

`agentic-kgis` ships a third package, `kg_eval` (alongside `kg_contracts`
and `kgis`; two-repo layout stands per ADR-0002 as amended), providing:

- **Named arms** — extraction: rules-only, LLM-only, rules+LLM, parser+CV,
  parser+CV+LLM; resolution: exact identifiers, probabilistic linkage,
  embedding-only, cross-encoder, probabilistic+LLM adjudication,
  multi-agent debate (experimental), human gold standard.
- **Metrics** — extraction (entity/relation P/R, attribute accuracy,
  evidence-span accuracy, hallucination rate, ontology-violation rate,
  source coverage, stability); resolution/curation (pairwise and cluster
  P/R, false-merge/false-split rates, abstention, calibration error,
  review yield/agreement, rollback frequency, queue age, time to
  canonicalization); graph outcomes (competency questions, retrieval
  recall, answer faithfulness, provenance completeness, multi-hop
  correctness, whether derived GraphRAG structures improve actual tasks).
- **Honest-null policy** — an LLM-enhanced pipeline never becomes a
  default merely because it produces more output; it must demonstrate
  improvement on a named metric without unacceptably worsening false
  merges, unsupported assertions, review workload, latency, cost, or
  reproducibility. A null result is valid and recorded.

`kg_eval` lands in plan milestone 6 and is a Phase 1 (baseball) deliverable
via golden-set construction and the Splink/dedupe matcher benchmark.

## Rationale

Calibrated ER (ADR-0007), the confidence-policy automation path
(ADR-0005), and the multi-agent-debate demotion are all only meaningful
against measured baselines — without kg_eval they are unfalsifiable
claims. Promoting the vttsi-eval discipline is consolidation of a proven
pattern, not new invention.

## Alternatives Considered

### Defer evaluation to post-v1

Fastest to first ingest, but thresholds, defaults, and the automation path
would be set by anecdote; retrofitting metrics after defaults exist
reverses the burden of proof.

### Per-project evaluation code (no shared package)

Each adopter measures what it likes; results are incomparable across
arms and adopters, and the honest-null discipline erodes to optional.

### Fold evaluation into kgcs

Curation would grade its own homework; eval must be able to compare KGIS
extraction arms and KGCS resolution arms independently of both.

## Consequences

### Positive

- Every "the LLM helps here" claim is testable and reversible.
- Golden sets and cost matrices get a maintained home and format.
- Multi-agent debate and GraphRAG indexing must earn adoption with data.

### Negative / Tradeoffs

- v1 scope grows (third package, golden-set labeling as human labor).
- Contract changes now ride a release train shared by three packages.

### Risks

- Golden sets go stale as domains evolve — mitigated by per-milestone
  ingest reporting feeding eval and by re-labeling being scheduled work,
  not emergency work.

## Impacted Areas

- [x] Product
- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §10.1: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Feedback: `docs/ai/chatgpt-feedback-2026-07.md` (Response 1 §5
  "Evaluation framework", Response 2 §5)
- Disposition: `docs/ai/chatgpt-feedback-disposition.md` (A13, R2; owner
  confirmation 2026-07-10: kg_eval is a third package in agentic-kgis)

## Related Issues / PRs

- PR #1 (external design review capture + disposition)

## Supersedes

None.

## Superseded By

None.
