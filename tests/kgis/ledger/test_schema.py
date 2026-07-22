from kgis.ledger.schema import SCHEMA_VERSION, open_ledger_db


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
