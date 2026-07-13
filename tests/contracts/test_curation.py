from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.assertions import CurationStatus
from kg_contracts.curation import (
    AuditRecord,
    CurationOperation,
    CurationOperationType,
    CurationPlan,
    FailureKind,
    Precondition,
    ProcessingState,
    ResolutionDecision,
    ReviewAction,
    ReviewDecision,
    ReviewItem,
    ReviewQueue,
    ValidationDecision,
)
from kg_contracts.policy import AdjudicationRoute

NOW = datetime(2026, 7, 12, tzinfo=UTC)


def test_processing_state_has_exactly_eleven_members_disjoint_from_curation_status():
    # Owner ruling R1: SUPERSEDED renamed to OBSOLETE (a candidate obsoleted
    # by a newer candidate) so the ledger state machine and the
    # canonical-graph CurationStatus enum share no values.
    expected = {
        "RECEIVED",
        "VALIDATED",
        "INVALID",
        "BLOCKED",
        "RESOLUTION_PENDING",
        "REVIEW_PENDING",
        "ACCEPTED",
        "REJECTED",
        "OBSOLETE",
        "RETRYABLE_ERROR",
        "PERMANENT_ERROR",
    }
    assert set(ProcessingState.__members__) == expected
    assert len(expected) == 11
    processing_values = {s.value for s in ProcessingState}
    curation_values = {s.value for s in CurationStatus}
    assert processing_values.isdisjoint(curation_values)


def test_validation_decision_valid_false_requires_failure_kind():
    with pytest.raises(ValidationError, match="failure_kind"):
        ValidationDecision(
            candidate_id="cand_1",
            valid=False,
            failure_kind=None,
            reasons=("bad row",),
            policy_version="1",
            trace_id="trace_1",
        )


def test_validation_decision_valid_true_forbids_failure_kind():
    with pytest.raises(ValidationError, match="failure_kind"):
        ValidationDecision(
            candidate_id="cand_1",
            valid=True,
            failure_kind=FailureKind.BAD_DATA,
            reasons=(),
            policy_version="1",
            trace_id="trace_1",
        )


def test_validation_decision_valid_true_without_failure_kind_ok():
    decision = ValidationDecision(
        candidate_id="cand_1",
        valid=True,
        failure_kind=None,
        reasons=(),
        policy_version="1",
        trace_id="trace_1",
    )
    assert decision.valid is True


def test_validation_decision_valid_false_with_failure_kind_ok():
    # the failure-recording case the class exists for: valid=False must
    # construct when a failure_kind is supplied, and preserve it.
    decision = ValidationDecision(
        candidate_id="cand_1",
        valid=False,
        failure_kind=FailureKind.BAD_DATA,
        reasons=("bad row",),
        policy_version="1",
        trace_id="trace_1",
    )
    assert decision.valid is False
    assert decision.failure_kind is FailureKind.BAD_DATA


def test_resolution_decision_requires_nonempty_score_vector():
    with pytest.raises(ValidationError, match="score_vector"):
        ResolutionDecision(
            candidate_id="cand_1",
            resolved_identity="id_1",
            create_new_identity=False,
            route=AdjudicationRoute.AUTO,
            score_vector={},
            matcher_version="v1",
            snapshot_version="17",
            trace_id="trace_1",
        )


def test_resolution_decision_requires_snapshot_version():
    with pytest.raises(ValidationError, match="snapshot_version"):
        ResolutionDecision(
            candidate_id="cand_1",
            resolved_identity="id_1",
            create_new_identity=False,
            route=AdjudicationRoute.AUTO,
            score_vector={"name_similarity": 0.9},
            matcher_version="v1",
            snapshot_version="",
            trace_id="trace_1",
        )


def test_resolution_decision_valid_construction():
    decision = ResolutionDecision(
        candidate_id="cand_1",
        resolved_identity="id_1",
        create_new_identity=False,
        route=AdjudicationRoute.AUTO,
        score_vector={"name_similarity": 0.9},
        matcher_version="v1",
        snapshot_version="17",
        trace_id="trace_1",
    )
    assert decision.score_vector == {"name_similarity": 0.9}


def test_curation_plan_requires_at_least_one_candidate_id():
    with pytest.raises(ValidationError):
        CurationPlan(
            candidate_ids=(),
            snapshot_version="17",
            operations=(),
            preconditions=(),
            evidence_ids=(),
            policy_version="1",
        )


def test_curation_plan_full_json_round_trip():
    op = CurationOperation(
        type=CurationOperationType.MERGE_IDENTITIES,
        payload={"left": "id_1", "right": "id_2"},
        reversal_data={"pre_merge_members": ["id_1", "id_2"]},
    )
    precondition = Precondition(kind="cluster_version", subject="id_1", expected="17")
    plan = CurationPlan(
        candidate_ids=("cand_1", "cand_2"),
        snapshot_version="17",
        operations=(op,),
        preconditions=(precondition,),
        evidence_ids=("ev_1",),
        policy_version="1",
    )
    assert CurationPlan.model_validate_json(plan.model_dump_json()) == plan


def test_curation_operation_carries_reversal_data_and_is_frozen():
    op = CurationOperation(
        type=CurationOperationType.SPLIT_IDENTITY,
        payload={"identity_id": "id_1"},
        reversal_data={"pre_split_members": ["id_1"]},
    )
    assert op.operation_id.startswith("op_")
    assert op.reversal_data == {"pre_split_members": ["id_1"]}
    with pytest.raises(ValidationError):
        op.payload = {}  # frozen


def test_review_action_has_all_eight_operations():
    assert {a.value for a in ReviewAction} == {
        "APPROVE",
        "REJECT",
        "EDIT",
        "SPLIT",
        "RELABEL",
        "LINK",
        "MERGE_ELSEWHERE",
        "SAME_CONCEPT_DIFFERENT_SCOPE",
    }


def test_review_decision_edit_requires_edited_payload():
    with pytest.raises(ValidationError, match="edited_payload"):
        ReviewDecision(
            item_id="rv_1",
            action=ReviewAction.EDIT,
            actor="reviewer_1",
            edited_payload=None,
            note=None,
            decided_at=NOW,
        )


def test_review_decision_approve_without_edited_payload_ok():
    decision = ReviewDecision(
        item_id="rv_1",
        action=ReviewAction.APPROVE,
        actor="reviewer_1",
        decided_at=NOW,
    )
    assert decision.edited_payload is None


def test_review_decision_edit_with_edited_payload_ok():
    # the edit-recording case: action=EDIT must construct when an
    # edited_payload is supplied, and preserve it.
    decision = ReviewDecision(
        item_id="rv_1",
        action=ReviewAction.EDIT,
        actor="reviewer_1",
        edited_payload={"display_name": "corrected"},
        decided_at=NOW,
    )
    assert decision.action is ReviewAction.EDIT
    assert decision.edited_payload == {"display_name": "corrected"}


def test_duck_typed_fake_satisfies_review_queue():
    class FakeReviewQueue:
        def __init__(self) -> None:
            self._items: dict[str, ReviewItem] = {}
            self._history: dict[str, list[ReviewDecision]] = {}

        def enqueue(self, item: ReviewItem) -> str:
            self._items[item.item_id] = item
            return item.item_id

        def pending(self, limit: int = 50) -> list[ReviewItem]:
            return list(self._items.values())[:limit]

        def resolve(self, decision: ReviewDecision) -> None:
            self._history.setdefault(decision.item_id, []).append(decision)

        def history(self, item_id: str) -> list[ReviewDecision]:
            return self._history.get(item_id, [])

    fake = FakeReviewQueue()
    assert isinstance(fake, ReviewQueue)

    item = ReviewItem(
        kind="entity_merge",
        payload={"candidate_id": "cand_1"},
        reason="ambiguous match",
        enqueued_at=NOW,
    )
    assert item.item_id.startswith("rv_")
    assert item.priority == "P3"
    item_id = fake.enqueue(item)
    assert fake.pending() == [item]

    decision = ReviewDecision(
        item_id=item_id,
        action=ReviewAction.APPROVE,
        actor="reviewer_1",
        decided_at=NOW,
    )
    fake.resolve(decision)
    assert fake.history(item_id) == [decision]


def test_audit_record_is_frozen_and_immutable():
    record = AuditRecord(
        operation_id="op_1",
        decided_by="reviewer_1",
        score_vector={"name_similarity": 0.9},
        evidence_ids=("ev_1",),
        policy_version="1",
        trace_id="trace_1",
        recorded_at=NOW,
    )
    assert record.audit_id.startswith("au_")
    with pytest.raises(ValidationError):
        record.decided_by = "someone_else"
