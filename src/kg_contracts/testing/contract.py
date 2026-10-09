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


def _revoke_identity_op(entity: CanonicalEntity) -> CurationOperation:
    return CurationOperation(
        type=CurationOperationType.REVOKE_IDENTITY,
        payload={"identity_id": entity.identity_id},
        reversal_data=entity.model_dump(mode="python"),
    )


def _restore_identity_op(entity: CanonicalEntity) -> CurationOperation:
    return CurationOperation(
        type=CurationOperationType.RESTORE_IDENTITY,
        payload={"identity_id": entity.identity_id},
        reversal_data=entity.model_dump(mode="python"),
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

    def test_revoked_assertions_hidden_by_default_visible_with_flag(self) -> None:
        # ADR-0025. The mirror of the SUPERSEDED test above, and the reason it
        # exists: `include_revoked` is a read rule every adapter must honour,
        # so an adapter that ignores it must FAIL conformance rather than pass
        # it while silently serving withdrawn records on ordinary reads.
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )

        active = make_assertion(
            subject_identity=entity.identity_id, predicate="height_cm", object_value=200
        )
        revoked = make_assertion(
            subject_identity=entity.identity_id,
            predicate="height_cm",
            object_value=195,
            status=CurationStatus.REVOKED,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_2",
                operations=(_attach_assertion_op(active), _attach_assertion_op(revoked)),
            ),
            preconditions=(),
        )

        default_read = store.assertions_for(entity.identity_id)
        assert [a.assertion_id for a in default_read] == [active.assertion_id]

        full_read = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert {a.assertion_id for a in full_read} == {
            active.assertion_id,
            revoked.assertion_id,
        }

    def test_include_superseded_and_include_revoked_are_independent(self) -> None:
        # ADR-0025: two switches over two different statuses, and neither may
        # reveal the other's records. An adapter that collapsed them into one
        # "show me everything" flag would pass both single-flag tests above
        # and fail here — which is the point of asserting the cross terms.
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )

        active = make_assertion(subject_identity=entity.identity_id, object_value=200)
        superseded = make_assertion(
            subject_identity=entity.identity_id,
            object_value=195,
            status=CurationStatus.SUPERSEDED,
            superseded_at=NOW,
        )
        revoked = make_assertion(
            subject_identity=entity.identity_id,
            object_value=190,
            status=CurationStatus.REVOKED,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_2",
                operations=(
                    _attach_assertion_op(active),
                    _attach_assertion_op(superseded),
                    _attach_assertion_op(revoked),
                ),
            ),
            preconditions=(),
        )

        def ids(*, superseded_flag: bool = False, revoked_flag: bool = False) -> set[str]:
            options = GraphReadOptions(
                include_superseded=superseded_flag, include_revoked=revoked_flag
            )
            return {
                a.assertion_id
                for a in store.assertions_for(entity.identity_id, options=options)
            }

        assert ids() == {active.assertion_id}
        # include_superseded must NOT reveal the revoked record ...
        assert ids(superseded_flag=True) == {active.assertion_id, superseded.assertion_id}
        # ... and include_revoked must NOT reveal the superseded one.
        assert ids(revoked_flag=True) == {active.assertion_id, revoked.assertion_id}
        assert ids(superseded_flag=True, revoked_flag=True) == {
            active.assertion_id,
            superseded.assertion_id,
            revoked.assertion_id,
        }

    def test_get_assertion_returns_active_assertion_by_id(self) -> None:
        # Issue #59: the canonical read surface gains an id-keyed lookup
        # alongside the identity-keyed `assertions_for`, so a consumer can
        # resolve one assertion (KGPS `explain(assertion_id)`) without walking
        # every subject.
        store = _as_testable(self.make_store())
        entity = make_entity()
        assertion = make_assertion(subject_identity=entity.identity_id, object_value=200)
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(_create_identity_op(entity), _attach_assertion_op(assertion)),
            ),
            preconditions=(),
        )

        fetched = store.get_assertion(assertion.assertion_id)
        assert fetched is not None
        assert fetched.assertion_id == assertion.assertion_id
        assert fetched.subject_identity == entity.identity_id
        assert fetched.status is CurationStatus.ACTIVE

    def test_get_assertion_hides_superseded_by_default_and_flag_reveals(self) -> None:
        # The id lookup must apply the same `include_superseded` gate as
        # `assertions_for`: a single-id read cannot surface history the list
        # read hides.
        store = _as_testable(self.make_store())
        entity = make_entity()
        active = make_assertion(subject_identity=entity.identity_id, object_value=200)
        superseded = make_assertion(
            subject_identity=entity.identity_id,
            object_value=195,
            status=CurationStatus.SUPERSEDED,
            superseded_at=NOW,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(
                    _create_identity_op(entity),
                    _attach_assertion_op(active),
                    _attach_assertion_op(superseded),
                ),
            ),
            preconditions=(),
        )

        assert store.get_assertion(superseded.assertion_id) is None
        revealed = store.get_assertion(
            superseded.assertion_id, options=GraphReadOptions(include_superseded=True)
        )
        assert revealed is not None
        assert revealed.status is CurationStatus.SUPERSEDED
        # ... and the flag is not a blanket "show everything": the active one is
        # still returned, but the revoke-shield cross term is separate (below).
        assert store.get_assertion(active.assertion_id) is not None

    def test_get_assertion_honours_subject_revoke_shield(self) -> None:
        # ADR-0026: revoking an identity shields its assertions. The id lookup
        # must honour that shield exactly as `assertions_for` does —
        # `include_revoked` is the only way to reach an assertion belonging to
        # a withdrawn subject.
        store = _as_testable(self.make_store())
        entity = make_entity()
        assertion = make_assertion(subject_identity=entity.identity_id, object_value=200)
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(_create_identity_op(entity), _attach_assertion_op(assertion)),
            ),
            preconditions=(),
        )
        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )

        assert store.get_assertion(assertion.assertion_id) is None
        surfaced = store.get_assertion(
            assertion.assertion_id, options=GraphReadOptions(include_revoked=True)
        )
        assert surfaced is not None
        # The shield is a read rule: the assertion's own status is untouched.
        assert surfaced.status is CurationStatus.ACTIVE

    def test_get_assertion_unknown_id_returns_none(self) -> None:
        store = _as_testable(self.make_store())
        assert store.get_assertion("assertion_does_not_exist") is None

    def test_revoke_identity_hides_entity_and_preserves_creation_epoch(self) -> None:
        # ADR-0025, the rollback contract an adapter must honour for a
        # committed curation run to be reversible: REVOKE_IDENTITY removes the
        # identity from ordinary reads, retains the record, and leaves its
        # ORIGINAL curation_epoch alone. Advancing the epoch would make the
        # identity vanish from epoch-scoped reads of the epoch that created it.
        store = _as_testable(self.make_store())
        entity = make_entity()
        created = store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        creation_epoch = created.new_epoch
        assert creation_epoch is not None
        assert store.get_entity(entity.identity_id) is not None

        revoked = store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        assert revoked.committed is True

        assert store.get_entity(entity.identity_id) is None
        stored = store.get_entity(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert stored is not None
        assert stored.status is CurationStatus.REVOKED
        assert stored.curation_epoch == creation_epoch

        # The cross term, and the property ADR-0025 argues hardest for:
        # history must survive an EPOCH-SCOPED read. Asserting the epoch
        # field alone does not establish that — an adapter can preserve the
        # stamp and still fail to serve the record when the two options are
        # combined, which is precisely how a rolled-back run would lose the
        # history of what it rolled back.
        as_of_creation = store.get_entity(
            entity.identity_id,
            options=GraphReadOptions(curation_epoch=creation_epoch, include_revoked=True),
        )
        assert as_of_creation is not None
        assert as_of_creation.identity_id == entity.identity_id
        # ... and the default read is still empty at that same epoch.
        assert (
            store.get_entity(
                entity.identity_id, options=GraphReadOptions(curation_epoch=creation_epoch)
            )
            is None
        )

    def test_revoke_identity_hides_its_assertions_by_default_and_flag_reveals(self) -> None:
        # Issue #49 / ADR-0026. Revoking an identity must hide that identity's
        # assertions from default reads, not leave them live off a withdrawn
        # identity. They are retained and surface with include_revoked=True.
        store = _as_testable(self.make_store())
        entity = make_entity()
        assertion = make_assertion(subject_identity=entity.identity_id, object_value=200)
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(_create_identity_op(entity), _attach_assertion_op(assertion)),
            ),
            preconditions=(),
        )
        assert [a.assertion_id for a in store.assertions_for(entity.identity_id)] == [
            assertion.assertion_id
        ]

        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )

        assert store.assertions_for(entity.identity_id) == []
        surfaced = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert [a.assertion_id for a in surfaced] == [assertion.assertion_id]
        # Retained, not deleted: the assertion's own status is untouched by
        # the revoke (the shield is a read rule, not an assertion mutation).
        assert surfaced[0].status is CurationStatus.ACTIVE

    def test_revoked_identity_assertion_visibility_flag_cross_terms(self) -> None:
        # Issue #49 / ADR-0026, the cross term. A revoked identity's assertions
        # are hidden by default; include_revoked is what surfaces them, and the
        # assertion's own status still gates it independently. A SUPERSEDED
        # assertion on a REVOKED identity therefore needs BOTH flags:
        # include_superseded alone must not reveal an assertion belonging to a
        # withdrawn identity, and include_revoked alone must not reveal a
        # superseded one. An adapter that collapsed the two switches into one
        # "show everything" flag passes either single-flag test and fails here.
        store = _as_testable(self.make_store())
        entity = make_entity()
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
                plan_id="pl_1",
                operations=(
                    _create_identity_op(entity),
                    _attach_assertion_op(active),
                    _attach_assertion_op(superseded),
                ),
            ),
            preconditions=(),
        )
        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )

        def ids(*, superseded_flag: bool = False, revoked_flag: bool = False) -> set[str]:
            options = GraphReadOptions(
                include_superseded=superseded_flag, include_revoked=revoked_flag
            )
            return {
                a.assertion_id
                for a in store.assertions_for(entity.identity_id, options=options)
            }

        assert ids() == set()
        # include_superseded must NOT reach past the withdrawn identity ...
        assert ids(superseded_flag=True) == set()
        # ... and include_revoked must NOT reveal the superseded assertion.
        assert ids(revoked_flag=True) == {active.assertion_id}
        assert ids(superseded_flag=True, revoked_flag=True) == {
            active.assertion_id,
            superseded.assertion_id,
        }

    def test_create_and_revoke_identity_in_one_batch_commits_a_tombstone(self) -> None:
        # Issue #50a / ADR-0026. Operations apply in order, so a REVOKE naming
        # an identity minted earlier in the same batch is coherent: it commits
        # a tombstone at this batch's epoch rather than failing with a
        # misleading "unknown identity". The attached assertion is shielded
        # with the identity and surfaces only under include_revoked.
        store = _as_testable(self.make_store())
        entity = make_entity()
        assertion = make_assertion(subject_identity=entity.identity_id)
        epoch_before = store.current_epoch()
        result = store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(
                    _create_identity_op(entity),
                    _attach_assertion_op(assertion),
                    _revoke_identity_op(entity),
                ),
            ),
            preconditions=(),
        )
        assert result.committed is True
        assert result.new_epoch == epoch_before + 1
        assert store.current_epoch() == result.new_epoch

        assert store.get_entity(entity.identity_id) is None
        assert store.assertions_for(entity.identity_id) == []
        stored = store.get_entity(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert stored is not None
        assert stored.status is CurationStatus.REVOKED
        surfaced = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert [a.assertion_id for a in surfaced] == [assertion.assertion_id]

    def test_second_revoke_of_already_revoked_identity_does_not_commit(self) -> None:
        # Issue #50b / ADR-0026. A revoke with nothing left to revoke must fail
        # loudly rather than commit a no-op epoch that looks like it did
        # something — the canonical-graph analogue of ADR-0013's ledger
        # `revoke()`, adapted to the `CommitResult` contract. The store is
        # untouched: no epoch consumed, the tombstone intact.
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        first = store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        assert first.committed is True
        epoch_after_first = store.current_epoch()

        second = store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        assert second.committed is False
        assert second.new_epoch is None
        assert second.error is not None and entity.identity_id in second.error
        assert store.current_epoch() == epoch_after_first
        stored = store.get_entity(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert stored is not None and stored.status is CurationStatus.REVOKED

    def test_restore_identity_undoes_a_revoke_and_preserves_creation_epoch(self) -> None:
        # Issue #51 / ADR-0027. The reverse leg ADR-0025 lacked as an
        # operation: RESTORE_IDENTITY flips REVOKED back to ACTIVE *without*
        # re-stamping the creation epoch, so the identity is findable again as
        # of the epoch that created it. Contrast the CREATE_IDENTITY replay
        # pinned as a bound by
        # `test_revoke_round_trip_restores_the_identity_but_not_its_creation_epoch`.
        store = _as_testable(self.make_store())
        entity = make_entity()
        created = store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        creation_epoch = created.new_epoch
        assert creation_epoch is not None

        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        assert store.get_entity(entity.identity_id) is None

        restored = store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )
        assert restored.committed is True
        assert restored.new_epoch == creation_epoch + 2

        live = store.get_entity(entity.identity_id)
        assert live is not None
        assert live.status is CurationStatus.ACTIVE
        # The restore is its own committed epoch, but the record keeps the
        # epoch that created it — that is the whole point of the type.
        assert live.curation_epoch == creation_epoch

        # The property that matters: a default read *as of the creation epoch*
        # finds the identity again.
        as_of_creation = store.get_entity(
            entity.identity_id, options=GraphReadOptions(curation_epoch=creation_epoch)
        )
        assert as_of_creation is not None
        assert as_of_creation.identity_id == entity.identity_id

    def test_restore_identity_lifts_the_assertion_shield(self) -> None:
        # ADR-0026 shields a revoked identity's assertions from default reads;
        # ADR-0027's restore is what lifts that shield, without mutating any
        # assertion's own status.
        store = _as_testable(self.make_store())
        entity = make_entity()
        active = make_assertion(subject_identity=entity.identity_id, object_value=200)
        superseded = make_assertion(
            subject_identity=entity.identity_id,
            object_value=195,
            status=CurationStatus.SUPERSEDED,
            superseded_at=NOW,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(
                    _create_identity_op(entity),
                    _attach_assertion_op(active),
                    _attach_assertion_op(superseded),
                ),
            ),
            preconditions=(),
        )
        assert [a.assertion_id for a in store.assertions_for(entity.identity_id)] == [
            active.assertion_id
        ]

        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        assert store.assertions_for(entity.identity_id) == []

        store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )
        assert [a.assertion_id for a in store.assertions_for(entity.identity_id)] == [
            active.assertion_id
        ]
        surfaced = store.assertions_for(
            entity.identity_id, options=GraphReadOptions(include_superseded=True)
        )
        by_id = {a.assertion_id: a for a in surfaced}
        assert by_id[active.assertion_id].status is CurationStatus.ACTIVE
        assert by_id[superseded.assertion_id].status is CurationStatus.SUPERSEDED

    def test_restore_identity_of_active_identity_does_not_commit(self) -> None:
        # Issue #51 / ADR-0027: the mirror of the double-revoke rule. A restore
        # with nothing to restore fails loudly, names the identity, and
        # consumes no epoch.
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        epoch_before = store.current_epoch()

        result = store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )
        assert result.committed is False
        assert result.new_epoch is None
        assert result.error is not None and entity.identity_id in result.error
        assert store.current_epoch() == epoch_before
        stored = store.get_entity(entity.identity_id)
        assert stored is not None and stored.status is CurationStatus.ACTIVE

    def test_second_restore_of_already_restored_identity_does_not_commit(self) -> None:
        # Double restore, the exact analogue of double revoke (#50b): a no-op
        # must not masquerade as a committed status change.
        store = _as_testable(self.make_store())
        entity = make_entity()
        store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        first = store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )
        assert first.committed is True
        epoch_after_first = store.current_epoch()

        second = store.apply(
            GraphMutationBatch(plan_id="pl_4", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )
        assert second.committed is False
        assert second.new_epoch is None
        assert second.error is not None and entity.identity_id in second.error
        assert store.current_epoch() == epoch_after_first

    def test_revoke_restore_revoke_cycle_returns_to_revoked_at_the_creation_epoch(self) -> None:
        # The sequence issue #51 names: revoke -> restore -> revoke must work,
        # landing back on REVOKED with the original creation epoch intact.
        store = _as_testable(self.make_store())
        entity = make_entity()
        created = store.apply(
            GraphMutationBatch(plan_id="pl_1", operations=(_create_identity_op(entity),)),
            preconditions=(),
        )
        creation_epoch = created.new_epoch
        assert creation_epoch is not None

        assert store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        ).committed
        assert store.get_entity(entity.identity_id) is None

        assert store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        ).committed
        assert store.get_entity(entity.identity_id) is not None

        assert store.apply(
            GraphMutationBatch(plan_id="pl_4", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        ).committed
        assert store.get_entity(entity.identity_id) is None
        stored = store.get_entity(
            entity.identity_id, options=GraphReadOptions(include_revoked=True)
        )
        assert stored is not None
        assert stored.status is CurationStatus.REVOKED
        assert stored.curation_epoch == creation_epoch

    def test_restore_identity_assertion_visibility_flag_cross_terms(self) -> None:
        # After a restore the *subject* shield is gone, so the two visibility
        # switches behave exactly as for a never-revoked identity — restoring
        # lifts the shield, it does not collapse the flags. An assertion whose
        # own status is REVOKED still needs include_revoked; a SUPERSEDED one
        # still needs include_superseded.
        store = _as_testable(self.make_store())
        entity = make_entity()
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
        revoked = make_assertion(
            subject_identity=entity.identity_id,
            predicate="height_cm",
            object_value=190,
            status=CurationStatus.REVOKED,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(
                    _create_identity_op(entity),
                    _attach_assertion_op(active),
                    _attach_assertion_op(superseded),
                    _attach_assertion_op(revoked),
                ),
            ),
            preconditions=(),
        )
        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(entity),)),
            preconditions=(),
        )
        store.apply(
            GraphMutationBatch(plan_id="pl_3", operations=(_restore_identity_op(entity),)),
            preconditions=(),
        )

        def ids(*, superseded_flag: bool = False, revoked_flag: bool = False) -> set[str]:
            options = GraphReadOptions(
                include_superseded=superseded_flag, include_revoked=revoked_flag
            )
            return {
                a.assertion_id
                for a in store.assertions_for(entity.identity_id, options=options)
            }

        assert ids() == {active.assertion_id}
        assert ids(superseded_flag=True) == {active.assertion_id, superseded.assertion_id}
        assert ids(revoked_flag=True) == {active.assertion_id, revoked.assertion_id}
        assert ids(superseded_flag=True, revoked_flag=True) == {
            active.assertion_id,
            superseded.assertion_id,
            revoked.assertion_id,
        }

    def test_assertion_on_live_subject_with_revoked_object_stays_visible_by_default(self) -> None:
        # Owner decision (a), ADR-0027. The ADR-0026 shield is on the SUBJECT
        # identity only: an assertion whose subject is live remains visible on a
        # default read even when its object_identity is revoked. Withdrawing the
        # object is not a retraction of the relation. neighborhood() keeps its
        # current behaviour and still drops the revoked target — a revoked node
        # is not a live neighbour, which does not contradict (a) because the
        # assertion itself is still served by assertions_for().
        store = _as_testable(self.make_store())
        subject = make_entity(key="a")
        target = make_entity(key="b")
        relation = make_assertion(
            subject_identity=subject.identity_id,
            object_value=None,
            object_identity=target.identity_id,
        )
        store.apply(
            GraphMutationBatch(
                plan_id="pl_1",
                operations=(
                    _create_identity_op(subject),
                    _create_identity_op(target),
                    _attach_assertion_op(relation),
                ),
            ),
            preconditions=(),
        )
        assert [a.assertion_id for a in store.assertions_for(subject.identity_id)] == [
            relation.assertion_id
        ]
        assert [e.identity_id for e in store.neighborhood(subject.identity_id)] == [
            target.identity_id
        ]

        store.apply(
            GraphMutationBatch(plan_id="pl_2", operations=(_revoke_identity_op(target),)),
            preconditions=(),
        )

        # (a): the live subject's assertion is NOT shielded by the object revoke.
        assert [a.assertion_id for a in store.assertions_for(subject.identity_id)] == [
            relation.assertion_id
        ]
        assert store.neighborhood(subject.identity_id) == []
        assert [
            e.identity_id
            for e in store.neighborhood(
                subject.identity_id, options=GraphReadOptions(include_revoked=True)
            )
        ] == [target.identity_id]

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
