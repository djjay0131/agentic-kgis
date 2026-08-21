"""Store contracts: capabilities, read options, and reader/writer protocols
(ADR-0010).

*Phase-0 lesson (vttsi-contracts):* one broad `GraphStore` protocol becomes
either too weak or too demanding once multiple backends, temporal curation,
and rollback share it — v2 splits reader/writer protocols and declares
capabilities (spec §3.3, §5.6-§5.7). No Cypher/GQL on core contracts.

This module defines the canonical-graph read surface (`GraphReader`,
`TemporalGraphReader`), the *separate* candidate-ledger read surface
(`LedgerReader` with `LedgerReadOptions` / `LedgerEntry`), capability
declarations (`AdapterCapabilities`, `CapabilityDeclaring`), the
adapter-internal writer protocols (`GraphWriter`, `TransactionalGraphWriter`,
`BulkGraphWriter`) used only by `GraphMutationStore` implementations (Plan
3) — never application-facing — and the two application/executor-facing
write surfaces themselves: `CandidateSink` (the only write surface
applications ever hold) and `GraphMutationStore` (executor-only). Readers
and writers deliberately never share a protocol (ADR-0010): the
vttsi-contracts `GraphStore` that mixed both, exposing `upsert_nodes` /
`upsert_edges` directly to consumers, is superseded — raw writes are how
pipelines get bypassed. Canonical reads and ledger reads are likewise never
the same surface (ADR-0006 three-store separation, ADR-0011): the canonical
graph and the candidate ledger have distinct access paths, so uncertainty
cannot leak into a canonical query. The in-memory adapters implementing
these protocols come in Task 18.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._ulid import new_ulid
from kg_contracts.assertions import Assertion, CanonicalEntity
from kg_contracts.candidates import Candidate
from kg_contracts.curation import CurationOperation, Precondition, ProcessingState
from kg_contracts.identity import EntityRef


class UnsupportedCapabilityError(RuntimeError):
    """A read/write option requires a capability the adapter hasn't declared.

    Never silently ignored: e.g. a non-temporal adapter given `valid_at` /
    `transaction_at` in `GraphReadOptions` MUST raise this rather than
    quietly serving a query it can't actually honor.
    """


class AdapterCapabilities(BaseModel):
    """What a graph adapter actually supports (spec §5.7). All default False.

    Adapters declare optional behavior instead of leaking it: consumers
    check capabilities before relying on an option that depends on one, and
    adapters raise `UnsupportedCapabilityError` (never silently ignore) when
    asked for something not declared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    supports_transactions: bool = False
    supports_temporal_queries: bool = False
    supports_vector_search: bool = False
    supports_full_text: bool = False
    supports_constraints: bool = False
    supports_bulk_upsert: bool = False
    supports_snapshot_reads: bool = False
    supports_graph_algorithms: bool = False


class GraphReadOptions(BaseModel):
    """Explicit consistency options every *canonical-graph* read takes (spec §3.3).

    `curation_epoch=None` means "the latest **published** epoch" — readers
    consume a published epoch, never "whatever is present", so one query can
    never observe a partially promoted batch.

    There is deliberately **no** ledger-visibility option here (ADR-0011,
    correcting ADR-0006's original field list). Under ADR-0006 the canonical
    graph contains only accepted records; uncertain candidates "never appear
    as ordinary graph entities" and the three stores share a physical
    database but "never one access path". An `include_provisional`-style flag
    would make the canonical reader an access path into the ledger — exactly
    the leak the three-store separation exists to prevent. Ledger visibility
    is instead a separate surface: `LedgerReader` / `LedgerReadOptions`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    curation_epoch: int | None = None
    valid_at: datetime | None = None
    transaction_at: datetime | None = None
    include_superseded: bool = False
    minimum_evidence_policy: str | None = None


@runtime_checkable
class CapabilityDeclaring(Protocol):
    """Anything that can report what it supports (spec §5.7)."""

    def capabilities(self) -> AdapterCapabilities: ...


@runtime_checkable
class GraphReader(Protocol):
    """Read-only access to the canonical graph (spec §5.6, ADR-0010).

    Deliberately exposes no write surface — readers and writers never share
    a protocol (ADR-0010).
    """

    def current_epoch(self) -> int: ...

    def get_entity(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> CanonicalEntity | None: ...

    def find_entities(
        self,
        entity_type: str | None = None,
        alias: EntityRef | None = None,
        options: GraphReadOptions = GraphReadOptions(),
    ) -> list[CanonicalEntity]: ...

    def assertions_for(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> list[Assertion]: ...

    def neighborhood(
        self, identity_id: str, hops: int = 1, options: GraphReadOptions = GraphReadOptions()
    ) -> list[CanonicalEntity]: ...


@runtime_checkable
class TemporalGraphReader(GraphReader, Protocol):
    """Marker for adapters that honor `valid_at` / `transaction_at` (spec §5.4).

    Non-temporal adapters MUST raise `UnsupportedCapabilityError` when given
    temporal options rather than silently ignoring them. Full temporal query
    support is capability-declared (`supports_temporal_queries`, spec
    §5.7): implemented first on the memory store, then per-backend as
    adopters need it.
    """


class LedgerEntry(BaseModel):
    """One candidate as it sits in the candidate ledger, with its state.

    The ledger's read record (ADR-0006 store 1): the submitted `candidate`
    plus the ledger's own `processing_state` (`curation.py`, the ledger's
    async lifecycle — distinct from the canonical `CurationStatus`) and the
    transaction time it was received. Pairing candidate with processing
    state is what a canonical `CanonicalEntity`/`Assertion` deliberately
    cannot carry — which is precisely why ledger visibility needs its own
    record type and its own reader rather than a flag on the canonical read
    surface. The full persisted ledger row (dedup keys, retry counters,
    quarantine reasons) is modeled by the ledger store in Plan 2; this is
    the minimal read projection the separation requires at the contract
    layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: Candidate
    processing_state: ProcessingState
    received_at: datetime


class LedgerReadOptions(BaseModel):
    """Filters for a `LedgerReader` query (ADR-0006 store 1, ADR-0011).

    Reads over the candidate ledger — the *uncertain* store — for review
    tooling and operators, never mixed into canonical graph reads.
    `processing_states=None` returns every ledger state; a tuple restricts
    to those states (e.g. only `REVIEW_PENDING` for a review queue view).
    `graph_id=None` spans all graphs; set it to scope to one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    processing_states: tuple[ProcessingState, ...] | None = None
    graph_id: str | None = None


@runtime_checkable
class LedgerReader(Protocol):
    """Read-only access to the candidate ledger — a *separate* surface (ADR-0011).

    The canonical `GraphReader` exposes only accepted graph records; this
    protocol is the distinct access path to the uncertain candidate ledger
    (ADR-0006: the three stores may share one physical database but "never
    one access path"). Keeping them as two protocols is what makes "uncertain
    candidates never appear as ordinary graph entities" a structural
    guarantee rather than a per-query flag a caller must remember to unset.
    A `GraphReader` and a `LedgerReader` are never the same protocol; an
    adapter may implement one, the other, or both (over one physical store),
    but the surfaces stay separate. Read-only, like `GraphReader`: ledger
    writes go through `CandidateSink`, never here.
    """

    def ledger_entries(
        self, options: LedgerReadOptions = LedgerReadOptions()
    ) -> list[LedgerEntry]: ...

    def ledger_entry(self, candidate_id: str) -> LedgerEntry | None: ...


@runtime_checkable
class GraphWriter(Protocol):
    """Adapter-internal write primitives (spec §5.6, ADR-0010).

    Used only by `GraphMutationStore` implementations (Plan 3) — never
    application-facing. The only application-facing write surface is
    `CandidateSink` (Task 15); raw `put_entity`/`put_assertion` reintroduce
    exactly the vttsi-contracts `upsert_nodes`/`upsert_edges` bypass this
    split deliberately forecloses at the application boundary.
    """

    def put_entity(self, entity: CanonicalEntity) -> None: ...

    def put_assertion(self, assertion: Assertion) -> None: ...

    def mark_superseded(self, assertion_id: str, at: datetime) -> None: ...


@runtime_checkable
class TransactionalGraphWriter(GraphWriter, Protocol):
    """Adapter-internal transactional write primitives (spec §5.6, ADR-0010).

    Used only by `GraphMutationStore` implementations (Plan 3) — never
    application-facing. Adapters declaring `supports_transactions`
    implement this.
    """

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class BulkGraphWriter(GraphWriter, Protocol):
    """Adapter-internal bulk write primitives (spec §5.6, ADR-0010).

    Used only by `GraphMutationStore` implementations (Plan 3) — never
    application-facing. Adapters declaring `supports_bulk_upsert`
    implement this.
    """

    def put_entities(self, entities: Sequence[CanonicalEntity]) -> int: ...


class SubmissionStatus(StrEnum):
    """Synchronous candidate-admission outcome only (spec §7.2).

    Deterministic checks performed at submission time — well-formedness,
    exact-duplicate detection. Acceptance into the canonical graph is a
    separate, asynchronous decision reported later through the ledger's own
    `ProcessingState` (`curation.py`), never folded into this enum.
    """

    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"


class SubmissionOutcome(BaseModel):
    """The synchronous admission outcome for one submitted candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    status: SubmissionStatus
    reason: str | None = None
    trace_id: str


class SubmissionResult(BaseModel):
    """The synchronous response to a `CandidateSink.submit()` call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    submission_id: str = Field(default_factory=lambda: "sub_" + new_ulid())
    outcomes: tuple[SubmissionOutcome, ...]

    def counts(self) -> dict[SubmissionStatus, int]:
        """Aggregate `outcomes` by `SubmissionStatus`."""
        result: dict[SubmissionStatus, int] = {}
        for outcome in self.outcomes:
            result[outcome.status] = result.get(outcome.status, 0) + 1
        return result


@runtime_checkable
class CandidateSink(Protocol):
    """The only application-facing write surface (ADR-0010).

    Applications submit candidates to the ledger; they never mutate the
    canonical graph directly. `submit()` returns only the synchronous
    admission outcome (`SubmissionStatus`) — whether acceptance into the
    canonical graph eventually follows is reported asynchronously through
    the ledger's `ProcessingState`, not through this call's return value.
    """

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult: ...


class GraphMutationBatch(BaseModel):
    """A `CurationPlan` compiled into the operations an executor applies.

    Mutations commit as atomic curation epochs (spec §3.3): `operations`
    must carry at least one operation — an empty batch has no epoch to
    commit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str = Field(default_factory=lambda: "mb_" + new_ulid())
    plan_id: str
    operations: tuple[CurationOperation, ...] = Field(min_length=1)


class CommitResult(BaseModel):
    """The outcome of a `GraphMutationStore.apply()` call.

    `committed=True` requires `new_epoch` — mutations commit as atomic
    curation epochs (spec §3.3), so a successful commit always names the
    epoch it produced. `committed=False` with `failed_preconditions`
    non-empty means a stale snapshot: the caller must re-evaluate against
    the current graph state, never blindly retry the same batch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str
    committed: bool
    new_epoch: int | None = None
    failed_preconditions: tuple[Precondition, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def _check_committed_requires_new_epoch(self) -> "CommitResult":
        if self.committed and self.new_epoch is None:
            raise ValueError("committed=True requires new_epoch")
        # Fail-closed (issue #8): a non-commit must name why. Without this a
        # `committed=False` result with no `error` and no `failed_preconditions`
        # is a silent failure the caller cannot act on — neither a stale
        # snapshot to re-evaluate nor an error to surface.
        if not self.committed and self.error is None and not self.failed_preconditions:
            raise ValueError(
                "committed=False requires a reason: set error or a non-empty "
                "failed_preconditions"
            )
        return self


@runtime_checkable
class GraphMutationStore(Protocol):
    """Applies precondition-checked mutation batches (ADR-0010).

    Executor-only: the curation core turns a `CurationPlan` into a
    `GraphMutationBatch` and hands it here; applications must never hold a
    `GraphMutationStore` reference (governance-delta principle 3). The only
    application-facing write surface is `CandidateSink`.
    """

    def apply(
        self, batch: GraphMutationBatch, preconditions: Sequence[Precondition]
    ) -> CommitResult: ...
