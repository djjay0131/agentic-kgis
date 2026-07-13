from datetime import datetime

import pytest
from pydantic import ValidationError

from kg_contracts.assertions import Assertion, CanonicalEntity
from kg_contracts.identity import EntityRef
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import (
    AdapterCapabilities,
    BulkGraphWriter,
    GraphReader,
    GraphReadOptions,
    GraphWriter,
    LedgerEntry,
    LedgerReader,
    LedgerReadOptions,
    TransactionalGraphWriter,
    UnsupportedCapabilityError,
)


def test_graph_read_options_defaults_canonical_only_at_latest_published_epoch():
    # curation_epoch None = latest *published* epoch; canonical-only by default.
    opts = GraphReadOptions()
    assert opts.curation_epoch is None
    assert opts.include_superseded is False


def test_graph_read_options_has_no_ledger_visibility_option():
    # ADR-0011: the canonical read surface exposes no way to see ledger
    # (provisional) records. The old include_provisional flag is gone, and
    # extra="forbid" makes reintroducing it as a read option unrepresentable
    # rather than a silently-ignored kwarg.
    assert "include_provisional" not in GraphReadOptions.model_fields
    with pytest.raises(ValidationError):
        GraphReadOptions(include_provisional=True)  # type: ignore[call-arg]


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


# --- ADR-0011: the candidate-ledger read surface is separate from the canonical
# GraphReader. These prove the two access paths never collapse into one.


def test_ledger_read_options_defaults_span_all_states_and_graphs():
    opts = LedgerReadOptions()
    assert opts.processing_states is None
    assert opts.graph_id is None


class _FakeLedgerReader:
    """Duck-typed fake with LedgerReader's two methods, nothing else."""

    def ledger_entries(
        self, options: LedgerReadOptions = LedgerReadOptions()
    ) -> list[LedgerEntry]:
        return []

    def ledger_entry(self, candidate_id: str) -> LedgerEntry | None:
        return None


def test_duck_typed_fake_satisfies_ledger_reader():
    assert isinstance(_FakeLedgerReader(), LedgerReader)


def test_ledger_reader_and_graph_reader_are_distinct_surfaces():
    # A canonical GraphReader must not accidentally satisfy LedgerReader, and a
    # LedgerReader must not satisfy GraphReader — the separation is structural,
    # not a runtime flag (ADR-0006 "never one access path").
    assert not isinstance(_FakeReader(), LedgerReader)
    assert not isinstance(_FakeLedgerReader(), GraphReader)


def test_graph_reader_exposes_no_ledger_surface():
    # The canonical reader has no ledger method: uncertainty cannot be reached
    # through a canonical query.
    for name in ("ledger_entries", "ledger_entry"):
        assert name not in dir(GraphReader)


def test_ledger_reader_exposes_no_canonical_or_write_surface():
    for name in ("get_entity", "find_entities", "assertions_for", "put_entity", "submit", "apply"):
        assert name not in dir(LedgerReader)


def test_processing_state_is_usable_as_a_ledger_filter():
    # LedgerReadOptions filters on the ledger's own ProcessingState machine,
    # never the canonical CurationStatus.
    opts = LedgerReadOptions(processing_states=(ProcessingState.REVIEW_PENDING,))
    assert opts.processing_states == (ProcessingState.REVIEW_PENDING,)
