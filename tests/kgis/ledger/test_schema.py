import sqlite3

from kg_contracts.stores import SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.schema import SCHEMA_VERSION, open_ledger_db
from kgis.ledger.store import SqliteCandidateLedger


def _dedup_index_sql(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_ledger_dedup'"
    ).fetchone()[0]


def test_open_creates_tables_and_is_idempotent(tmp_path):
    path = tmp_path / "ledger.db"
    conn = open_ledger_db(path)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ledger_entries", "ledger_transitions", "audit_records", "ledger_meta"} <= names
    assert conn.execute(
        "SELECT value FROM ledger_meta WHERE key='schema_version'"
    ).fetchone()["value"] == str(SCHEMA_VERSION)
    conn.close()
    # Re-opening the same file must not error (IF NOT EXISTS) and must persist.
    conn2 = open_ledger_db(path)
    assert conn2.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"] == 0
    conn2.close()


def test_memory_db_opens():
    conn = open_ledger_db(":memory:")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_fresh_db_uses_partial_dedup_index():
    conn = open_ledger_db(":memory:")
    assert "WHERE" in _dedup_index_sql(conn).upper()  # partial, live-row only
    conn.close()


def _downgrade_to_v1_full_index(path) -> None:
    """Rewrite a v2 DB into the OLD Plan 2 shape: a FULL unique index on
    dedup_key and schema_version=1 — what an existing on-disk ledger has."""
    conn = sqlite3.connect(str(path))
    conn.execute("DROP INDEX IF EXISTS ix_ledger_dedup")
    conn.execute("CREATE UNIQUE INDEX ix_ledger_dedup ON ledger_entries (dedup_key)")
    conn.execute("UPDATE ledger_meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()


def test_v1_db_migrates_to_partial_index_and_allows_revoked_resubmit(tmp_path):
    """An existing v1 DB (full unique index) must migrate on open to the
    partial index, and a revoked key must then be resubmittable (Issue #16 T3).
    Starts from the OLD schema, not a fresh DB."""
    path = tmp_path / "ledger.db"

    # Build a v1-shaped DB with a real submitted candidate, then verify it is
    # genuinely the old full-unique index (no partial WHERE clause).
    seed = SqliteCandidateLedger(str(path))
    c1 = make_entity_candidate(key="mig/1")
    seed.submit([c1])
    seed.revoke(c1.candidate_id, reason="retraction", actor="ops")
    seed.close()
    _downgrade_to_v1_full_index(path)

    raw = sqlite3.connect(str(path))
    assert "WHERE" not in _dedup_index_sql(raw).upper()  # confirm old full index
    assert raw.execute(
        "SELECT value FROM ledger_meta WHERE key='schema_version'"
    ).fetchone()[0] == "1"
    raw.close()

    # Reopen through the real path: it must migrate to v2 + partial index.
    ledger = SqliteCandidateLedger(str(path))
    assert "WHERE" in _dedup_index_sql(ledger._conn).upper()
    assert ledger._conn.execute(
        "SELECT value FROM ledger_meta WHERE key='schema_version'"
    ).fetchone()[0] == str(SCHEMA_VERSION)

    # The revoked key from the v1 DB is now resubmittable as a new live row.
    c2 = make_entity_candidate(key="mig/1")  # same semantic_key, new candidate_id
    assert ledger.submit([c2]).outcomes[0].status is SubmissionStatus.RECEIVED
    live_ids = {e.candidate.candidate_id for e in ledger.ledger_entries()}
    assert live_ids == {c2.candidate_id}
    ledger.close()
