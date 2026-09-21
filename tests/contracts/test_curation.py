import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.assertions import CurationStatus
from kg_contracts.curation import (
    INVERSE_OPERATION_TYPES,
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
from kg_contracts.policy import AdjudicationRoute, IdentityDisposition

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


def test_curation_operation_payload_is_frozen_and_round_trips():
    op = CurationOperation(
        type=CurationOperationType.CREATE_IDENTITY,
        payload={"assertion_id": "a1", "value": 3},
    )
    with pytest.raises(TypeError):
        op.payload["value"] = 999  # type: ignore[index]
    with pytest.raises(TypeError):
        op.reversal_data["x"] = 1  # type: ignore[index]
    dumped = op.model_dump_json()
    assert json.loads(dumped)["payload"] == {"assertion_id": "a1", "value": 3}
    assert CurationOperation.model_validate_json(dumped) == op


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
    with pytest.raises(TypeError):
        record.score_vector["name_similarity"] = 0.0  # type: ignore[index]


def test_curation_operation_omitted_reversal_data_still_frozen():
    # Regression: reversal_data used to rely on a per-field
    # validate_default=True to force validation of the default_factory=dict
    # value. That flag is now hoisted to the model config, so an omitted
    # reversal_data must still validate to an immutable mapping, not a
    # plain, mutable dict.
    op = CurationOperation(
        type=CurationOperationType.CREATE_IDENTITY,
        payload={"assertion_id": "a1"},
    )
    assert op.reversal_data == {}
    with pytest.raises(TypeError):
        op.reversal_data["x"] = 1  # type: ignore[index]


def test_resolution_decision_score_vector_is_frozen():
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
    with pytest.raises(TypeError):
        decision.score_vector["name_similarity"] = 0.0  # type: ignore[index]


def test_review_item_payload_is_frozen():
    item = ReviewItem(
        kind="entity_merge",
        payload={"candidate_id": "cand_1"},
        reason="ambiguous match",
        enqueued_at=NOW,
    )
    with pytest.raises(TypeError):
        item.payload["candidate_id"] = "cand_2"  # type: ignore[index]


def test_review_decision_edited_payload_is_frozen():
    decision = ReviewDecision(
        item_id="rv_1",
        action=ReviewAction.EDIT,
        actor="reviewer_1",
        edited_payload={"display_name": "corrected"},
        decided_at=NOW,
    )
    with pytest.raises(TypeError):
        decision.edited_payload["display_name"] = "other"  # type: ignore[index]


# --- ADR-0024: ResolutionDecision projects onto the adjudication gate -------


def _decision(**kw: object) -> ResolutionDecision:
    base: dict[str, object] = dict(
        candidate_id="cand_1",
        resolved_identity=None,
        create_new_identity=False,
        route=AdjudicationRoute.LLM_ASSESS,
        score_vector={"name_similarity": 0.9},
        matcher_version="v1",
        snapshot_version="17",
        trace_id="trace_1",
    )
    base.update(kw)
    return ResolutionDecision(**base)  # type: ignore[arg-type]


def test_identity_disposition_resolved_existing():
    decision = _decision(resolved_identity="kg://g1/identity/" + "0" * 26)
    assert decision.identity_disposition() is IdentityDisposition.RESOLVED_EXISTING


def test_identity_disposition_new_identity():
    decision = _decision(create_new_identity=True)
    assert decision.identity_disposition() is IdentityDisposition.NEW_IDENTITY


def test_identity_disposition_abstention_is_unresolved():
    # Neither an identity nor an instruction to mint one: the resolver
    # abstained. That must never be read as a resolution.
    decision = _decision()
    assert decision.identity_disposition() is IdentityDisposition.UNRESOLVED


def test_new_identity_decision_may_also_name_the_minted_identity():
    # Issue #47: a resolver minting a new identity normally names the id it
    # minted — the executor needs it to build the CREATE_IDENTITY payload —
    # so create_new_identity=True ALONGSIDE resolved_identity is the
    # expected shape, not a contradiction. `kgcs.policy.ResolutionPolicy`
    # emits exactly this for every AUTO-routed entity candidate, so a
    # contract that rejected it would break KGCS for every adopter.
    minted = "kg://g1/identity/" + "0" * 26
    decision = _decision(create_new_identity=True, resolved_identity=minted)
    assert decision.resolved_identity == minted
    assert decision.identity_disposition() is IdentityDisposition.NEW_IDENTITY


def test_create_new_identity_wins_over_a_named_identity_in_the_disposition():
    # The precedence that makes the both-set case unambiguous: whatever
    # `resolved_identity` holds, an explicit instruction to mint decides the
    # disposition. Without this ordering the both-set case would resolve to
    # RESOLVED_EXISTING and re-impose the very gate ADR-0024 lifts.
    both_set = _decision(
        create_new_identity=True, resolved_identity="kg://g1/identity/" + "1" * 26
    )
    only_named = _decision(resolved_identity="kg://g1/identity/" + "1" * 26)
    assert both_set.identity_disposition() is IdentityDisposition.NEW_IDENTITY
    assert only_named.identity_disposition() is IdentityDisposition.RESOLVED_EXISTING


# --- ADR-0025: every operation type but one has a named inverse -------------


def test_create_identity_and_revoke_identity_are_mutual_inverses():
    # The defect: a plan of CREATE_IDENTITY operations used to compensate to
    # nothing, because the vocabulary named no operation that reverses one.
    assert (
        INVERSE_OPERATION_TYPES[CurationOperationType.CREATE_IDENTITY]
        is CurationOperationType.REVOKE_IDENTITY
    )
    assert (
        INVERSE_OPERATION_TYPES[CurationOperationType.REVOKE_IDENTITY]
        is CurationOperationType.CREATE_IDENTITY
    )


def test_every_operation_type_except_promote_ontology_term_has_an_inverse():
    # Named exclusion, not a silent gap: PROMOTE_ONTOLOGY_TERM has no inverse
    # yet (issue #45), and the map says so by omission rather than by a
    # plausible-looking wrong entry.
    missing = set(CurationOperationType) - set(INVERSE_OPERATION_TYPES)
    assert missing == {CurationOperationType.PROMOTE_ONTOLOGY_TERM}


def test_inverse_operation_types_is_an_involution():
    # Applying the inverse twice returns the original operation type, so
    # compensating a compensation replays the original work.
    for op_type, inverse in INVERSE_OPERATION_TYPES.items():
        assert inverse in INVERSE_OPERATION_TYPES, op_type
        assert INVERSE_OPERATION_TYPES[inverse] is op_type


def test_revoke_identity_is_a_member_of_the_operation_vocabulary():
    assert CurationOperationType.REVOKE_IDENTITY.value == "REVOKE_IDENTITY"
    assert "REVOKE_IDENTITY" in CurationOperationType.__members__
