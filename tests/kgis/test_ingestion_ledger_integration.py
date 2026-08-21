"""Task 14: the real Plan 4 ingestion pipeline composed onto the persistent
`SqliteCandidateLedger` (both `CandidateSink` and `LedgerReader`), proving
`ledger_duplicates` becomes a real count once a durable ledger is injected —
the seam PR #9 left open (sink owns cross-run idempotency, but a dry-run
plan had no ledger to consult) is closed by Task 7/8's persistent ledger.
"""

import pytest

from kg_contracts.curation import ProcessingState
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.ids import IdStrategy, RandomIdStrategy
from kgis.ledger.config import ConsumerProfile
from kgis.ledger.store import SqliteCandidateLedger
from kgis.normalize import PassthroughNormalizer
from kgis.pipeline import IngestPipeline
from kgis.sources import IterableRecordReader

_RECORDS = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]


def _pipeline(
    ledger: SqliteCandidateLedger, *, ids: IdStrategy | None = None
) -> IngestPipeline:
    return IngestPipeline(
        graph_id="baseball",
        reader=IterableRecordReader(_RECORDS, source_type="roster", locator="memory://roster"),
        normalizer=PassthroughNormalizer(),
        builder=EntityCandidateBuilder(namespace="usssa", key_field="id", entity_type="Player"),
        sink=ledger,
        scoring=SourceScoring(source_reliability=0.9),
        ledger_reader=ledger,
        ids=ids,
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


def test_plan_and_run_agree_after_revoke(tmp_path):
    """Regression (Issue #16): a revoked key must be predicted by plan() AND
    admitted by run() — the dry-run/execution divergence is closed.

    Uses `RandomIdStrategy` so the resubmission mints a NEW candidate_id that
    coexists with the revoked tombstone as a fresh live row (the "new live row
    of the same dedup_key" model). See `test_deterministic_id_resubmit_*` for
    the content-addressed-id case, which is a separate open owner decision.
    """
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)
    assert _pipeline(ledger, ids=RandomIdStrategy()).run().received == 3

    victim = ledger.ledger_entries()[0].candidate.candidate_id
    ledger.revoke(victim, reason="source retraction", actor="ops")

    dry = _pipeline(ledger, ids=RandomIdStrategy()).plan()
    assert dry.plan is not None
    assert dry.plan.would_submit == 3
    assert dry.plan.ledger_duplicates == 2  # revoked key no longer counts as a dup

    report = _pipeline(ledger, ids=RandomIdStrategy()).run()
    assert report.received == 1     # exactly the revoked key re-admitted
    assert report.duplicates == 2   # the two still-live keys dedupe
    # plan() and run() agree: predicted net-new == actually received.
    assert dry.plan.would_submit - dry.plan.ledger_duplicates == report.received

    assert ledger.is_revoked(victim)                     # tombstone retained
    assert len(ledger.ledger_entries()) == 3             # 2 originals + 1 resubmit
    total = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert total == 4                                    # 3 originals + 1 new live row
    ledger.close()


def test_plan_and_run_agree_after_erase(tmp_path):
    """Same invariant for erasure: the erased key is resubmittable and both
    plan() and run() agree it is net-new (Issue #16). Distinct-id model, as
    for revoke above."""
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path, profile=ConsumerProfile(erasure_enabled=True))
    assert _pipeline(ledger, ids=RandomIdStrategy()).run().received == 3

    victim = ledger.ledger_entries()[0].candidate.candidate_id
    ledger.erase(victim, reason="gdpr", actor="dpo")

    dry = _pipeline(ledger, ids=RandomIdStrategy()).plan()
    assert dry.plan is not None
    assert dry.plan.ledger_duplicates == 2

    report = _pipeline(ledger, ids=RandomIdStrategy()).run()
    assert report.received == 1
    assert report.duplicates == 2
    assert dry.plan.would_submit - dry.plan.ledger_duplicates == report.received

    assert ledger.is_erased(victim)                      # tombstone retained
    assert ledger.row(victim).payload_hash               # hash-only tombstone kept
    assert len(ledger.ledger_entries()) == 3
    ledger.close()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Open owner decision (Issue #16): under the DEFAULT content-addressed "
        "DeterministicIdStrategy, resubmitting the identical fact after revoke "
        "mints the SAME candidate_id, so the new row collides with the tombstone "
        "on the candidate_id PRIMARY KEY (not the dedup index) and run() reports "
        "DUPLICATE while plan() predicts a submit. Closing this divergence needs "
        "an owner call on whether a content-addressed fact is one identity forever "
        "or a tombstone frees its candidate_id for a fresh live row."
    ),
)
def test_deterministic_id_resubmit_after_revoke_still_diverges(tmp_path):
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)
    assert _pipeline(ledger).run().received == 3  # default DeterministicIdStrategy

    victim = ledger.ledger_entries()[0].candidate.candidate_id
    ledger.revoke(victim, reason="source retraction", actor="ops")

    dry = _pipeline(ledger).plan()
    assert dry.plan is not None
    report = _pipeline(ledger).run()
    # The invariant we WANT (and that holds for distinct-id resubmission):
    assert dry.plan.would_submit - dry.plan.ledger_duplicates == report.received
    ledger.close()
