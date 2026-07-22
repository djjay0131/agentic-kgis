"""SQLite schema for the evidence registry (spec §5.3)."""

from __future__ import annotations

import os
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id    TEXT PRIMARY KEY,
    source_type    TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    availability   TEXT NOT NULL,
    absence_reason TEXT,
    payload_hash   TEXT,
    valid_from     TEXT,
    valid_to       TEXT,
    evidence_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_avail ON evidence (availability);

CREATE TABLE IF NOT EXISTS evidence_refs (
    subject_id   TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    relationship TEXT NOT NULL,
    PRIMARY KEY (subject_id, evidence_id, relationship)
);
CREATE INDEX IF NOT EXISTS ix_refs_subject ON evidence_refs (subject_id);
"""


def open_evidence_db(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
