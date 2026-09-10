# ADR-0007: Entity-resolution architecture — calibrated pipeline with a bounded LLM adviser and a deterministic policy gate

Status: Accepted
Date: 2026-07-10

## Context

The v1 design resolved entities by embedding-similarity search against
same-type entities with fixed per-type thresholds (~0.90 concepts, ~0.95
named things), routing the uncertain middle band to a single LLM evaluator
or a multi-agent Maker/Hater/Arbiter consensus tier. External review
(PR #1) showed cosine thresholds are not portable across embedding models,
entity types, languages, text lengths, or candidate-pool difficulty — 0.95
between two short organization names means something very different from
0.95 between two research-problem descriptions — and that multi-agent
debate adds cost, latency, correlated errors (similar models and evidence
are not independent votes), calibration difficulty, and audit complexity.
The VTTSI repos already demonstrate the sound deterministic/LLM
relationship: deterministic baseline, bounded LLM adjustment with cited
evidence, clamp, fallback.

## Decision

Replace the embedding-threshold funnel with a staged pipeline:

1. Normalization + deterministic identity rules (DOI/ORCID/VIN/source IDs,
   canonical name variants, crosswalks) — explainable evidence, never
   silent merges.
2. Multi-channel blocking (lexical, phonetic, identifier, geo/temporal,
   source keys, embedding ANN, graph-neighborhood overlap) — embeddings
   are one recall channel.
3. Typed pairwise features, including **mutually exclusive evidence**
   (e.g. simultaneous appearances on different teams).
4. Calibrated matcher (probabilistic linkage / gradient-boosted / logistic
   / cross-encoder / rules+weights) producing calibrated probabilities.
5. Cluster validation — transitive closure is wrong when A~B, B~C, A
   contradicts C; cluster-level constraints re-score membership.
6. Deterministic policy gate routing on calibrated error risk and
   consequence class: auto-link / retain separately / human review /
   gather evidence / abstain.

The LLM is a **bounded, evidence-citing adviser**, never the merge
authority: it returns `ResolutionAssessment{recommendation: same |
different | insufficient_evidence, evidence_ids, contradictions,
rationale, confidence}` as one input to the gate, with deterministic
fallback on any failure (vttsi-llm-score discipline). Thresholds are
learned per graph / entity type / source pair / matcher version /
consequence class from golden sets and an explicit cost matrix (false
merges cost more than false splits). Every decision logs the full score
vector and model versions. Multi-agent debate is demoted to an
experimental `kg_eval` arm. Splink and dedupe are benchmarked as
buy-before-build matcher baselines during the baseball PoC.

## Rationale

This is the established record-linkage architecture (Splink, Senzing) and
mirrors the portfolio's proven clamp-and-fallback pattern. It makes
resolution explainable, calibratable, and reproducible; raw thresholds
picked "because 0.90 and 0.95 sound conservative" are none of those.
Confidence routing as a *policy* concept survives (adjudication routing,
graph advisor); the consensus tier does not ship.

## Alternatives Considered

### Embedding-threshold funnel with confidence bands (v1 design)

Cheap and simple, matches agentic-kg's prototype, but thresholds are not
portable, decisions are unexplainable, and the middle band grows with
domain difficulty.

### LLM as the merge adjudicator

Flexible for textual reasoning, but ungrounded authority: unbounded
errors, poor calibration, expensive, and irreproducible as models change.
Kept as a bounded adviser only.

### Multi-agent debate (Maker/Hater/Arbiter) as a standard tier

Not independent votes; adds cost, latency, and audit complexity without
demonstrated accuracy gains. Retained only as a `kg_eval` experiment that
must beat the calibrated baseline on named metrics.

### Adopt Splink or dedupe wholesale as the resolution layer

Strong baselines for structured records, but neither covers evidence
citation, cluster policy gates, LLM advisement, or our contracts; they are
benchmarked as the stage-4 matcher, not the architecture.

## Consequences

### Positive

- Every merge decision is explainable, reproducible (full score vector +
  versions), and tunable per consequence class.
- Recall and precision are separately controllable (blocking vs. gate).
- Cluster validation prevents transitive-closure false merges.

### Negative / Tradeoffs

- Requires labeled golden sets per adopter domain — a real human-labor
  line item (first: baseball, Phase 1).
- More components than a similarity query; calibration is ongoing work,
  not one-time setup.

### Risks

- Poorly constructed golden sets miscalibrate the gate — mitigated by
  golden-set composition requirements (hard negatives, homonyms, temporal
  conflicts) and `kg_eval` metrics.
- Blocking recall gaps silently hide true matches — mitigated by
  multi-channel blocking and blocking-recall measurement in `kg_eval`.

## Impacted Areas

- [x] Data architecture
- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §7.4: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Feedback: `docs/ai/chatgpt-feedback-2026-07.md` (Response 1 §3, Response 2 §7)
- Disposition: `docs/ai/chatgpt-feedback-disposition.md` (A5, A6, A22)

## Related Issues / PRs

- PR #1 (external design review capture + disposition)

## Supersedes

ADR-0003, in part — the clause "promoted/merged by confidence-routed
resolution (auto / LLM evaluator / consensus / human queue)", insofar as
it makes embedding-similarity confidence bands the decision mechanism and
multi-agent consensus a standard resolution tier. Confidence-routed
adjudication as a policy concept survives behind the deterministic policy
gate.

## Superseded By

None.
