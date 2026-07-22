"""Task 14: the real Plan 4 ingestion pipeline composed onto the persistent
`SqliteCandidateLedger` (both `CandidateSink` and `LedgerReader`), proving
`ledger_duplicates` becomes a real count once a durable ledger is injected —
the seam PR #9 left open (sink owns cross-run idempotency, but a dry-run
plan had no ledger to consult) is closed by Task 7/8's persistent ledger.
"""

from kg_contracts.curation import ProcessingState
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.ledger.store import SqliteCandidateLedger
from kgis.normalize import PassthroughNormalizer
from kgis.pipeline import IngestPipeline
from kgis.sources import IterableRecordReader

_RECORDS = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]


def _pipeline(ledger: SqliteCandidateLedger) -> IngestPipeline:
    return IngestPipeline(
        graph_id="baseball",
        reader=IterableRecordReader(_RECORDS, source_type="roster", locator="memory://roster"),
        normalizer=PassthroughNormalizer(),
        builder=EntityCandidateBuilder(namespace="usssa", key_field="id", entity_type="Player"),
        sink=ledger,
        scoring=SourceScoring(source_reliability=0.9),
        ledger_reader=ledger,
    )


def test_pipeline_persists_to_ledger_and_reads_back(tmp_path):
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)

    report = _pipeline(ledger).run()
    assert report.received == 3

    entries = ledger.ledger_entries()
    assert len(entries) == 3
    assert {e.processing_state for e in entries} == {ProcessingState.RECEIVED}

    # Dry-run over the now-populated ledger: ledger_duplicates is a REAL count, not None.
    dry = _pipeline(ledger).plan()
    assert dry.plan is not None
    assert dry.plan.ledger_duplicates == 3

    ledger.close()


def test_cross_run_replay_via_reopened_ledger(tmp_path):
    path = str(tmp_path / "ledger.db")
    first = SqliteCandidateLedger(path)
    assert _pipeline(first).run().received == 3
    first.close()

    reopened = SqliteCandidateLedger(path)
    report = _pipeline(reopened).run()
    assert report.duplicates == 3  # every candidate already in the durable ledger
    assert len(reopened.ledger_entries()) == 3
    reopened.close()
