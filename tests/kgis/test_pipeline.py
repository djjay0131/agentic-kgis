"""Pipeline behavior: the end-to-end wiring, the two idempotency layers, the
failure-isolation split, and CandidateSink integration. The cross-cutting
invariants (replay, dry-run==execution as a law) get their own suite in
test_invariants.py; this file pins the mechanics."""

from typing import Sequence

import pytest

from kg_contracts.candidates import Candidate
from kg_contracts.curation import FailureKind, ValidationDecision
from kg_contracts.ingestion import IngestJob, IngestReport
from kg_contracts.stores import (
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
)
from kg_contracts.testing.memory import MemoryCandidateSink
from kgis.builders import (
    BuildContext,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
)
from kgis.clock import FixedClock
from kgis.errors import SourceReadError
from kgis.ids import DeterministicIdStrategy
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.ontology import Ontology
from kgis.pipeline import IngestPipeline
from kgis.records import NormalizedRecord
from kgis.sources.iterable_reader import IterableRecordReader

from scenarios import NOW, PLAYERS, build_pipeline


class ExplodingReader:
    """A reader that yields a few records, then faults mid-stream."""

    def __init__(self, good: int = 2) -> None:
        self._good = good

    @property
    def source_type(self) -> str:
        return "explosive"

    @property
    def locator(self) -> str:
        return "boom"

    def read(self):  # type: ignore[no-untyped-def]
        base = IterableRecordReader(PLAYERS[: self._good], source_type="explosive", locator="boom")
        yield from base.read()
        raise SourceReadError("disk fell over")


class TestEndToEnd:
    def test_ingests_players_into_the_sink(self, sink: MemoryCandidateSink) -> None:
        report = build_pipeline(sink=sink).run()
        # 3 players × (entity + height attribute + PLAYS_FOR relation) = 9
        assert report.candidates_built == 9
        assert report.candidates_submitted == 9
        assert len(sink.received()) == 9

    def test_report_counts_every_stage(self, sink: MemoryCandidateSink) -> None:
        report = build_pipeline(sink=sink).run()
        assert report.records_read == 3
        assert report.records_valid == 3
        assert report.records_invalid == 0
        assert report.received == 9
        assert report.succeeded is True

    def test_kind_counts_break_down_the_output(self, sink: MemoryCandidateSink) -> None:
        report = build_pipeline(sink=sink).run()
        assert report.kind_counts == {"attribute_assertion": 3, "entity": 3, "relation": 3}

    def test_the_pipeline_is_an_ingest_job(self) -> None:
        assert isinstance(build_pipeline(), IngestJob)

    def test_run_returns_a_contract_ingest_report(self, sink: MemoryCandidateSink) -> None:
        assert isinstance(build_pipeline(sink=sink).run(), IngestReport)

    def test_job_id_is_stable_across_runs(self) -> None:
        pipeline = build_pipeline()
        assert pipeline.run().job_id == pipeline.run().job_id == "job-fixed"

    def test_only_the_candidate_sink_is_written(self, sink: MemoryCandidateSink) -> None:
        """The pipeline holds no graph-write surface at all (ADR-0010)."""
        build_pipeline(sink=sink).run()
        assert not hasattr(sink, "put_entity")
        assert set(sink.received()[0].model_dump().keys())  # candidates, not graph rows


class TestValidationGate:
    def test_an_invalid_record_produces_no_candidate(self, sink: MemoryCandidateSink) -> None:
        """The core guarantee: validation failures never reach the builder."""
        records = [
            {"id": "1", "name": "Ada", "team": "10", "height_cm": "170"},
            {"id": "", "name": "NoId", "team": "10", "height_cm": "1"},  # empty required id
        ]
        report = build_pipeline(records=records, sink=sink).run()
        assert report.records_invalid == 1
        assert report.records_valid == 1
        assert len(report.validation_failures) == 1
        # Only the valid row's candidates exist; the bad row contributed none.
        assert all(c.source_coordinates.fragment == "index=0" for c in sink.received())

    def test_a_bad_value_row_is_isolated_not_fatal(self, sink: MemoryCandidateSink) -> None:
        records = [
            {"id": "1", "name": "Ada", "team": "10", "height_cm": "not-a-number"},
            {"id": "2", "name": "Grace", "team": "10", "height_cm": "175"},
        ]
        report = build_pipeline(records=records, sink=sink).run()
        assert report.records_invalid == 1
        assert report.records_valid == 1
        assert report.succeeded is False  # a rejection means partial success at best


class TestOntologyGate:
    def test_strict_mode_rejects_an_unknown_term_before_the_sink(
        self, sink: MemoryCandidateSink
    ) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Team"}))  # no Player
        builder = EntityCandidateBuilder(entity_type="Player", namespace="usssa", key_field="id")
        report = build_pipeline(
            builder=builder, ontology=ontology, ontology_strict=True, sink=sink
        ).run()
        assert report.candidates_built == 3
        assert report.candidates_rejected == 3
        assert report.candidates_submitted == 0
        assert len(sink.received()) == 0

    def test_permissive_mode_admits_but_reports_the_unknown_term(
        self, sink: MemoryCandidateSink
    ) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Team"}))
        builder = EntityCandidateBuilder(entity_type="Player", namespace="usssa", key_field="id")
        report = build_pipeline(
            builder=builder, ontology=ontology, ontology_strict=False, sink=sink
        ).run()
        assert report.candidates_submitted == 3
        assert report.coverage.unknown_entity_types == ("Player",)

    def test_coverage_reports_unknown_and_unused_terms(self, sink: MemoryCandidateSink) -> None:
        ontology = Ontology(
            version="1",
            entity_types=frozenset({"Player", "Team", "Coach"}),
            relation_types=frozenset({"PLAYS_FOR"}),
            attributes=frozenset({"height_cm"}),
        )
        report = build_pipeline(ontology=ontology, sink=sink).run()
        assert "Coach" in report.coverage.unused_entity_types
        assert report.coverage.has_unknown_terms is False


class TestIntraRunIdempotency:
    def test_a_repeated_semantic_key_is_suppressed_before_the_sink(
        self, sink: MemoryCandidateSink
    ) -> None:
        """Two identical rows in one file must not become two candidates."""
        records = [PLAYERS[0], PLAYERS[0]]  # same player twice
        report = build_pipeline(records=records, sink=sink).run()
        assert report.candidates_built == 6  # built for both rows
        assert report.candidates_suppressed == 3  # second row's three dropped
        assert report.candidates_submitted == 3
        assert len(sink.received()) == 3

    def test_suppression_keeps_the_first_occurrence(self, sink: MemoryCandidateSink) -> None:
        records = [PLAYERS[0], PLAYERS[0]]
        build_pipeline(records=records, sink=sink).run()
        # First row's candidates all point at record index 0.
        assert all(c.source_coordinates.fragment == "index=0" for c in sink.received())


class TestCrossRunIdempotency:
    def test_re_ingesting_the_same_data_is_all_duplicate(
        self, sink: MemoryCandidateSink
    ) -> None:
        """The sink owns cross-run dedup: yesterday's file re-run is a no-op."""
        first = build_pipeline(sink=sink).run()
        assert first.received == 9

        second = build_pipeline(sink=sink).run()  # same sink, same data
        assert second.duplicates == 9
        assert second.received == 0
        assert second.candidates_submitted == 0
        assert len(sink.received()) == 9  # sink still holds exactly the first run's

    def test_the_same_candidate_ids_recur_across_runs(self) -> None:
        """Deterministic ids make a replay recognizable as the same facts."""
        sink1, sink2 = MemoryCandidateSink(), MemoryCandidateSink()
        first = build_pipeline(sink=sink1).run()
        second = build_pipeline(sink=sink2).run()
        assert {c.candidate_id for c in sink1.received()} == {
            c.candidate_id for c in sink2.received()
        }
        assert first.received == second.received == 9


class TestFailureIsolation:
    def test_a_mid_stream_reader_fault_marks_the_report_incomplete(
        self, sink: MemoryCandidateSink
    ) -> None:
        """Spec §9: a failed read is never a silent truncation."""
        pipeline = IngestPipeline(
            graph_id="baseball",
            reader=ExplodingReader(good=2),
            normalizer=SchemaNormalizer([FieldSpec(name="id", required=True)]),
            builder=EntityCandidateBuilder(
                entity_type="Player", namespace="usssa", key_field="id"
            ),
            sink=sink,
            scoring=SourceScoring(source_reliability=0.8),
            clock=FixedClock(NOW),
            ids=DeterministicIdStrategy(),
        )
        report = pipeline.run()
        assert report.incomplete is True
        assert any("source read failed" in f for f in report.failures)

    def test_candidates_built_before_the_fault_are_kept(
        self, sink: MemoryCandidateSink
    ) -> None:
        pipeline = IngestPipeline(
            graph_id="baseball",
            reader=ExplodingReader(good=2),
            normalizer=SchemaNormalizer([FieldSpec(name="id", required=True)]),
            builder=EntityCandidateBuilder(
                entity_type="Player", namespace="usssa", key_field="id"
            ),
            sink=sink,
            scoring=SourceScoring(source_reliability=0.8),
            clock=FixedClock(NOW),
            ids=DeterministicIdStrategy(),
        )
        report = pipeline.run()
        assert report.records_read == 2
        assert len(sink.received()) == 2  # the two good rows made it in
        assert report.succeeded is False


class TestElapsedTime:
    def test_elapsed_is_measured_monotonically(self, sink: MemoryCandidateSink) -> None:
        pipeline = build_pipeline(sink=sink, clock=FixedClock(NOW, tick_seconds=0.25))
        report = pipeline.run()
        # start + end reads = the two monotonic() calls straddling the run.
        assert report.elapsed_seconds == 0.25

    def test_stamped_created_at_comes_from_the_injected_clock(
        self, sink: MemoryCandidateSink
    ) -> None:
        build_pipeline(sink=sink).run()
        assert all(c.created_at == NOW for c in sink.received())


def _timed_schema() -> SchemaNormalizer:
    return SchemaNormalizer(
        [
            FieldSpec(name="id", type="str", required=True),
            FieldSpec(name="team", type="str"),
            FieldSpec(name="start", type="datetime"),
            FieldSpec(name="end", type="datetime"),
        ]
    )


def _timed_relation_builder() -> RelationCandidateBuilder:
    return RelationCandidateBuilder(
        relation_type="PLAYS_FOR",
        subject_type="Player",
        subject_namespace="usssa",
        subject_key_field="id",
        object_type="Team",
        object_namespace="usssa",
        object_key_field="team",
        valid_from_field="start",
        valid_to_field="end",
    )


class _ExplodingBuilder:
    """A builder that raises a *programmer* error, not a data error.

    Used to prove the build boundary catches data faults specifically and
    lets a genuine bug propagate — a `KeyError` here is never quarantined as
    a bad record.
    """

    @property
    def required_fields(self) -> tuple[str, ...]:
        return ()

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        raise KeyError("this is a bug, not bad data")


class TestBuildFailureIsolation:
    """Fix: a data-dependent failure at *build* time is one bad record, not a
    dead run — and it never admits a partial set of candidates from that row."""

    def test_a_missing_relation_endpoint_rejects_the_record_not_the_run(
        self, sink: MemoryCandidateSink
    ) -> None:
        """The relation builder requires `team`; a null one is rejected before
        any builder runs, so the entity/attribute for that row are never
        partially admitted (the composite's required_fields are auto-wired)."""
        records = [
            {"id": "9", "name": "NoTeam", "team": "", "height_cm": "170"},  # empty endpoint
            {"id": "2", "name": "Grace", "team": "10", "height_cm": "175"},  # a valid row
        ]
        report = build_pipeline(records=records, sink=sink).run()
        assert report.records_invalid == 1
        assert report.records_valid == 1
        # No partial admission: the bad row contributed *nothing*, not just no
        # relation. Every candidate in the sink is the good row's.
        assert {c.source_coordinates.fragment for c in sink.received()} == {"index=1"}

    def test_an_inverted_valid_time_interval_rejects_the_record(
        self, sink: MemoryCandidateSink
    ) -> None:
        """`valid_from > valid_to` only fails inside the contract model, at
        build time — it must still land as a record rejection, not an abort."""
        records = [
            {"id": "1", "team": "10", "start": "2026-12-31T00:00:00+00:00",
             "end": "2026-01-01T00:00:00+00:00"},  # inverted interval
            {"id": "2", "team": "10", "start": "2026-01-01T00:00:00+00:00",
             "end": "2026-12-31T00:00:00+00:00"},  # a valid row
        ]
        report = build_pipeline(
            records=records,
            normalizer=_timed_schema(),
            builder=_timed_relation_builder(),
            sink=sink,
        ).run()
        assert report.records_invalid == 1
        assert report.records_valid == 1
        assert len(sink.received()) == 1
        assert sink.received()[0].source_coordinates.fragment == "index=1"
        assert report.validation_failures[0].failure_kind is FailureKind.BAD_DATA

    def test_a_bad_dynamic_entity_type_rejects_the_record(
        self, sink: MemoryCandidateSink
    ) -> None:
        """A per-row `entity_type` that violates the `EntityRef` pattern fails
        only when the ref is constructed, at build time. Still one bad row."""
        schema = SchemaNormalizer(
            [
                FieldSpec(name="id", type="str", required=True),
                FieldSpec(name="kind", type="str"),
            ]
        )
        builder = EntityCandidateBuilder(
            entity_type_field="kind", namespace="usssa", key_field="id"
        )
        records = [
            {"id": "1", "kind": "not a type"},  # invalid entity_type (spaces, lowercase)
            {"id": "2", "kind": "Player"},  # a valid row
        ]
        report = build_pipeline(
            records=records, normalizer=schema, builder=builder, sink=sink
        ).run()
        assert report.records_invalid == 1
        assert report.records_valid == 1
        assert [c.source_coordinates.fragment for c in sink.received()] == ["index=1"]

    def test_a_programmer_error_in_a_builder_still_propagates(
        self, sink: MemoryCandidateSink
    ) -> None:
        """The boundary catches *data* faults, never bugs: a `KeyError` from a
        builder is a defect and must not be silently quarantined as bad data."""
        with pytest.raises(KeyError, match="this is a bug"):
            build_pipeline(
                records=[PLAYERS[0]], builder=_ExplodingBuilder(), sink=sink
            ).run()


class RejectingSink:
    """A `CandidateSink` that rejects every candidate with `INVALID`.

    Models a sink whose synchronous well-formedness check refuses a
    candidate the pipeline itself was willing to submit — the case
    `IngestionReport.succeeded` must not paper over.
    """

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult:
        return SubmissionResult(
            outcomes=tuple(
                SubmissionOutcome(
                    candidate_id=c.candidate_id,
                    status=SubmissionStatus.INVALID,
                    reason="sink refused it",
                    trace_id=c.trace_id,
                )
                for c in candidates
            )
        )


class TestSinkRejectionCountsAgainstSuccess:
    """Fix: a sink returning INVALID means the run did not succeed."""

    def test_a_sink_invalid_makes_succeeded_false(self) -> None:
        report = build_pipeline(sink=RejectingSink()).run()
        assert report.invalid == 9
        assert report.candidates_submitted == 0
        assert report.succeeded is False


class _RejectFirstValidator:
    """A candidate validator that rejects the first candidate it sees and
    accepts every one after — regardless of semantic key.

    Proves the pipeline does not let a *rejected* candidate reserve a
    semantic key: if it did, a later valid candidate sharing that key would
    be silently suppressed instead of getting its own verdict.
    """

    policy_version = "test"

    def __init__(self) -> None:
        self._seen = 0

    def validate(self, candidate: Candidate) -> ValidationDecision:
        self._seen += 1
        rejected = self._seen == 1
        return ValidationDecision(
            candidate_id=candidate.candidate_id,
            valid=not rejected,
            failure_kind=FailureKind.BAD_DATA if rejected else None,
            reasons=("rejected the first one",) if rejected else (),
            policy_version=self.policy_version,
            trace_id=candidate.trace_id,
        )


class TestRejectedCandidateDoesNotReserveTheKey:
    """Fix: the semantic key is reserved only after validation succeeds."""

    def test_a_rejected_first_candidate_does_not_suppress_a_later_valid_one(
        self, sink: MemoryCandidateSink
    ) -> None:
        # Two identical rows → same semantic keys. The validator rejects the
        # first entity candidate; the second row's identical-key entity must
        # still be validated and admitted, not suppressed as a duplicate.
        records = [PLAYERS[0], PLAYERS[0]]
        builder = EntityCandidateBuilder(
            entity_type="Player", namespace="usssa", key_field="id"
        )
        report = build_pipeline(
            records=records,
            builder=builder,
            candidate_validator=_RejectFirstValidator(),
            sink=sink,
        ).run()
        assert report.candidates_built == 2
        assert report.candidates_rejected == 1  # the first
        assert report.candidates_suppressed == 0  # the second was NOT suppressed
        assert report.candidates_submitted == 1  # the second reached the sink
        assert len(sink.received()) == 1


class TestBatching:
    def test_batch_size_does_not_change_outcomes(self) -> None:
        """Spec §6 batch-of-one constraint: transport, never semantics."""
        results = []
        for batch_size in (1, 2, 500):
            sink = MemoryCandidateSink()
            report = build_pipeline(sink=sink, batch_size=batch_size).run()
            results.append((report.received, {c.candidate_id for c in sink.received()}))
        assert results[0] == results[1] == results[2]

    def test_batch_size_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="batch_size"):
            build_pipeline(batch_size=0)
