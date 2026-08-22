"""End-to-end structured sync: SQLite source → pipeline → persistent ledger.

Proves the Plan 4 deliverables on the real Sprint 1 spine (no second pipeline):
candidates produced through `CandidateSink`; cross-run idempotency via the
durable ledger; `plan()` and `run()` agree over the deterministic snapshot; and
per-row Evidence is produced and resolves through the evidence registry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fixtures import PLAYER_ROWS, make_players_db  # type: ignore[import-not-found]

from kgis.builders import (
    AttributeCandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
)
from kgis.clock import FixedClock
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.ledger.store import SqliteCandidateLedger
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.structured import (
    SqliteRowProvider,
    StructuredEvidenceRecorder,
    StructuredSyncConfig,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _config(conn) -> StructuredSyncConfig:
    entity = EntityCandidateBuilder(
        entity_type="Player", namespace="usssa", key_field="id", display_name_field="name"
    )
    builder = CompositeCandidateBuilder(
        [
            entity,
            AttributeCandidateBuilder(subject=entity, attribute_fields=("height_cm",)),
            RelationCandidateBuilder(
                relation_type="PLAYS_FOR",
                subject_type="Player",
                subject_namespace="usssa",
                subject_key_field="id",
                object_type="Team",
                object_namespace="usssa",
                object_key_field="team",
            ),
        ]
    )
    return StructuredSyncConfig(
        graph_id="baseball",
        provider=SqliteRowProvider(conn, table="players", key_fields=("id",)),
        normalizer=SchemaNormalizer(
            [
                FieldSpec(name="id", type="str", required=True),
                FieldSpec(name="name", type="str"),
                FieldSpec(name="team", type="str"),
                FieldSpec(name="height_cm", type="int"),
            ]
        ),
        builder=builder,
        scoring=SourceScoring(source_reliability=0.9),
    )


def _pipeline(config: StructuredSyncConfig, ledger: SqliteCandidateLedger):
    return config.build_pipeline(
        sink=ledger, ledger_reader=ledger, clock=FixedClock(NOW), run_id="run-fixed"
    )


def test_source_to_ledger_produces_candidates_through_the_sink(tmp_path) -> None:
    ledger = SqliteCandidateLedger(str(tmp_path / "ledger.db"))
    report = _pipeline(_config(make_players_db()), ledger).run()

    # 3 entities + 3 attribute assertions + 3 relations.
    assert report.received == 9
    kinds = {e.candidate.candidate_kind for e in ledger.ledger_entries()}
    assert kinds == {"entity", "attribute_assertion", "relation"}
    ledger.close()


def test_reingesting_the_same_snapshot_is_idempotent(tmp_path) -> None:
    path = str(tmp_path / "ledger.db")
    first = SqliteCandidateLedger(path)
    assert _pipeline(_config(make_players_db()), first).run().received == 9
    first.close()

    reopened = SqliteCandidateLedger(path)
    replay = _pipeline(_config(make_players_db()), reopened).run()
    assert replay.received == 0        # nothing new
    assert replay.duplicates == 9      # every candidate already durable
    assert len(reopened.ledger_entries()) == 9
    reopened.close()


def test_plan_and_run_agree_for_the_deterministic_source(tmp_path) -> None:
    ledger = SqliteCandidateLedger(str(tmp_path / "ledger.db"))

    dry = _pipeline(_config(make_players_db()), ledger).plan()
    assert dry.plan is not None
    assert dry.plan.would_submit == 9
    assert dry.plan.ledger_duplicates == 0  # empty ledger
    planned_ids = {c.candidate_id for c in dry.plan.candidates}

    report = _pipeline(_config(make_players_db()), ledger).run()
    submitted_ids = {e.candidate.candidate_id for e in ledger.ledger_entries()}

    # The plan an operator approves is exactly the set that runs.
    assert report.received == dry.plan.would_submit
    assert planned_ids == submitted_ids
    ledger.close()


def test_changed_data_new_snapshot_still_idempotent_by_candidate_id(tmp_path) -> None:
    """Coordinates carry the snapshot version, so a changed re-sync gets new
    coordinates — but candidate_id is content-addressed on semantic_key, so the
    ledger still recognizes the same fact as a duplicate across snapshots."""
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)
    conn = make_players_db()
    r1 = _pipeline(_config(conn), ledger)
    assert r1.run().received == 9

    v1 = _config(conn).provider.open_snapshot().version
    conn.execute("UPDATE players SET name = 'Adah' WHERE id = '1'")
    conn.commit()
    v2 = _config(conn).provider.open_snapshot().version
    assert v1 != v2  # a genuinely different read

    # Entity's semantic_key derives from id (unchanged) => same candidate_id =>
    # duplicate. The renamed display_name rides in content only, which is not
    # the idempotency anchor.
    replay = _pipeline(_config(conn), ledger).run()
    assert replay.received == 0
    assert replay.duplicates == 9
    ledger.close()


def test_evidence_is_produced_and_resolves_for_each_candidate(tmp_path) -> None:
    ledger = SqliteCandidateLedger(str(tmp_path / "ledger.db"))
    registry = SqliteEvidenceRegistry(str(tmp_path / "evidence.db"))
    config = _config(make_players_db())
    reader = config.reader()

    recorder = StructuredEvidenceRecorder(
        registry,
        snapshot_version=reader.snapshot_version,
        source_type=reader.source_type,
        source_locator=reader.locator,
        clock=FixedClock(NOW),
    )
    by_coord = recorder.record(reader.read())
    assert len(by_coord) == len(PLAYER_ROWS)  # one Evidence per source row

    report = config.build_pipeline(
        sink=ledger, ledger_reader=ledger, clock=FixedClock(NOW), run_id="run-fixed"
    ).run()
    assert report.received == 9

    candidates = [e.candidate for e in ledger.ledger_entries()]
    linked = recorder.link(candidates)
    assert linked == 9  # every candidate cites its row's evidence

    # Every candidate's evidence resolves to real, PRESENT Evidence.
    for candidate in candidates:
        resolved = registry.resolve(candidate.candidate_id)
        assert len(resolved) == 1
        assert resolved[0].availability.value == "PRESENT"

    ledger.close()
    registry.close()


def test_evidence_production_and_linking_are_idempotent(tmp_path) -> None:
    ledger = SqliteCandidateLedger(str(tmp_path / "ledger.db"))
    registry = SqliteEvidenceRegistry(str(tmp_path / "evidence.db"))
    config = _config(make_players_db())
    reader = config.reader()
    recorder = StructuredEvidenceRecorder(
        registry,
        snapshot_version=reader.snapshot_version,
        source_type=reader.source_type,
        source_locator=reader.locator,
        clock=FixedClock(NOW),
    )
    recorder.record(reader.read())
    recorder.record(reader.read())  # deterministic ids => INSERT OR REPLACE no-op

    config.build_pipeline(sink=ledger, clock=FixedClock(NOW), run_id="run-fixed").run()
    candidates = [e.candidate for e in ledger.ledger_entries()]
    recorder.link(candidates)
    recorder.link(candidates)  # INSERT OR IGNORE => still one ref per candidate

    for candidate in candidates:
        assert len(registry.refs_for(candidate.candidate_id)) == 1
    ledger.close()
    registry.close()
