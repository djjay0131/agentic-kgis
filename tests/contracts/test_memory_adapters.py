from datetime import UTC, datetime

from kg_contracts.assertions import CurationStatus
from kg_contracts.curation import CurationOperation, CurationOperationType
from kg_contracts.stores import (
    BulkGraphWriter,
    CandidateSink,
    GraphMutationBatch,
    GraphMutationStore,
    GraphReadOptions,
    GraphWriter,
    TransactionalGraphWriter,
)
from kg_contracts.testing.contract import (
    CandidateSinkContract,
    GraphMutationStoreContract,
    MemoryReviewQueue,
    ReviewQueueContract,
)
from kg_contracts.testing.factories import make_assertion, make_entity, make_entity_candidate
from kg_contracts.testing.memory import MemoryCandidateSink, MemoryGraphStore


class TestMemoryCandidateSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return MemoryCandidateSink()


class TestMemoryGraphStore(GraphMutationStoreContract):
    def make_store(self) -> GraphMutationStore:
        return MemoryGraphStore()


class TestMemoryReviewQueue(ReviewQueueContract):
    def make_queue(self) -> MemoryReviewQueue:
        return MemoryReviewQueue()


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
