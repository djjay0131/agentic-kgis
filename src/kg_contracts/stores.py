"""Read-side store contracts: capabilities, read options, reader protocols (ADR-0010).

*Phase-0 lesson (vttsi-contracts):* one broad `GraphStore` protocol becomes
either too weak or too demanding once multiple backends, temporal curation,
and rollback share it — v2 splits reader/writer protocols and declares
capabilities (spec §3.3, §5.6-§5.7). No Cypher/GQL on core contracts.

This module defines the read surface (`GraphReader`, `TemporalGraphReader`),
capability declarations (`AdapterCapabilities`, `CapabilityDeclaring`), and
the adapter-internal writer protocols (`GraphWriter`,
`TransactionalGraphWriter`, `BulkGraphWriter`) used only by
`GraphMutationStore` implementations (Plan 3) — never application-facing.
Readers and writers deliberately never share a protocol (ADR-0010): the
vttsi-contracts `GraphStore` that mixed both, exposing `upsert_nodes` /
`upsert_edges` directly to consumers, is superseded — raw writes are how
pipelines get bypassed. The application-facing write surfaces
(`CandidateSink`, `GraphMutationStore`) come in Task 15; the in-memory
`MemoryGraphStore` adapter implementing all of these protocols comes in
Task 18.
"""

from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict

from kg_contracts.assertions import Assertion, CanonicalEntity
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
    """Explicit consistency options every graph read takes (spec §3.3).

    `curation_epoch=None` means "the latest **published** epoch" — readers
    consume a published epoch, never "whatever is present", so one query can
    never observe a partially promoted batch. `include_provisional` is
    opt-in ledger visibility (default canonical-only, ADR-0006): uncertain
    candidate-ledger records are excluded unless a caller explicitly asks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    curation_epoch: int | None = None
    valid_at: datetime | None = None
    transaction_at: datetime | None = None
    include_provisional: bool = False
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
