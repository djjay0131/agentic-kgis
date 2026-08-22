from datetime import UTC, datetime

import pytest

from kg_contracts.assertions import CurationStatus
from kg_contracts.curation import CurationOperation, CurationOperationType
from kg_contracts.stores import (
    AdapterCapabilities,
    BulkGraphWriter,
    CandidateSink,
    GraphMutationBatch,
    GraphMutationStore,
    GraphReader,
    GraphReadOptions,
    GraphWriter,
    LedgerReader,
    TransactionalGraphWriter,
    UnsupportedCapabilityError,
)
from kg_contracts.testing.contract import (
    CandidateSinkContract,
    GraphMutationStoreContract,
    LedgerReaderContract,
    MemoryReviewQueue,
    ReviewQueueContract,
)
from kg_contracts.identity import new_identity_id
from kg_contracts.testing.factories import make_assertion, make_entity, make_entity_candidate
from kg_contracts.testing.memory import MemoryCandidateSink, MemoryGraphStore

NOW = datetime(2026, 7, 12, tzinfo=UTC)


class TestMemoryCandidateSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return MemoryCandidateSink()


class TestMemoryGraphStore(GraphMutationStoreContract):
    def make_store(self) -> GraphMutationStore:
        return MemoryGraphStore()


class TestMemoryReviewQueue(ReviewQueueContract):
    def make_queue(self) -> MemoryReviewQueue:
        return MemoryReviewQueue()


class TestMemoryLedgerReader(LedgerReaderContract):
    def make_ledger(self) -> CandidateSink:
        return MemoryCandidateSink()


# --- ADR-0011: the memory ledger store is both a CandidateSink (write) and a
# LedgerReader (read), two separate surfaces; the canonical MemoryGraphStore is
# neither a ledger reader nor is the ledger a canonical GraphReader.


def test_memory_candidate_sink_implements_ledger_reader():
    assert isinstance(MemoryCandidateSink(), LedgerReader)


def test_memory_graph_store_is_not_a_ledger_reader():
    assert not isinstance(MemoryGraphStore(), LedgerReader)


def test_memory_candidate_sink_is_not_a_canonical_graph_reader():
    assert not isinstance(MemoryCandidateSink(), GraphReader)


# --- Owner ruling R2: MemoryGraphStore's apply() internally composes the
# adapter-internal writer primitives (put_entity/put_assertion/mark_superseded,
# begin/commit/rollback, put_entities) defined in stores.py (Task 13) — never
# application-facing, but the memory adapter's actual internal mutation
# surface. Structural (runtime_checkable) conformance is asserted directly.


def test_memory_graph_store_implements_graph_writer():
    assert isinstance(MemoryGraphStore(), GraphWriter)


def test_memory_graph_store_implements_transactional_graph_writer():
    assert isinstance(MemoryGraphStore(), TransactionalGraphWriter)


def test_memory_graph_store_implements_bulk_graph_writer():
    assert isinstance(MemoryGraphStore(), BulkGraphWriter)


# --- Whitebox coverage of memory.py-specific helpers not exercised by the
# generic contract suites (which only see the port protocols).


def test_memory_candidate_sink_received_helper_returns_admitted_candidates_in_order():
    sink = MemoryCandidateSink()
    first = make_entity_candidate(key="r1")
    second = make_entity_candidate(key="r2")
    duplicate_of_first = make_entity_candidate(key="r1")

    sink.submit([first, second, duplicate_of_first])

    assert [c.candidate_id for c in sink.received()] == [first.candidate_id, second.candidate_id]


def test_memory_graph_store_mark_superseded_updates_stored_assertion():
    store = MemoryGraphStore()
    entity = make_entity()
    store.apply(
        GraphMutationBatch(
            plan_id="pl_1",
            operations=(
                CurationOperation(
                    type=CurationOperationType.CREATE_IDENTITY,
                    payload=entity.model_dump(mode="python"),
                ),
            ),
        ),
        preconditions=(),
    )
    assertion = make_assertion(subject_identity=entity.identity_id)
    store.apply(
        GraphMutationBatch(
            plan_id="pl_2",
            operations=(
                CurationOperation(
                    type=CurationOperationType.ATTACH_ASSERTION,
                    payload=assertion.model_dump(mode="python"),
                ),
            ),
        ),
        preconditions=(),
    )

    at = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    store.mark_superseded(assertion.assertion_id, at)

    [stored] = store.assertions_for(
        entity.identity_id, options=GraphReadOptions(include_superseded=True)
    )
    assert stored.status is CurationStatus.SUPERSEDED
    assert stored.superseded_at == at


class _NonTemporalMemoryGraphStore(MemoryGraphStore):
    """A MemoryGraphStore that declares NO temporal-query support.

    Proves the capability-conformance contract works in both directions:
    the real store hardcodes supports_temporal_queries=True (so its
    temporal path always succeeds), but the raise branch guarding an
    undeclared capability must still fire for an adapter that says False.
    """

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(supports_temporal_queries=False)


def test_non_temporal_store_raises_unsupported_capability_for_temporal_options():
    store = _NonTemporalMemoryGraphStore()
    entity = make_entity()
    store.apply(
        GraphMutationBatch(
            plan_id="pl_1",
            operations=(
                CurationOperation(
                    type=CurationOperationType.CREATE_IDENTITY,
                    payload=entity.model_dump(mode="python"),
                ),
            ),
        ),
        preconditions=(),
    )

    with pytest.raises(UnsupportedCapabilityError):
        store.assertions_for(entity.identity_id, options=GraphReadOptions(valid_at=NOW))
    with pytest.raises(UnsupportedCapabilityError):
        store.assertions_for(entity.identity_id, options=GraphReadOptions(transaction_at=NOW))


def test_revoked_record_visible_by_default():
    # REVOKED read-visibility (issue #8): the canonical read surface only
    # mandates hiding SUPERSEDED by default (`include_superseded`). REVOKED
    # records deliberately stay visible — there is no `include_revoked`
    # option. This pins current behavior; auto-hiding REVOKED would be a
    # durable read-semantics change (an ADR, not a test-double tweak).
    store = MemoryGraphStore()
    revoked_entity = make_entity(status=CurationStatus.REVOKED)
    store.put_entity(revoked_entity)
    assert store.get_entity(revoked_entity.identity_id) is not None

    revoked_assertion = make_assertion(
        subject_identity=revoked_entity.identity_id, status=CurationStatus.REVOKED
    )
    store.put_assertion(revoked_assertion)
    assert store.assertions_for(revoked_entity.identity_id) == [revoked_assertion]


def test_superseded_is_hidden_by_default_but_revoked_is_not():
    # The asymmetry, pinned in one place: in the same position, SUPERSEDED is
    # hidden without include_superseded while REVOKED is not.
    store = MemoryGraphStore()
    ident = new_identity_id("g1")
    superseded = make_assertion(subject_identity=ident, status=CurationStatus.SUPERSEDED)
    revoked = make_assertion(subject_identity=ident, status=CurationStatus.REVOKED)
    store.put_assertion(superseded)
    store.put_assertion(revoked)

    visible = store.assertions_for(ident)
    assert superseded not in visible
    assert revoked in visible


def test_memory_graph_store_other_five_operation_types_raise_not_implemented_plan_3():
    store = MemoryGraphStore()
    entity = make_entity()
    unimplemented_types = (
        CurationOperationType.MERGE_IDENTITIES,
        CurationOperationType.SPLIT_IDENTITY,
        CurationOperationType.REASSIGN_ASSERTION,
        CurationOperationType.RETRACT_ASSERTION,
        CurationOperationType.PROMOTE_ONTOLOGY_TERM,
    )
    for op_type in unimplemented_types:
        batch = GraphMutationBatch(
            plan_id="pl_x",
            operations=(
                CurationOperation(type=op_type, payload={"identity_id": entity.identity_id}),
            ),
        )
        try:
            store.apply(batch, preconditions=())
        except NotImplementedError as exc:
            assert "Plan 3" in str(exc)
        else:
            raise AssertionError(f"{op_type} should have raised NotImplementedError")
