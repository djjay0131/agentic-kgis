# ADR-0010: Write-path mechanism — pure curation core, plan-applying executor, two-level store contracts

Status: Accepted
Date: 2026-07-10

## Context

ADR-0003 made the unbypassable gate a `CuratedGraphStore` wrapper around
any `GraphStore`, and the inherited `vttsi-contracts` protocol exposed
`upsert_nodes`/`upsert_edges` directly to consumers. External review
(PR #1) identified both as weaknesses: a wrapping store is a "magical
gate" whose decisions are neither serializable nor replayable; direct
upsert on the application-facing contract invites bypassing the pipeline
because it is convenient; and concurrent curation workers can make
locally reasonable but globally incompatible merges when decisions are
made against stale, arbitrary nodes. The traffic repos already demonstrate
the sound structure: pure decision logic with injected adapters, bounded
side effects, fallback discipline.

## Decision

Replace the wrapper mechanism with decisions and operations:

1. **Pure curation core** — `evaluate_candidate(candidate, graph_snapshot,
   ontology, policy) → decision`, no database connection. Explicit,
   serializable pipeline: Candidate → ValidationDecision →
   ResolutionDecision → CurationPlan → GraphMutationBatch → CommitResult,
   where `CurationPlan{plan_id, candidate_ids, snapshot_version,
   operations, preconditions, evidence_ids, policy_version}`.
2. **Executor** — applies a plan through the adapter only if optimistic
   preconditions still hold against the recorded cluster snapshot;
   idempotent operation IDs; deterministic survivor selection;
   compensating rollback from the operation log (never deletion of
   history). Curation actions are explicit operations: CREATE_IDENTITY,
   ATTACH_ASSERTION, MERGE_IDENTITIES, SPLIT_IDENTITY, REASSIGN_ASSERTION,
   RETRACT_ASSERTION, PROMOTE_ONTOLOGY_TERM.
3. **Two-level store contracts** — `CandidateSink` (application-facing;
   `submit(candidates) → SubmissionResult`; the only surface projects
   get) and `GraphMutationStore` (internal, executor-only;
   `apply(batch, preconditions) → CommitResult`). Reader/writer protocols
   are split (GraphReader, GraphWriter, TransactionalGraphWriter,
   BulkGraphWriter, TemporalGraphReader) with adapter capability
   declarations (supports_transactions, supports_temporal_queries,
   supports_vector_search, supports_full_text, supports_constraints,
   supports_bulk_upsert, supports_snapshot_reads,
   supports_graph_algorithms).

The unbypassable-gate *property* of ADR-0003 is preserved and
strengthened: applications hold no synchronous write path to the
canonical graph at all.

## Rationale

Serializable decisions are testable, replayable, comparable, explainable,
and backend-independent — a wrapper's inline side effects are none of
these. Snapshot-versioned preconditions substantially reduce async merge
conflicts. Removing raw upsert from the application surface makes the
0/18-style bypass structurally impossible rather than conventionally
discouraged. Capability declarations keep one contract honest across
memory, Neo4j, and Spanner without lowest-common-denominator decay.

## Alternatives Considered

### CuratedGraphStore wrapper around GraphStore (ADR-0003 mechanism)

Least new machinery and easy to explain, but decisions are implicit in
call flow, unreplayable, hard to audit, and the wrapped raw store still
exists in every consumer's dependency graph as a temptation.

### Keep one broad GraphStore protocol with upsert exposed, enforce by review

The vttsi-contracts status quo; relies on convention. Developers bypass
pipelines when raw writes are one import away; review does not scale to
that.

### Pessimistic cluster locking instead of optimistic preconditions

Prevents conflicting merges outright but serializes curation throughput
and deadlocks easily across long-running human review; optimistic
precondition failure + re-evaluation is cheaper at this scale and keeps
the executor stateless.

## Consequences

### Positive

- Every canonical mutation traces to a serializable, auditable plan with
  its evidence, policy version, and snapshot version.
- Curation logic is testable with zero infrastructure.
- Merge conflicts become precondition failures with defined re-evaluation,
  not silent corruption.
- Rollback is a first-class compensating operation.

### Negative / Tradeoffs

- More contract surface than one store protocol (two write levels, split
  readers/writers, capabilities).
- Plan/execute round-trips add latency versus inline wrapped writes
  (bounded: deterministic admission stays synchronous per ADR-0003's
  surviving principle; only canonical mutation is plan-mediated).

### Risks

- High precondition-failure rates under contention could thrash
  re-evaluation — monitored via curation metrics in kg_eval; cluster
  granularity is the tuning knob.
- Adapters may falsely declare capabilities — mitigated by the
  contract-conformance test suite.

## Impacted Areas

- [x] Data architecture
- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- Spec v2 §5.6, §5.7, §7.1, §7.2: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
- Feedback: `docs/ai/chatgpt-feedback-2026-07.md` (Response 1 §2, Response 2 §6, §9)
- Disposition: `docs/ai/chatgpt-feedback-disposition.md` (A9, A10, A12)

## Related Issues / PRs

- PR #1 (external design review capture + disposition)

## Supersedes

ADR-0003, in part — the clause "Deterministic gates run synchronously and
unbypassably in a `CuratedGraphStore` wrapper". The gate property survives;
the wrapper mechanism is replaced by the curation core, executor, and
two-level store contracts above.

## Superseded By

None.
