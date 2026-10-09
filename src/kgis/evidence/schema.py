"""SQLite schema for the evidence registry (spec §5.3)."""

from __future__ import annotations

import os
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id      TEXT PRIMARY KEY,
    source_type      TEXT NOT NULL,
    source_locator   TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    availability     TEXT NOT NULL,
    absence_reason   TEXT,
    payload_hash     TEXT,
    valid_from       TEXT,
    valid_to         TEXT,
    evidence_json    TEXT NOT NULL,
    redacted_at      TEXT,   -- set when inline content was erased (issue #61)
    redaction_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_evidence_avail ON evidence (availability);

CREATE TABLE IF NOT EXISTS evidence_refs (
    subject_id   TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    relationship TEXT NOT NULL,
    PRIMARY KEY (subject_id, evidence_id, relationship)
);
CREATE INDEX IF NOT EXISTS ix_refs_subject ON evidence_refs (subject_id);
CREATE INDEX IF NOT EXISTS ix_refs_evidence ON evidence_refs (evidence_id);
"""

# Columns added after the v1 evidence table shipped. Applied idempotently to an
# existing database so a registry opened on an old file gains the redaction
# marker (issue #61) without a table rewrite. Fresh databases get them from
# SCHEMA_SQL above.
_REDACTION_COLUMNS = (
    ("redacted_at", "TEXT"),
    ("redaction_reason", "TEXT"),
)

# Indexes added after the v1 evidence tables shipped. `ix_refs_evidence` backs
# the evidence -> subjects reverse lookup (issue #59: `subjects_for`). Fresh
# databases get it from SCHEMA_SQL above; this idempotent step brings an
# existing database forward, including a caller-supplied connection.
_REFS_INDEXES = (("ix_refs_evidence", "evidence_refs", "evidence_id"),)


def ensure_evidence_schema(conn: sqlite3.Connection) -> None:
    """Add post-v1 columns and indexes to an existing schema, idempotently.

    A no-op when the `evidence` table does not exist yet (a pre-built
    connection whose caller has not applied the schema, which was already
    unsupported) or when the columns/indexes are present. `ALTER TABLE ADD
    COLUMN` is safe to re-run only guarded like this, so the column set is
    probed first; `CREATE INDEX IF NOT EXISTS` is inherently idempotent.
    """
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'evidence'"
    ).fetchone()
    if table is None:
        return
    present = {row[1] for row in conn.execute("PRAGMA table_info(evidence)")}
    for name, kind in _REDACTION_COLUMNS:
        if name not in present:
            conn.execute(f"ALTER TABLE evidence ADD COLUMN {name} {kind}")
    refs_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'evidence_refs'"
    ).fetchone()
    if refs_table is not None:
        for name, index_table, column in _REFS_INDEXES:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {name} ON {index_table} ({column})"
            )


def open_evidence_db(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    ensure_evidence_schema(conn)
    conn.commit()
    return conn
