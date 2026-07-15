"""Pipeline behavior: the end-to-end wiring, the two idempotency layers, the
failure-isolation split, and CandidateSink integration. The cross-cutting
invariants (replay, dry-run==execution as a law) get their own suite in
test_invariants.py; this file pins the mechanics."""

import pytest

from kg_contracts.ingestion import IngestJob, IngestReport
from kg_contracts.testing.memory import MemoryCandidateSink
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.clock import FixedClock
from kgis.errors import SourceReadError
from kgis.ids import DeterministicIdStrategy
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.ontology import Ontology
from kgis.pipeline import IngestPipeline
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
