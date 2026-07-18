"""The invariant suite: the laws that make this engine trustworthy.

Each class here is one property the sprint brief names, written as a law
rather than an example — asserted across formats, across runs, and against
the built candidates themselves rather than a summary of them. If any of
these breaks, a downstream project built on KGIS inherits a silent bug, so
they are the tests that matter most.

The laws:
  1. same input → same candidates (determinism)
  2. dry-run == execution, except submission
  3. validation failures never produce candidates
  4. pipeline stage ordering
  5. deterministic replay (idempotent re-ingest)
  6. CandidateSink always receives valid candidates
  7. cross-format equivalence (CSV / JSON / iterable agree)
  8. batch-of-one equivalence
"""

import csv
import io
import json

import pytest

from kg_contracts.candidates import candidate_adapter
from kg_contracts.testing.contract import CandidateSinkContract
from kg_contracts.testing.memory import MemoryCandidateSink
from kgis.sources.csv_reader import CsvRecordReader
from kgis.sources.iterable_reader import IterableRecordReader
from kgis.sources.json_reader import JsonRecordReader

from scenarios import PLAYERS, baseball_ontology, build_pipeline


def _candidate_signature(sink: MemoryCandidateSink) -> list[tuple[str, str, str]]:
    """A run's output reduced to what determinism actually promises: the same
    facts, with the same ids, in the same order. Excludes nothing that should
    be stable — created_at is fixed by the injected clock, so it stays in via
    the full-model comparison used elsewhere; this is the readable projection."""
    return [(c.candidate_kind, c.semantic_key, c.candidate_id) for c in sink.received()]


def _players_as_csv(rows: tuple[dict[str, str], ...]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


class TestSameInputSameCandidates:
    """Law 1: same input → same candidates, byte for byte."""

    def test_two_runs_produce_identical_candidates(self) -> None:
        sink_a, sink_b = MemoryCandidateSink(), MemoryCandidateSink()
        build_pipeline(sink=sink_a).run()
        build_pipeline(sink=sink_b).run()
        assert sink_a.received() == sink_b.received()

    def test_identical_down_to_candidate_and_trace_ids(self) -> None:
        sink_a, sink_b = MemoryCandidateSink(), MemoryCandidateSink()
        build_pipeline(sink=sink_a).run()
        build_pipeline(sink=sink_b).run()
        assert _candidate_signature(sink_a) == _candidate_signature(sink_b)
        assert [c.trace_id for c in sink_a.received()] == [
            c.trace_id for c in sink_b.received()
        ]

    def test_reports_fingerprint_equally(self) -> None:
        a = build_pipeline(sink=MemoryCandidateSink()).run()
        b = build_pipeline(sink=MemoryCandidateSink()).run()
        assert a.fingerprint() == b.fingerprint()


class TestDryRunEqualsExecution:
    """Law 2: dry-run plans exactly what execution submits — and submits nothing."""

    def test_plan_builds_the_same_candidates_execution_submits(self) -> None:
        planned = build_pipeline(sink=MemoryCandidateSink()).plan()
        exec_sink = MemoryCandidateSink()
        build_pipeline(sink=exec_sink).run()
        assert planned.plan is not None
        assert list(planned.plan.candidates) == exec_sink.received()

    def test_dry_run_submits_nothing(self) -> None:
        sink = MemoryCandidateSink()
        report = build_pipeline(sink=sink).plan()
        assert report.candidates_submitted == 0
        assert sink.received() == []
        assert report.received == 0

    def test_plan_and_execution_agree_on_every_stage_count(self) -> None:
        plan = build_pipeline(sink=MemoryCandidateSink()).plan()
        run = build_pipeline(sink=MemoryCandidateSink()).run()
        # Everything up to submission is identical; only submission differs.
        assert plan.records_read == run.records_read
        assert plan.records_valid == run.records_valid
        assert plan.candidates_built == run.candidates_built
        assert plan.candidates_suppressed == run.candidates_suppressed
        assert plan.candidates_rejected == run.candidates_rejected
        assert plan.kind_counts == run.kind_counts
        assert plan.coverage == run.coverage
        assert plan.plan is not None
        assert plan.plan.would_submit == run.candidates_submitted

    def test_plan_is_safe_against_a_shared_sink(self) -> None:
        """Planning against a live sink must not mutate it."""
        sink = MemoryCandidateSink()
        build_pipeline(sink=sink).run()
        before = sink.received()
        build_pipeline(sink=sink).plan()
        assert sink.received() == before

    def test_plan_counts_ledger_duplicates_when_a_reader_is_present(self) -> None:
        sink = MemoryCandidateSink()
        build_pipeline(sink=sink).run()  # sink now holds 9
        plan = build_pipeline(sink=sink, ledger_reader=sink).plan()
        assert plan.plan is not None
        assert plan.plan.ledger_duplicates == 9  # all of them already there

    def test_plan_ledger_duplicates_is_null_without_a_reader(self) -> None:
        plan = build_pipeline(sink=MemoryCandidateSink()).plan()
        assert plan.plan is not None
        assert plan.plan.ledger_duplicates is None


class TestValidationFailuresNeverProduceCandidates:
    """Law 3: a rejected record contributes zero candidates. Non-negotiable."""

    @pytest.mark.parametrize(
        "bad_row",
        [
            {"id": "", "name": "NoId", "team": "1", "height_cm": "1"},  # empty required
            {"id": "x", "name": "Bad", "team": "1", "height_cm": "tall"},  # uncoercible
        ],
    )
    def test_a_bad_row_adds_nothing_to_the_sink(self, bad_row: dict[str, str]) -> None:
        sink = MemoryCandidateSink()
        good = {"id": "1", "name": "Ada", "team": "10", "height_cm": "170"}
        report = build_pipeline(records=[good, bad_row], sink=sink).run()
        assert report.records_invalid == 1
        # Every admitted candidate traces to the good row (index 0), none to the bad one.
        assert {c.source_coordinates.fragment for c in sink.received()} == {"index=0"}

    def test_an_all_bad_source_submits_nothing(self) -> None:
        sink = MemoryCandidateSink()
        bad = [{"id": "", "name": n, "team": "1", "height_cm": "1"} for n in ("a", "b")]
        report = build_pipeline(records=bad, sink=sink).run()
        assert report.records_valid == 0
        assert report.candidates_built == 0
        assert sink.received() == []

    def test_a_rejected_candidate_never_reaches_the_sink(self) -> None:
        """The candidate tier is the sink's guard — an unknown term is stopped here."""
        from kgis.ontology import Ontology

        sink = MemoryCandidateSink()
        ontology = Ontology(version="1", entity_types=frozenset({"Team"}))  # Player unknown
        from kgis.builders import EntityCandidateBuilder

        builder = EntityCandidateBuilder(entity_type="Player", namespace="usssa", key_field="id")
        report = build_pipeline(builder=builder, ontology=ontology, sink=sink).run()
        assert report.candidates_rejected == 3
        assert sink.received() == []


class TestStageOrdering:
    """Law 4: the stages run in the one order that is correct."""

    def test_normalization_precedes_validation(self) -> None:
        """A CSV "170" must be an int by the time the sink sees it — proof that
        normalization ran before build, which ran before submission."""
        csv_text = _players_as_csv(PLAYERS)
        sink = MemoryCandidateSink()
        build_pipeline(reader=CsvRecordReader(text=csv_text), sink=sink).run()
        heights = [
            c.value for c in sink.received() if c.candidate_kind == "attribute_assertion"
        ]
        assert heights == [170, 175, 180]  # ints, not strings
        assert all(isinstance(h, int) for h in heights)

    def test_suppression_precedes_submission(self) -> None:
        """A duplicate is dropped before the sink, so the sink never reports it."""
        sink = MemoryCandidateSink()
        report = build_pipeline(records=[PLAYERS[0], PLAYERS[0]], sink=sink).run()
        assert report.candidates_suppressed == 3
        assert report.duplicates == 0  # the sink never saw the suppressed ones

    def test_validation_precedes_build(self) -> None:
        """candidates_built counts only rows that passed validation."""
        sink = MemoryCandidateSink()
        good = {"id": "1", "name": "Ada", "team": "10", "height_cm": "170"}
        bad = {"id": "", "name": "x", "team": "1", "height_cm": "1"}
        report = build_pipeline(records=[good, bad], sink=sink).run()
        assert report.records_read == 2
        assert report.records_valid == 1
        assert report.candidates_built == 3  # only the one good row's three


class TestDeterministicReplay:
    """Law 5: re-ingesting identical data is a no-op — no duplicate candidates."""

    def test_second_run_into_the_same_sink_is_all_duplicate(self) -> None:
        sink = MemoryCandidateSink()
        build_pipeline(sink=sink).run()
        second = build_pipeline(sink=sink).run()
        assert second.received == 0
        assert second.duplicates == 9

    def test_the_ledger_holds_exactly_one_copy_after_repeated_ingest(self) -> None:
        sink = MemoryCandidateSink()
        for _ in range(5):
            build_pipeline(sink=sink).run()
        assert len(sink.received()) == 9  # not 45

    def test_replay_reuses_candidate_ids(self) -> None:
        sink_a, sink_b = MemoryCandidateSink(), MemoryCandidateSink()
        build_pipeline(sink=sink_a).run()
        build_pipeline(sink=sink_b).run()
        assert {c.candidate_id for c in sink_a.received()} == {
            c.candidate_id for c in sink_b.received()
        }


class TestSinkAlwaysReceivesValidCandidates:
    """Law 6: everything handed to the sink is a well-formed contract Candidate."""

    def test_every_submitted_candidate_round_trips_through_the_union(self) -> None:
        sink = MemoryCandidateSink()
        build_pipeline(sink=sink).run()
        assert sink.received()  # non-empty
        for candidate in sink.received():
            revived = candidate_adapter.validate_python(candidate.model_dump(mode="python"))
            assert revived == candidate

    def test_every_submitted_candidate_carries_both_required_scores(self) -> None:
        sink = MemoryCandidateSink()
        build_pipeline(sink=sink).run()
        for candidate in sink.received():
            assert 0.0 <= candidate.scores.extraction_confidence <= 1.0
            assert 0.0 <= candidate.scores.source_reliability <= 1.0

    def test_no_rejected_candidate_ever_appears_in_the_sink(self) -> None:
        from kgis.builders import EntityCandidateBuilder
        from kgis.ontology import Ontology

        sink = MemoryCandidateSink()
        ontology = Ontology(version="1", entity_types=frozenset({"Team"}))
        builder = EntityCandidateBuilder(entity_type="Player", namespace="usssa", key_field="id")
        build_pipeline(builder=builder, ontology=ontology, sink=sink).run()
        assert sink.received() == []


class TestCrossFormatEquivalence:
    """Law 7: the same data in CSV, JSON, JSON-Lines, or a list produces the
    same candidates. This is the payoff of a uniform reader and a
    format-erasing normalizer."""

    def _run(self, reader: object) -> MemoryCandidateSink:
        sink = MemoryCandidateSink()
        build_pipeline(reader=reader, sink=sink).run()  # type: ignore[arg-type]
        return sink

    def test_all_four_formats_yield_identical_candidates(self) -> None:
        csv_text = _players_as_csv(PLAYERS)
        json_array = json.dumps(list(PLAYERS))
        json_lines = "\n".join(json.dumps(row) for row in PLAYERS)

        sinks = {
            "iterable": self._run(IterableRecordReader(PLAYERS)),
            "csv": self._run(CsvRecordReader(text=csv_text)),
            "json_array": self._run(JsonRecordReader(text=json_array)),
            "json_lines": self._run(JsonRecordReader(text=json_lines)),
        }
        signatures = {
            name: [(c.candidate_kind, c.semantic_key, c.candidate_id) for c in sink.received()]
            for name, sink in sinks.items()
        }
        reference = signatures["iterable"]
        for name, signature in signatures.items():
            assert signature == reference, f"{name} diverged from iterable"

    def test_the_stamped_values_agree_across_formats(self) -> None:
        """CSV strings and JSON ints must both land as the same int in the graph."""
        csv_sink = self._run(CsvRecordReader(text=_players_as_csv(PLAYERS)))
        json_sink = self._run(JsonRecordReader(text=json.dumps(list(PLAYERS))))
        csv_heights = [c.value for c in csv_sink.received() if c.candidate_kind == "attribute_assertion"]
        json_heights = [c.value for c in json_sink.received() if c.candidate_kind == "attribute_assertion"]
        assert csv_heights == json_heights == [170, 175, 180]


class TestBatchOfOneEquivalence:
    """Law 8: batch size is transport, never semantics (spec §6)."""

    def test_every_batch_size_produces_the_same_ledger(self) -> None:
        reference: list[str] | None = None
        for batch_size in (1, 2, 3, 9, 500):
            sink = MemoryCandidateSink()
            build_pipeline(sink=sink, batch_size=batch_size).run()
            ids = [c.candidate_id for c in sink.received()]
            if reference is None:
                reference = ids
            assert ids == reference, f"batch_size={batch_size} diverged"

    def test_batch_size_does_not_change_the_report(self) -> None:
        one = build_pipeline(sink=MemoryCandidateSink(), batch_size=1).run()
        many = build_pipeline(sink=MemoryCandidateSink(), batch_size=500).run()
        assert one.fingerprint() == many.fingerprint()


class TestOntologyCoverageIsHonest:
    """A cross-cutting check that the report never overstates what happened."""

    def test_coverage_flags_a_declared_type_the_run_never_produced(self) -> None:
        """The pipeline builds Player entities but no Team entities — teams appear
        only as relation objects. Coverage must report that gap honestly, not
        round it up: Player + PLAYS_FOR + height_cm are covered, Team is not."""
        report = build_pipeline(ontology=baseball_ontology(), sink=MemoryCandidateSink()).run()
        assert report.coverage.has_unknown_terms is False
        assert report.coverage.unused_entity_types == ("Team",)
        assert report.coverage.coverage_ratio == 0.75  # 3 of 4 declared terms produced

    def test_full_coverage_when_every_declared_term_is_produced(self) -> None:
        """Declare exactly what this pipeline produces, and coverage reads 1.0."""
        from kgis.ontology import Ontology

        exact = Ontology(
            version="1",
            entity_types=frozenset({"Player"}),
            relation_types=frozenset({"PLAYS_FOR"}),
            attributes=frozenset({"height_cm"}),
        )
        report = build_pipeline(ontology=exact, sink=MemoryCandidateSink()).run()
        assert report.coverage.coverage_ratio == 1.0
        assert report.coverage.has_unknown_terms is False


class TestKgisSinkPassesTheContractSuite(CandidateSinkContract):
    """The memory sink KGIS submits into is the contract reference — re-running
    the reusable suite here keeps the sprint honest that we integrated with the
    real CandidateSink, not a bespoke stand-in."""

    def make_sink(self) -> MemoryCandidateSink:
        return MemoryCandidateSink()
