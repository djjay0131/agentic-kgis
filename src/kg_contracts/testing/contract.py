"""Reusable pytest-style contract suites (spec §10.2).

*Phase-0 lesson (vttsi contract-test discipline):* every implementation of
a port must pass the same reusable suite unchanged. Subclass one of these,
implement the single `make_*` factory method it asks for, and every test
below runs against your adapter for free — memory (Task 18), Neo4j,
Spanner, and any adopter repo's own adapter all share this exact suite.

`MemoryReviewQueue` — the reference list-backed `ReviewQueue` — lives
here rather than in `memory.py` because it is small enough to sit next to
the suite it satisfies, and downstream repos importing the suites already
need this module.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, cast, runtime_checkable

import pytest

from kg_contracts.assertions import Assertion, CanonicalEntity, CurationStatus
from kg_contracts.curation import (
    CurationOperation,
    CurationOperationType,
    Precondition,
    ProcessingState,
    ReviewAction,
    ReviewDecision,
    ReviewItem,
)
from kg_contracts.evidence import ValidPeriod
from kg_contracts.stores import (
    CandidateSink,
    CapabilityDeclaring,
    GraphMutationBatch,
    GraphMutationStore,
    GraphReadOptions,
    LedgerReader,
    LedgerReadOptions,
    SubmissionStatus,
    TemporalGraphReader,
    UnsupportedCapabilityError,
)
from kg_contracts.testing.factories import make_assertion, make_entity, make_entity_candidate

NOW: datetime = datetime(2026, 7, 12, tzinfo=UTC)


@runtime_checkable
class _TestableGraphStore(GraphMutationStore, TemporalGraphReader, CapabilityDeclaring, Protocol):
    """Type-only union of everything this suite drives on an adapter.

    `GraphMutationStoreContract.make_store()` is typed `-> GraphMutationStore`
    (the executor-facing surface, matching the brief's port signature
    exactly), but the suite exercises the read and capability surface of
    the same object too — every real adapter under test (`MemoryGraphStore`,
    and later Neo4j/Spanner) implements all three. Test bodies `cast` to
    this combined protocol once per method rather than widening
    `make_store()`'s public return type.
    """


def _as_testable(store: GraphMutationStore) -> _TestableGraphStore:
    return cast(_TestableGraphStore, store)


def _create_identity_op(entity: CanonicalEntity) -> CurationOperation:
    return CurationOperation(
        type=CurationOperationType.CREATE_IDENTITY,
        payload=entity.model_dump(mode="python"),
    )


def _attach_assertion_op(assertion: Assertion) -> CurationOperation:
    return CurationOperation(
        type=CurationOperationType.ATTACH_ASSERTION,
        payload=assertion.model_dump(mode="python"),
    )


class MemoryReviewQueue:
    """List-backed reference `ReviewQueue` (spec §7.6).

    `pending()` preserves enqueue order; `resolve()` removes the item from
    `pending()` and appends the decision to that item's `history()` —
    resolving the same item more than once (e.g. an `EDIT` pass followed
    by a final `APPROVE`) is allowed and both decisions are kept.
    """

    def __init__(self) -> None:
        self._pending: dict[str, ReviewItem] = {}
        self._history: dict[str, list[ReviewDecision]] = {}

    def enqueue(self, item: ReviewItem) -> str:
        self._pending[item.item_id] = item
        return item.item_id

    def pending(self, limit: int = 50) -> list[ReviewItem]:
        return list(self._pending.values())[:limit]

    def resolve(self, decision: ReviewDecision) -> None:
        self._pending.pop(decision.item_id, None)
        self._history.setdefault(decision.item_id, []).append(decision)

    def history(self, item_id: str) -> list[ReviewDecision]:
        return list(self._history.get(item_id, []))


class CandidateSinkContract:
    """Subclass and implement `make_sink()` (spec §10.2)."""

    def make_sink(self) -> CandidateSink:
        raise NotImplementedError

    def test_submit_all_received(self) -> None:
        sink = self.make_sink()
        candidates = [make_entity_candidate(key="a"), make_entity_candidate(key="b")]
        result = sink.submit(candidates)
        assert [o.status for o in result.outcomes] == [
            SubmissionStatus.RECEIVED,
            SubmissionStatus.RECEIVED,
        ]

    def test_resubmit_same_semantic_key_is_duplicate(self) -> None:
        sink = self.make_sink()
        first = make_entity_candidate(key="dup")
        second = make_entity_candidate(key="dup")
        sink.submit([first])
        result = sink.submit([second])
        assert result.outcomes[0].status == SubmissionStatus.DUPLICATE

    def test_outcomes_carry_trace_ids(self) -> None:
        sink = self.make_sink()
        candidate = make_entity_candidate(key="c")
        result = sink.submit([candidate])
        assert result.outcomes[0].trace_id == candidate.trace_id

    def test_counts_consistent_with_outcomes(self) -> None:
        sink = self.make_sink()
        sink.submit([make_entity_candidate(key="seed")])
        result = sink.submit(
            [
                make_entity_candidate(key="fresh-1"),
                make_entity_candidate(key="fresh-2"),
                make_entity_candidate(key="seed"),
            ]
        )
        assert result.counts() == {
            SubmissionStatus.RECEIVED: 2,
            SubmissionStatus.DUPLICATE: 1,
        }


@runtime_checkable
class _TestableLedger(CandidateSink, LedgerReader, Protocol):
    """Type-only union: a candidate ledger is *written* via `CandidateSink`
    and *read* via `LedgerReader` — two separate protocols over one store
    (ADR-0006, ADR-0011). `make_ledger()` is typed `-> CandidateSink` (the
    write port); the suite `cast`s to this union to exercise reads, exactly
    as `GraphMutationStoreContract` does for the canonical store.
    """


def _as_ledger(sink: CandidateSink) -> _TestableLedger:
    return cast(_TestableLedger, sink)


class LedgerReaderContract:
    """Subclass and implement `make_ledger()` (spec §10.2, ADR-0011).

    Validates the *separate* ledger read surface: any store that is both a
    `CandidateSink` and a `LedgerReader` must round-trip received candidates
    through the ledger read path with their `ProcessingState`, honor the
    state/graph filters, and never leak that data through a canonical
    `GraphReader` (the last is guaranteed structurally by the protocol
    split, tested in `test_stores_read.py`).
    """

    def make_ledger(self) -> CandidateSink:
        raise NotImplementedError

    def test_received_candidate_appears_in_ledger_with_received_state(self) -> None:
        ledger = _as_ledger(self.make_ledger())
        candidate = make_entity_candidate(key="lr-1")
        ledger.submit([candidate])
        entries = ledger.ledger_entries()
        assert [e.candidate.candidate_id for e in entries] == [candidate.candidate_id]
        assert entries[0].processing_state is ProcessingState.RECEIVED
        assert entries[0].received_at == candidate.created_at

    def test_ledger_entry_lookup_by_candidate_id(self) -> None:
        ledger = _as_ledger(self.make_ledger())
        candidate = make_entity_candidate(key="lr-2")
        ledger.submit([candidate])
        found = ledger.ledger_entry(candidate.candidate_id)
        assert found is not None
        assert found.candidate.candidate_id == candidate.candidate_id
        assert ledger.ledger_entry("cand_does_not_exist") is None

    def test_processing_state_filter_excludes_non_matching_states(self) -> None:
        ledger = _as_ledger(self.make_ledger())
        ledger.submit([make_entity_candidate(key="lr-3")])
        # Received candidates sit in RECEIVED; filtering to another state hides them.
        hidden = ledger.ledger_entries(
            LedgerReadOptions(processing_states=(ProcessingState.REVIEW_PENDING,))
        )
        assert hidden == []
        shown = ledger.ledger_entries(
            LedgerReadOptions(processing_states=(ProcessingState.RECEIVED,))
        )
        assert len(shown) == 1

    def test_graph_id_filter_scopes_entries(self) -> None:
        ledger = _as_ledger(self.make_ledger())
        ledger.submit([make_entity_candidate(graph_id="g1", key="x")])
        ledger.submit([make_entity_candidate(graph_id="g2", key="y")])
        scoped = ledger.ledger_entries(LedgerReadOptions(graph_id="g1"))
        assert [e.candidate.graph_id for e in scoped] == ["g1"]


class GraphMutationStoreContract:
    """Subclass and implement `make_store()` (spec §10.2)."""

    def make_store(self) -> GraphMutationStore:
        raise NotImplementedError

    def test_create_and_attach_commits_and_returns_new_epoch(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        assertion = make_assertion(subject_identity=entity.identity_id)
        batch = GraphMutationBatch(
            plan_id="pl_1",
            operations=(_create_identity_op(entity), _attach_assertion_op(assertion)),
        )
        epoch_before = store.current_epoch()
        result = store.apply(batch, preconditions=())
        assert result.committed is True
        assert result.new_epoch == epoch_before + 1
        assert store.current_epoch() == result.new_epoch

    def test_entity_readable_after_commit_not_before(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        assert store.get_entity(entity.identity_id) is None
        result = store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        fetched = store.get_entity(entity.identity_id)
        assert fetched is not None
        assert fetched.identity_id == entity.identity_id
        assert fetched.entity_type == entity.entity_type
        assert fetched.aliases == entity.aliases
        assert fetched.curation_epoch == result.new_epoch

    def test_failed_entity_version_precondition_blocks_commit_atomically(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )

        assertion = make_assertion(subject_identity=entity.identity_id)
        bad_precondition = Precondition(
            kind="entity_version", subject=entity.identity_id, expected="99"
        )
        epoch_before = store.current_epoch()
        result = store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_attach_assertion_op(assertion),)),
            preconditions=(bad_precondition,),
        )

        assert result.committed is False
        assert result.failed_preconditions == (bad_precondition,)
        assert store.current_epoch() == epoch_before
        assert store.assertions_for(entity.identity_id) == []

    def test_superseded_assertions_hidden_by_default_visible_with_flag(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )

        active = make_assertion(
            subject_identity=entity.identity_id, predicate="height_cm", object_value=200
        )
        superseded = make_assertion(
            subject_identity=entity.identity_id,
            predicate="height_cm",
            object_value=195,
            status=CurationStatus.SUPERSEDED,
            superseded_at=NOW,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_2",
                operations=(_attach_assertion_op(active), _attach_assertion_op(superseded)),
            ),
            preconditions=(),
        )

        default_read = store.assertions_for(entity.identity_id)
        assert [a.assertion_id for a in default_read] == [active.assertion_id]

        full_read = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(include_superseded=True)
        )
        assert {a.assertion_id for a in full_read} == {
            active.assertion_id,
            superseded.assertion_id,
        }

    def test_snapshot_read_at_old_epoch_hides_later_records(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        result1 = store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        old_epoch = result1.new_epoch
        assert old_epoch is not None

        later_assertion = make_assertion(subject_identity=entity.identity_id)
        store.apply(
            GraphMutationBatch(
                plan_id="pl_2", operations=(_attach_assertion_op(later_assertion),)
            ),
            preconditions=(),
        )

        snapshot = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(curation_epoch=old_epoch)
        )
        assert snapshot == []

        latest = store.assertions_for(entity.identity_id)
        assert [a.assertion_id for a in latest] == [later_assertion.assertion_id]

    def test_capability_conformance_for_temporal_options(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        caps = store.capabilities()
        valid_period = ValidPeriod(
            valid_from=NOW - timedelta(days=1), valid_to=NOW + timedelta(days=1)
        )
        assertion = make_assertion(subject_identity=entity.identity_id, valid_period=valid_period)
        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_attach_assertion_op(assertion),)),
            preconditions=(),
        )

        if not caps.supports_temporal_queries:
            with pytest.raises(UnsupportedCapabilityError):
                store.assertions_for(entity.identity_id, options=GraphReadOptions(valid_at=NOW))
            return

        within = store.assertions_for(entity.identity_id, options=GraphReadOptions(valid_at=NOW))
        assert [a.assertion_id for a in within] == [assertion.assertion_id]

        outside = store.assertions_for(
            entity.identity_id,
            options=GraphReadOptions(valid_at=NOW + timedelta(days=30)),
        )
        assert outside == []

    def test_transaction_at_filters_by_half_open_recorded_superseded_window(self) -> None:
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        caps = store.capabilities()

        # An active assertion recorded at NOW, never superseded.
        active = make_assertion(
            subject_identity=entity.identity_id, predicate="height_cm", recorded_at=NOW
        )
        # A superseded assertion whose transaction-time window is
        # [NOW - 2d, NOW): recorded earlier, retired at NOW.
        retired = make_assertion(
            subject_identity=entity.identity_id,
            predicate="weight_kg",
            object_value=90,
            status=CurationStatus.SUPERSEDED,
            recorded_at=NOW - timedelta(days=2),
            superseded_at=NOW,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_2",
                operations=(_attach_assertion_op(active), _attach_assertion_op(retired)),
            ),
            preconditions=(),
        )

        if not caps.supports_temporal_queries:
            with pytest.raises(UnsupportedCapabilityError):
                store.assertions_for(
                    entity.identity_id, options=GraphReadOptions(transaction_at=NOW)
                )
            return

        # Before the active assertion's recorded_at: not yet in the graph.
        before = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(transaction_at=NOW - timedelta(days=1))
        )
        assert [a.assertion_id for a in before] == []

        # At/after recorded_at: the active assertion is visible (window is
        # half-open at the recorded_at end, i.e. transaction_at >= recorded_at).
        at_now = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(transaction_at=NOW)
        )
        assert [a.assertion_id for a in at_now] == [active.assertion_id]

        # Inside the retired assertion's [recorded_at, superseded_at) window,
        # with include_superseded to see past the status filter: visible.
        inside_retired = store.assertions_for(
            entity.identity_id,
            options=GraphReadOptions(
                transaction_at=NOW - timedelta(days=1), include_superseded=True
            ),
        )
        assert {a.assertion_id for a in inside_retired} == {retired.assertion_id}

        # At/after superseded_at the retired assertion drops out of the
        # transaction-time view (half-open at the superseded_at end).
        at_superseded = store.assertions_for(
            entity.identity_id,
            options=GraphReadOptions(transaction_at=NOW, include_superseded=True),
        )
        assert retired.assertion_id not in {a.assertion_id for a in at_superseded}


class ReviewQueueContract:
    """Subclass and implement `make_queue()` (spec §10.2)."""

    def make_queue(self) -> MemoryReviewQueue:
        raise NotImplementedError

    def test_enqueue_pending_ordering(self) -> None:
        queue = self.make_queue()
        first = ReviewItem(kind="entity_merge", payload={"a": 1}, reason="r1", enqueued_at=NOW)
        second = ReviewItem(kind="entity_merge", payload={"a": 2}, reason="r2", enqueued_at=NOW)
        queue.enqueue(first)
        queue.enqueue(second)
        assert [item.item_id for item in queue.pending()] == [first.item_id, second.item_id]

    def test_resolve_removes_from_pending(self) -> None:
        queue = self.make_queue()
        item = ReviewItem(kind="entity_merge", payload={}, reason="r", enqueued_at=NOW)
        queue.enqueue(item)
        decision = ReviewDecision(
            item_id=item.item_id, action=ReviewAction.APPROVE, actor="reviewer", decided_at=NOW
        )
        queue.resolve(decision)
        assert queue.pending() == []

    def test_history_returns_decisions_in_order(self) -> None:
        queue = self.make_queue()
        item = ReviewItem(kind="entity_merge", payload={}, reason="r", enqueued_at=NOW)
        queue.enqueue(item)
        first_decision = ReviewDecision(
            item_id=item.item_id,
            action=ReviewAction.EDIT,
            actor="a1",
            edited_payload={"note": "first pass"},
            decided_at=NOW,
        )
        second_decision = ReviewDecision(
            item_id=item.item_id,
            action=ReviewAction.APPROVE,
            actor="a2",
            decided_at=NOW + timedelta(minutes=1),
        )
        queue.resolve(first_decision)
        queue.resolve(second_decision)
        assert queue.history(item.item_id) == [first_decision, second_decision]

    def test_edit_decision_round_trips_edited_payload(self) -> None:
        queue = self.make_queue()
        item = ReviewItem(
            kind="entity_merge", payload={"display_name": "old"}, reason="r", enqueued_at=NOW
        )
        queue.enqueue(item)
        decision = ReviewDecision(
            item_id=item.item_id,
            action=ReviewAction.EDIT,
            actor="reviewer",
            edited_payload={"display_name": "new"},
            decided_at=NOW,
        )
        queue.resolve(decision)
        [recorded] = queue.history(item.item_id)
        assert recorded.edited_payload == {"display_name": "new"}
