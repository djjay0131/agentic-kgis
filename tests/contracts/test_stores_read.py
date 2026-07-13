from datetime import datetime

import pytest
from pydantic import ValidationError

from kg_contracts.assertions import Assertion, CanonicalEntity
from kg_contracts.identity import EntityRef
from kg_contracts.stores import (
    AdapterCapabilities,
    BulkGraphWriter,
    GraphReader,
    GraphReadOptions,
    GraphWriter,
    TransactionalGraphWriter,
    UnsupportedCapabilityError,
)


def test_graph_read_options_defaults_canonical_only_at_latest_published_epoch():
    # curation_epoch None = latest *published* epoch; canonical-only by default.
    opts = GraphReadOptions()
    assert opts.curation_epoch is None
    assert opts.include_provisional is False
    assert opts.include_superseded is False


def test_adapter_capabilities_defaults_all_false_and_frozen():
    caps = AdapterCapabilities()
    assert caps.supports_transactions is False
    assert caps.supports_temporal_queries is False
    assert caps.supports_vector_search is False
    assert caps.supports_full_text is False
    assert caps.supports_constraints is False
    assert caps.supports_bulk_upsert is False
    assert caps.supports_snapshot_reads is False
    assert caps.supports_graph_algorithms is False
    with pytest.raises(ValidationError):
        caps.supports_transactions = True  # type: ignore[misc]


class _FakeReader:
    """Duck-typed fake with GraphReader's five methods, nothing else."""

    def current_epoch(self) -> int:
        return 1

    def get_entity(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> CanonicalEntity | None:
        return None

    def find_entities(
        self,
        entity_type: str | None = None,
        alias: EntityRef | None = None,
        options: GraphReadOptions = GraphReadOptions(),
    ) -> list[CanonicalEntity]:
        return []

    def assertions_for(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> list[Assertion]:
        return []

    def neighborhood(
        self, identity_id: str, hops: int = 1, options: GraphReadOptions = GraphReadOptions()
    ) -> list[CanonicalEntity]:
        return []


def test_duck_typed_fake_satisfies_graph_reader():
    assert isinstance(_FakeReader(), GraphReader)


def test_graph_reader_exposes_no_write_surface():
    # ADR-0010: readers and writers never share a surface.
    for name in ("upsert_nodes", "upsert_edges", "put_entity", "apply", "submit"):
        assert name not in dir(GraphReader)


def test_unsupported_capability_error_is_runtime_error():
    assert issubclass(UnsupportedCapabilityError, RuntimeError)


# --- Owner ruling R2: writer protocols (adapter-internal, GraphMutationStore-only,
# never application-facing) are kept and gain duck-type tests here; Task 18's
# MemoryGraphStore will implement them for real.


class _FakeWriter:
    """Duck-typed fake with GraphWriter's three methods, nothing else."""

    def put_entity(self, entity: CanonicalEntity) -> None:
        return None

    def put_assertion(self, assertion: Assertion) -> None:
        return None

    def mark_superseded(self, assertion_id: str, at: datetime) -> None:
        return None


def test_duck_typed_fake_satisfies_graph_writer():
    assert isinstance(_FakeWriter(), GraphWriter)


class _FakeTransactionalWriter(_FakeWriter):
    """Adds begin/commit/rollback on top of the GraphWriter surface."""

    def begin(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_duck_typed_fake_satisfies_transactional_graph_writer():
    assert isinstance(_FakeTransactionalWriter(), TransactionalGraphWriter)


class _FakeBulkWriter(_FakeWriter):
    """Adds put_entities on top of the GraphWriter surface."""

    def put_entities(self, entities: list[CanonicalEntity]) -> int:
        return len(entities)


def test_duck_typed_fake_satisfies_bulk_graph_writer():
    assert isinstance(_FakeBulkWriter(), BulkGraphWriter)
