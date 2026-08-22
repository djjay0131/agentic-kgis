"""Task 14: the real Plan 4 ingestion pipeline composed onto the persistent
`SqliteCandidateLedger` (both `CandidateSink` and `LedgerReader`), proving
`ledger_duplicates` becomes a real count once a durable ledger is injected —
the seam PR #9 left open (sink owns cross-run idempotency, but a dry-run
plan had no ledger to consult) is closed by Task 7/8's persistent ledger.
"""

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


def test_deterministic_id_resubmit_after_revoke_plan_and_run_agree(tmp_path):
    """Under the DEFAULT content-addressed DeterministicIdStrategy, an
    identical resubmit after revoke reuses the same candidate_id, so run()
    rejects it as a DUPLICATE on the candidate_id PRIMARY KEY (not the dedup
    index). plan() now predicts that PK collision via `has_candidate_id`, so
    the two agree: both see 3 duplicates / 0 net-new (Issue #16)."""
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)
    assert _pipeline(ledger).run().received == 3  # default DeterministicIdStrategy

    victim = ledger.ledger_entries()[0].candidate.candidate_id
    ledger.revoke(victim, reason="source retraction", actor="ops")

    dry = _pipeline(ledger).plan()
    assert dry.plan is not None
    # Two live semantic_keys + one revoked tombstone whose candidate_id the
    # deterministic resubmit reuses = all 3 predicted duplicate.
    assert dry.plan.would_submit == 3
    assert dry.plan.ledger_duplicates == 3

    report = _pipeline(ledger).run()
    assert report.received == 0     # revoked key's resubmit hits the candidate_id PK
    assert report.duplicates == 3
    # plan() and run() agree, no divergence.
    assert dry.plan.would_submit - dry.plan.ledger_duplicates == report.received

    assert ledger.is_revoked(victim)                     # tombstone retained
    ledger.close()


def _prop_pipeline(ledger: SqliteCandidateLedger, records) -> IngestPipeline:
    """Pipeline whose builder carries a `v` property, so changing `v` changes
    a candidate's content_hash while its semantic_key (from `id`) and its
    deterministic candidate_id stay fixed."""
    return IngestPipeline(
        graph_id="baseball",
        reader=IterableRecordReader(records, source_type="roster", locator="memory://roster"),
        normalizer=PassthroughNormalizer(),
        builder=EntityCandidateBuilder(
            namespace="usssa", key_field="id", entity_type="Player", property_fields=("v",)
        ),
        sink=ledger,
        scoring=SourceScoring(source_reliability=0.9),
        ledger_reader=ledger,
    )


def test_deterministic_id_changed_content_same_semantic_key_still_duplicate(tmp_path):
    """Deterministic candidate_id = f(graph_id, kind, semantic_key) — it does
    NOT depend on content. So re-ingesting the same semantic_key with CHANGED
    content still mints the same candidate_id and is a DUPLICATE no-op; plan()
    and run() agree. (Enforcing "a resubmit must change content + carry a
    reason" is the separate, deferred owner decision on Issue #16.)"""
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)
    assert _prop_pipeline(ledger, [{"id": "p1", "v": "a"}]).run().received == 1
    original = ledger.ledger_entries()[0].candidate

    # Same id (=> same semantic_key => same deterministic candidate_id), new content.
    dry = _prop_pipeline(ledger, [{"id": "p1", "v": "b"}]).plan()
    assert dry.plan is not None
    assert dry.plan.would_submit == 1
    assert dry.plan.ledger_duplicates == 1   # predicted duplicate

    report = _prop_pipeline(ledger, [{"id": "p1", "v": "b"}]).run()
    assert report.received == 0              # actually deduped
    assert report.duplicates == 1
    assert dry.plan.would_submit - dry.plan.ledger_duplicates == report.received

    # The live row is unchanged: content-addressed identity is a no-op replay.
    current = ledger.ledger_entries()[0].candidate
    assert current.candidate_id == original.candidate_id
    assert current.content_hash == original.content_hash
    ledger.close()
