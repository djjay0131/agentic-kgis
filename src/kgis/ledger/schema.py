"""SQLite schema + connection bootstrap for the candidate ledger (spec §3.2).

The ledger is ADR-0006 store 1: immutable, replayable proposed
assertions/entities with their own processing state. Persisted via stdlib
`sqlite3` (owner decision a, ADR-0012) so at-rest immutability (Issue #7)
is real. One physical database, but the ledger read surface is distinct
from any canonical graph reader (ADR-0011).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Literal

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    candidate_id      TEXT PRIMARY KEY,
    graph_id          TEXT NOT NULL,
    dedup_key         TEXT NOT NULL,
    candidate_kind    TEXT NOT NULL,
    processing_state  TEXT NOT NULL,
    payload_json      TEXT,               -- NULL after hard-erase (tombstone)
    payload_hash      TEXT NOT NULL,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    quarantine_reason TEXT,
    valid_from        TEXT,               -- domain valid-time (ISO-8601, nullable)
    valid_to          TEXT,
    received_at       TEXT NOT NULL,      -- candidate.created_at (LedgerEntry projection)
    recorded_at       TEXT NOT NULL,      -- transaction-time the ledger admitted it
    revoked_at        TEXT,
    revocation_reason TEXT,
    erased_at         TEXT,
    erasure_reason    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_ledger_dedup ON ledger_entries (dedup_key);
CREATE INDEX IF NOT EXISTS ix_ledger_state ON ledger_entries (processing_state);
CREATE INDEX IF NOT EXISTS ix_ledger_graph ON ledger_entries (graph_id);

CREATE TABLE IF NOT EXISTS ledger_transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id  TEXT NOT NULL REFERENCES ledger_entries (candidate_id),
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    reason        TEXT,
    actor         TEXT NOT NULL,
    at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transitions_candidate ON ledger_transitions (candidate_id);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id   TEXT NOT NULL,
    transition_id  INTEGER,
    kind           TEXT NOT NULL,          -- 'transition' | 'revoke' | 'erase'
    from_state     TEXT,
    to_state       TEXT,
    payload_hash   TEXT NOT NULL,
    reason         TEXT,
    actor          TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    detail_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_candidate ON audit_records (candidate_id);
"""


def open_ledger_db(path: str | os.PathLike[str] | Literal[":memory:"]) -> sqlite3.Connection:
    """Open (creating if absent) a ledger database with the DDL applied."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO ledger_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
