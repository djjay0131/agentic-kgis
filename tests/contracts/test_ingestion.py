from datetime import UTC, datetime
from typing import Iterator

from kg_contracts.candidates import Candidate, CandidateScores, EntityCandidate, SourceCoordinates
from kg_contracts.evidence import Provenance
from kg_contracts.identity import EntityRef
from kg_contracts.ingestion import (
    CompletionClient,
    Extractor,
    IngestJob,
    IngestReport,
    Source,
)
from kg_contracts.stores import SubmissionOutcome, SubmissionStatus

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


def _provenance() -> Provenance:
    return Provenance(source="csv", actor="test-actor")


# --- 1. Duck-typed fakes satisfy Source, Extractor, CompletionClient, IngestJob ---


class _FakeSource:
    def fetch(self) -> Iterator[Candidate]:
        yield _entity_candidate()


def test_duck_typed_fake_satisfies_source():
    assert isinstance(_FakeSource(), Source)


class _FakeExtractor:
    @property
    def name(self) -> str:
        return "player-extractor"

    def extract(self, text: str, provenance: Provenance) -> list[Candidate]:
        return [_entity_candidate()]


def test_duck_typed_fake_satisfies_extractor():
    assert isinstance(_FakeExtractor(), Extractor)


class _FakeCompletionClient:
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        return "completion"


def test_duck_typed_fake_satisfies_completion_client():
    assert isinstance(_FakeCompletionClient(), CompletionClient)


class _FakeIngestJob:
    @property
    def job_id(self) -> str:
        return "job_1"

    def run(self) -> IngestReport:
        return IngestReport(graph_id="g1")


def test_duck_typed_fake_satisfies_ingest_job():
    assert isinstance(_FakeIngestJob(), IngestJob)


# --- 2. IngestReport.record() tallies RECEIVED/DUPLICATE/INVALID outcomes ---


def test_ingest_report_record_tallies_by_status():
    report = IngestReport(graph_id="g1")
    report.record(SubmissionOutcome(candidate_id="c1", status=SubmissionStatus.RECEIVED, trace_id="t1"))
    report.record(SubmissionOutcome(candidate_id="c2", status=SubmissionStatus.DUPLICATE, trace_id="t2"))
    report.record(SubmissionOutcome(candidate_id="c3", status=SubmissionStatus.INVALID, trace_id="t3"))

    assert report.received == 1
    assert report.duplicates == 1
    assert report.invalid == 1
    assert report.incomplete is False
    assert report.failures == []


# --- 3. IngestReport.fail() sets incomplete=True and captures the message ---


def test_ingest_report_fail_sets_incomplete_and_captures_message():
    report = IngestReport(graph_id="g1")
    report.fail("extractor player-extractor: timeout")

    assert report.incomplete is True
    assert report.failures == ["extractor player-extractor: timeout"]


# --- 4. IngestJob is documented SPEC-LEVEL ---


def test_ingest_job_is_documented_spec_level():
    assert IngestJob.__doc__ is not None
    assert "SPEC-LEVEL" in IngestJob.__doc__
