# ADR-0029: A second canonical read key — `GraphReader.get_assertion` and the evidence reverse index

Status: Proposed
Date: 2026-10-09
Raised by: Issue #59 — read ports KGPS needs for `explain(assertion_id)` and `impacted_by(evidence_id)`, found in the KGPS (PA-AKG) provenance audit, 2026-10-07

## Context

The KGPS design spec §7 needs two provenance reads this repository does not
yet expose:

- `explain(assertion_id)` — resolve a single assertion by id. `GraphReader`
  (`src/kg_contracts/stores.py`) is keyed by identity only: `get_entity` by
  `identity_id` and `assertions_for(identity_id)`. There is no lookup by
  `assertion_id`, so KGPS builds a `GraphAssertionIndex` by scanning every
  entity's assertions. That is fine for tests and O(graph) in production.
- `impacted_by(evidence_id)` — the subjects that cite a piece of evidence,
  so a retraction can name the candidates/assertions to re-validate.
  `SqliteEvidenceRegistry` supports subject → refs (`refs_for`, `resolve`)
  but has no evidence → subjects reverse lookup.

Both are read-side additions. The canonical read surface is deliberately
canonical-only and its visibility rules are load-bearing (ADR-0006,
ADR-0011): a read must not reveal a record the ordinary read path hides, and
`include_superseded` / `include_revoked` are two independent switches
(ADR-0025) with a subject-only revoke shield (ADR-0026, ADR-0027). A new
keyed read has to preserve all of that rather than open a second, weaker
path into the canonical graph.

`AdapterCapabilities` (spec §5.7) is where an adapter declares optional
behavior so a consumer can prefer a capability over a fallback.

## Decision

### 1. `GraphReader.get_assertion(assertion_id, options) -> Assertion | None`

Add an id-keyed read to the canonical read contract:

```python
def get_assertion(
    self, assertion_id: str, options: GraphReadOptions = GraphReadOptions()
) -> Assertion | None: ...
```

It is the assertion counterpart to `get_entity`, and it honors **exactly**
the visibility rules `assertions_for` applies — the `curation_epoch` filter,
the `include_superseded` and `include_revoked` status switches, the
subject-revoke shield (ADR-0026), and the `valid_at` / `transaction_at`
temporal filters. A hidden assertion returns `None`, exactly as it would be
absent from `assertions_for`; an unknown id returns `None`. There is no
separate "show everything" semantics and no ledger-visibility leak.

### 2. `AdapterCapabilities.supports_assertion_lookup` (default `False`)

The adapter can resolve one assertion by id through an id index rather than a
scan. Consumers check it before preferring `get_assertion` over building an
index by scanning. The field defaults `False`, so the addition is backward
compatible for every existing adapter construction. `MemoryGraphStore`
declares it `True` and backs `get_assertion` with an `assertion_id -> Assertion`
index kept in lockstep with the subject-keyed store. The two indexes must not
diverge, so `apply` rejects an `ATTACH_ASSERTION` whose `assertion_id` already
exists (in the store or earlier in the same batch) as a loud non-commit naming
the id, rather than appending a second subject-keyed entry the id index cannot
address. The matching invariant for the unimplemented `RETRACT_ASSERTION`
(named in code and pinned by a test): any future operation that removes or
reassigns an assertion must delete from the id index alongside the
subject-keyed list.

### 3. `SqliteEvidenceRegistry.subjects_for(evidence_id, relationship=None) -> list[str]`

The inverse of `refs_for`: the distinct subjects that cite an evidence id,
optionally narrowed to one `EvidenceRelationship`, ordered deterministically.
Backed by the `ix_refs_evidence` index on `evidence_refs(evidence_id)` — an
index probe, not a scan. `ensure_evidence_schema` now asserts that index
idempotently as well, so an existing database opened through a
caller-supplied connection gains it (fresh databases already got it in
`SCHEMA_SQL`, added with the erasure work).

### 4. Conformance coverage

`GraphMutationStoreContract` — the published suite every adapter must pass —
gains four `get_assertion` cases: an active assertion is returned by id; a
superseded one is hidden by default and revealed by `include_superseded`; an
assertion on a revoked subject is shielded by default and revealed by
`include_revoked`; and an unknown id returns `None`. `EvidenceRegistryContract`
gains the reverse-lookup cases, including relationship filtering and
de-duplication of a subject citing the same evidence under two
relationships.

### 5. Adopter follow-up

`agentic-kg`'s `Neo4jCanonicalGraphStore` must implement `get_assertion`
(the same way it adopted `RESTORE_IDENTITY`, ADR-0027). Listed as a
follow-up, not done here.

### 6. The `runtime_checkable` protocol-widening hazard

`GraphReader` is `@runtime_checkable`. A runtime-checkable `Protocol`
satisfies `isinstance()` on **method presence alone** — it does not check
signatures and it has no structural default. Adding `get_assertion` to
`GraphReader` therefore silently *narrows* which objects satisfy
`isinstance(store, GraphReader)`: any store that implemented the old
protocol and has not yet added the new method stops counting as a
`GraphReader`, even though nothing about its reads regressed.

That is not hypothetical here. `agentic-kgcs`'s executor
(`src/kgcs/executor/executor.py`, ~L243) gates its snapshot preconditions on
`isinstance(store, GraphReader)`. A third-party store lacking `get_assertion`
would silently stop matching, so the executor would **skip its snapshot
preconditions** rather than fail — a read-compatibility addition producing a
quiet write-safety regression. The failure is invisible: no exception, no
log line, just fewer guards.

Consequence recorded: every store type-checked against `GraphReader` must
add `get_assertion` when it adopts this contract — the method is not
optional even for an adapter that never serves `explain(assertion_id)`
directly (it may scan or raise `UnsupportedCapabilityError` internally, but
the name must be present). Mitigation adopted here: **adapters must
implement it**, and the published conformance suite plus the cross-repo
`agentic-kg` follow-up (above) force it loudly. A structural default (a
`GraphReader` mixin supplying a scanning `get_assertion`, so an adapter
cannot fall out of the protocol by omission) is noted as a **possible
future mitigation** if third-party stores prove slow to adopt; it is not
introduced here because it would turn a missing index into a silent
O(graph) scan, which is the cost this ADR exists to remove.

## Rationale

**One read surface, one set of gates.** Adding the id lookup to `GraphReader`
rather than a separate protocol keeps the canonical read contract a single
place where visibility is defined. The alternative — a marker subprotocol
like `TemporalGraphReader` — would let an adapter offer id lookup while
re-implementing (and drifting from) the shield and status gates. The id key
is a second index, not a second surface, so the gates are shared helpers
(`_subject_visible`, `_is_visible`) in the reference store.

**A single-id read must not be a weaker read.** The whole reason the two
status switches and the shield exist is that "history" and "retraction" are
different facts (ADR-0025/0026). A lookup that returned a REVOKED subject's
assertion by default, or a SUPERSEDED one, would be a bypass of those rules
dressed as a convenience. Pinning parity in the published suite is what keeps
the Neo4j adapter honest.

**A capability, not a hard requirement, for the index.** Some adapters can
answer the lookup cheaply (an id index); others cannot. Declaring
`supports_assertion_lookup` lets a consumer such as KGPS choose
`get_assertion` when it is index-backed and fall back to a scan otherwise,
without either behavior being silent.

**The evidence reverse index already exists.** ADR candidate 0010 (the
erasure cascade, issue #61) added `ix_refs_evidence` to serve its orphan
check. `subjects_for` reads the same index; the only addition is ensuring the
index on a pre-existing database opened through a supplied connection.

## Alternatives Considered

### Keep building `GraphAssertionIndex` by scanning every entity

The status quo. Rejected: it is the O(graph) production cost the KGPS audit
filed. A single indexed read is the point of the port.

### Publish `get_assertion` only on a marker subprotocol

Rejected. Id lookup is a fundamental canonical read, not an optional temporal
one; a separate protocol fragments the visibility contract and leaves the
gates to be re-derived per adapter. The capability flag already carries the
"index-backed" nuance without a second protocol.

### Return `Evidence` objects from `subjects_for`

Rejected. `subjects_for` mirrors `refs_for`'s shape (identifiers out), and
callers that need the evidence body already have `resolve`/`get`. Keeping the
reverse lookup id-only avoids implying a resolve that may raise on a dangling
ref.

### Gate `get_assertion` with a mandatory capability raise

Considered and declined. `get_assertion` is part of `GraphReader`, so a
non-index adapter can still answer it by scanning; the capability advertises
efficiency, not existence. An adapter that cannot answer it at all may raise
`UnsupportedCapabilityError`, which the docstring permits but does not
mandate.

## Consequences

### Positive

- KGPS `explain(assertion_id)` becomes an indexed, visibility-faithful read
  instead of an O(graph) scan.
- KGPS `impacted_by(evidence_id)` becomes the indexed inverse of `refs_for`.
- The canonical read contract has one visibility definition, exercised by the
  published suite for every adapter.

### Negative / Tradeoffs

- `kg_contracts` gains a protocol method and an `AdapterCapabilities` field —
  a contract change every graph adapter must implement. The capability field
  defaults `False`, so construction sites are unaffected.
- A `GraphReader` implementation that ignores the new method at runtime fails
  the published conformance suite (the intended loud failure).

### Risks

- `agentic-kg`'s `Neo4jCanonicalGraphStore` must adopt `get_assertion`; until
  it does it lacks the method and would fail the suite. Listed as a
  follow-up, not done here.
- The `runtime_checkable` protocol widening (Decision §6): a store that
  implements `GraphReader` without `get_assertion` silently stops satisfying
  `isinstance(store, GraphReader)`. The known consumer is `agentic-kgcs`'s
  executor, which gates snapshot preconditions on that check, so the
  regression is a silent skip of a guard, not a loud error. Mitigated by
  requiring every adapter to implement the method; a scanning mixin default
  is a deferred option.
- The evidence reverse lookup sees only citations registered through
  `add_refs` (and its non-committing variant), the same scope limit the
  orphan check documents (ADR candidate 0010). A citation carried only inside
  a candidate payload is invisible to it.

## Impacted Areas

- [x] Domain model
- [x] Data architecture
- [x] Integrations
- [x] Implementation
- [x] Documentation

## Related Documents

- `src/kg_contracts/stores.py` (`GraphReader`, `AdapterCapabilities`),
  `src/kg_contracts/testing/memory.py` (`MemoryGraphStore.get_assertion`),
  `src/kg_contracts/testing/contract.py` (`GraphMutationStoreContract`)
- `src/kgis/evidence/store.py` (`SqliteEvidenceRegistry.subjects_for`),
  `src/kgis/evidence/schema.py` (`ix_refs_evidence`), `src/kgis/evidence/contract.py`
- ADR-0006 (three-store separation), ADR-0011 (canonical-only reads),
  ADR-0025 (`include_revoked`), ADR-0026 (assertion shield), ADR-0027
  (subject-only shield)
- KGPS design spec §7:
  <https://github.com/djjay0131/agentic-kgps/blob/main/llm/specs/2026-10-07-kgps-design.md>

## Related Issues / PRs

- Issue #59 (this repo) — fixed by this ADR.
- KGPS tracking issue djjay0131/agentic-kgps#1.
- Follow-up, deliberately not touched here: `agentic-kg`'s
  `Neo4jCanonicalGraphStore` must implement `get_assertion`.

## Supersedes

None.

## Superseded By

None.
