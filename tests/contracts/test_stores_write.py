from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.candidates import CandidateScores, EntityCandidate, SourceCoordinates
from kg_contracts.curation import CurationOperation, CurationOperationType, Precondition
from kg_contracts.identity import EntityRef
from kg_contracts.stores import (
    CandidateSink,
    CommitResult,
    GraphMutationBatch,
    GraphMutationStore,
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
)

NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _entity_candidate() -> EntityCandidate:
    return EntityCandidate(
        graph_id="g1",
        producer="test-producer",
        producer_run_id="run_1",
        ontology_version="1",
        source_coordinates=SourceCoordinates(source_type="csv", locator="row_1"),
        semantic_key="entity/1",
        scores=CandidateScores(extraction_confidence=0.9, source_reliability=0.9),
        entity_type="Player",
        aliases=(EntityRef(entity_type="Player", namespace="test", key="1"),),
    )


def _operation() -> CurationOperation:
    return CurationOperation(
        type=CurationOperationType.CREATE_IDENTITY,
        payload={"entity_type": "Player"},
    )


def _precondition() -> Precondition:
    return Precondition(kind="cluster_version", subject="ident_1", expected="1")


# --- 1. Duck-typed fakes satisfy CandidateSink and GraphMutationStore ---


class _FakeSink:
    def submit(self, candidates: list[EntityCandidate]) -> SubmissionResult:
        outcomes = tuple(
            SubmissionOutcome(
                candidate_id=c.candidate_id,
                status=SubmissionStatus.RECEIVED,
                trace_id=c.trace_id,
            )
            for c in candidates
        )
        return SubmissionResult(outcomes=outcomes)


def test_duck_typed_fake_satisfies_candidate_sink():
    assert isinstance(_FakeSink(), CandidateSink)


class _FakeMutationStore:
    def apply(
        self, batch: GraphMutationBatch, preconditions: list[Precondition]
    ) -> CommitResult:
        return CommitResult(batch_id=batch.batch_id, committed=True, new_epoch=2)


def test_duck_typed_fake_satisfies_graph_mutation_store():
    assert isinstance(_FakeMutationStore(), GraphMutationStore)


# --- 2. CandidateSink protocol surface is submit() ONLY ---


def test_candidate_sink_exposes_submit_only():
    for name in ("upsert_nodes", "upsert_edges", "apply", "put_entity"):
        assert name not in dir(CandidateSink)


# --- 3. SubmissionResult.counts() aggregates outcomes by status ---


def test_submission_result_counts_aggregates_by_status():
    outcomes = (
        SubmissionOutcome(candidate_id="c1", status=SubmissionStatus.RECEIVED, trace_id="t1"),
        SubmissionOutcome(candidate_id="c2", status=SubmissionStatus.RECEIVED, trace_id="t2"),
        SubmissionOutcome(
            candidate_id="c3",
            status=SubmissionStatus.DUPLICATE,
            reason="already ingested",
            trace_id="t3",
        ),
        SubmissionOutcome(
            candidate_id="c4", status=SubmissionStatus.INVALID, reason="bad row", trace_id="t4"
        ),
    )
    result = SubmissionResult(outcomes=outcomes)
    assert result.counts() == {
        SubmissionStatus.RECEIVED: 2,
        SubmissionStatus.DUPLICATE: 1,
        SubmissionStatus.INVALID: 1,
    }
    assert result.submission_id.startswith("sub_")


# --- 4. CommitResult validation ---


def test_commit_result_committed_true_without_new_epoch_rejected():
    with pytest.raises(ValidationError, match="epoch"):
        CommitResult(batch_id="mb_1", committed=True, new_epoch=None)


def test_commit_result_not_committed_carries_failed_preconditions():
    preconditions = (_precondition(),)
    result = CommitResult(
        batch_id="mb_1",
        committed=False,
        failed_preconditions=preconditions,
        error="stale snapshot",
    )
    assert result.committed is False
    assert result.new_epoch is None
    assert result.failed_preconditions == preconditions


def test_commit_result_not_committed_without_reason_rejected():
    # fail-closed: a non-commit must name why (error or failed_preconditions),
    # never a silent failure the caller cannot act on.
    with pytest.raises(ValidationError, match="requires a reason"):
        CommitResult(batch_id="mb_1", committed=False)


def test_commit_result_not_committed_with_only_error_is_accepted():
    result = CommitResult(batch_id="mb_1", committed=False, error="backend unavailable")
    assert result.committed is False
    assert result.failed_preconditions == ()


def test_commit_result_not_committed_with_only_failed_preconditions_is_accepted():
    result = CommitResult(
        batch_id="mb_1", committed=False, failed_preconditions=(_precondition(),)
    )
    assert result.committed is False
    assert result.error is None


# --- 5. GraphMutationBatch requires >=1 operation; JSON round-trip equality ---


def test_graph_mutation_batch_requires_at_least_one_operation():
    with pytest.raises(ValidationError):
        GraphMutationBatch(plan_id="pl_1", operations=())


def test_graph_mutation_batch_json_round_trip_equality():
    batch = GraphMutationBatch(plan_id="pl_1", operations=(_operation(),))
    assert batch.batch_id.startswith("mb_")
    assert GraphMutationBatch.model_validate_json(batch.model_dump_json()) == batch
