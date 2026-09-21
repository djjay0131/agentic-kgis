from datetime import UTC, datetime

import pytest

from kg_contracts.assertions import CanonicalEntity, CurationStatus
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


def test_revoked_record_is_hidden_by_default_and_reachable_with_include_revoked():
    # ADR-0025 changed this: REVOKED records are now hidden from canonical
    # reads by default, because otherwise REVOKE_IDENTITY (the inverse of
    # CREATE_IDENTITY) would change nothing a reader can observe. Nothing is
    # deleted — include_revoked=True is the history surface that returns it.
    store = MemoryGraphStore()
    revoked_entity = make_entity(status=CurationStatus.REVOKED)
    store.put_entity(revoked_entity)
    assert store.get_entity(revoked_entity.identity_id) is None
    assert (
        store.get_entity(
            revoked_entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        == revoked_entity
    )

    revoked_assertion = make_assertion(
        subject_identity=revoked_entity.identity_id, status=CurationStatus.REVOKED
    )
    store.put_assertion(revoked_assertion)
    assert store.assertions_for(revoked_entity.identity_id) == []
    assert store.assertions_for(
        revoked_entity.identity_id, options=GraphReadOptions(include_revoked=True)
    ) == [revoked_assertion]


def test_superseded_and_revoked_are_hidden_by_two_independent_flags():
    # Replaced-by-a-newer-record and withdrawn-outright are different facts.
    # Neither flag may reveal the other's records: asking to see graph
    # history must not surface retractions the caller did not ask for.
    store = MemoryGraphStore()
    ident = new_identity_id("g1")
    superseded = make_assertion(subject_identity=ident, status=CurationStatus.SUPERSEDED)
    revoked = make_assertion(subject_identity=ident, status=CurationStatus.REVOKED)
    active = make_assertion(subject_identity=ident, status=CurationStatus.ACTIVE)
    store.put_assertion(superseded)
    store.put_assertion(revoked)
    store.put_assertion(active)

    assert store.assertions_for(ident) == [active]
    assert store.assertions_for(
        ident, options=GraphReadOptions(include_superseded=True)
    ) == [superseded, active]
    assert store.assertions_for(
        ident, options=GraphReadOptions(include_revoked=True)
    ) == [revoked, active]
    assert store.assertions_for(
        ident, options=GraphReadOptions(include_superseded=True, include_revoked=True)
    ) == [superseded, revoked, active]


def _create_identity_batch(plan_id: str, *entities: CanonicalEntity) -> GraphMutationBatch:
    return GraphMutationBatch(
        plan_id=plan_id,
        operations=tuple(
            CurationOperation(
                type=CurationOperationType.CREATE_IDENTITY,
                payload=entity.model_dump(mode="python"),
            )
            for entity in entities
        ),
    )


def _revoke_identity_batch(plan_id: str, *entities: CanonicalEntity) -> GraphMutationBatch:
    return GraphMutationBatch(
        plan_id=plan_id,
        operations=tuple(
            CurationOperation(
                type=CurationOperationType.REVOKE_IDENTITY,
                payload={"identity_id": entity.identity_id, "reason": "rollback"},
                reversal_data=entity.model_dump(mode="python"),
            )
            for entity in entities
        ),
    )


def test_revoke_identity_reverses_a_committed_create_identity_run():
    # The defect this closes, end to end: a committed run of eight
    # CREATE_IDENTITY operations used to compensate to nothing. The counts
    # are asserted BEFORE the compensation too, so "no entities visible"
    # cannot pass vacuously on a store that never created any.
    store = MemoryGraphStore()
    entities = [make_entity(key=f"e{i}", identity_id=new_identity_id("g1")) for i in range(8)]

    created = store.apply(_create_identity_batch("pl_create", *entities), preconditions=())
    assert created.committed is True
    assert len(store.find_entities(entity_type="TestEntity")) == 8

    compensated = store.apply(_revoke_identity_batch("pl_undo", *entities), preconditions=())
    assert compensated.committed is True
    assert store.find_entities(entity_type="TestEntity") == []

    # Reversed, not erased: every one is still there, named, and marked.
    surviving = store.find_entities(
        entity_type="TestEntity", options=GraphReadOptions(include_revoked=True)
    )
    assert {e.identity_id for e in surviving} == {e.identity_id for e in entities}
    assert all(e.status is CurationStatus.REVOKED for e in surviving)


def test_revoke_identity_preserves_the_creation_epoch():
    # An identity that was created and then reversed must not silently become
    # invisible in a way that breaks history. Advancing curation_epoch on
    # revoke would do exactly that: an epoch-scoped read of the epoch that
    # CREATED the identity would stop finding it.
    store = MemoryGraphStore()
    entity = make_entity(identity_id=new_identity_id("g1"))
    created = store.apply(_create_identity_batch("pl_create", entity), preconditions=())
    creation_epoch = created.new_epoch
    assert creation_epoch is not None

    revoked = store.apply(_revoke_identity_batch("pl_undo", entity), preconditions=())
    assert revoked.new_epoch is not None
    assert revoked.new_epoch > creation_epoch  # the revoke is its own epoch

    # The revoke must actually have landed — asserting the epoch alone would
    # also hold for a store that ignored the operation entirely.
    assert store.get_entity(entity.identity_id) is None
    stored = store.get_entity(
        entity.identity_id, options=GraphReadOptions(include_revoked=True)
    )
    assert stored is not None
    assert stored.status is CurationStatus.REVOKED
    assert stored.curation_epoch == creation_epoch

    # ... and the record is still reachable reading AS OF the creation epoch.
    as_of_creation = store.get_entity(
        entity.identity_id,
        options=GraphReadOptions(curation_epoch=creation_epoch, include_revoked=True),
    )
    assert as_of_creation is not None
    assert as_of_creation.identity_id == entity.identity_id
    assert as_of_creation.status is CurationStatus.REVOKED


def test_revoke_identity_of_an_unknown_identity_does_not_commit():
    store = MemoryGraphStore()
    known = make_entity(identity_id=new_identity_id("g1"))
    store.apply(_create_identity_batch("pl_create", known), preconditions=())
    epoch_before = store.current_epoch()

    ghost = new_identity_id("g1")
    result = store.apply(_revoke_identity_batch("pl_ghost", make_entity(identity_id=ghost)),
                         preconditions=())
    assert result.committed is False
    assert result.error is not None and ghost in result.error
    # The store is untouched: no epoch burned, the real entity still visible.
    assert store.current_epoch() == epoch_before
    assert store.get_entity(known.identity_id) is not None


def test_revoke_identity_without_a_string_identity_id_does_not_commit():
    store = MemoryGraphStore()
    batch = GraphMutationBatch(
        plan_id="pl_bad",
        operations=(
            CurationOperation(
                type=CurationOperationType.REVOKE_IDENTITY, payload={"reason": "rollback"}
            ),
        ),
    )
    result = store.apply(batch, preconditions=())
    assert result.committed is False
    assert result.error is not None and "identity_id" in result.error


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
