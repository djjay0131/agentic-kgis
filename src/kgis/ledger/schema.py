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

SCHEMA_VERSION = 2

# The single "live row" predicate, shared verbatim by three places that MUST
# agree (Issue #16): the partial unique index below, the sink's duplicate
# lookup (`store.submit`), and the default listing filter
# (`store.ledger_entries`). A revoked or erased row is a retained tombstone,
# NOT a live row, so a new live row of the same `dedup_key` may coexist with
# it — which is what makes a revoked/erased `semantic_key` resubmittable.
LIVE_ROW_PREDICATE = "revoked_at IS NULL AND erased_at IS NULL"

# v1 shipped a FULL unique index on `dedup_key`; v2 makes it PARTIAL over live
# rows only (see LIVE_ROW_PREDICATE) so a tombstone and a fresh live row can
# share a key. Built from the constant so index and query predicates cannot
# drift apart.
_DEDUP_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_ledger_dedup "
    f"ON ledger_entries (dedup_key) WHERE {LIVE_ROW_PREDICATE}"
)

SCHEMA_SQL = f"""
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
{_DEDUP_INDEX_SQL};
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


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Idempotently upgrade an existing ledger DB in place.

    Only forward migrations; each step is written to be safe to re-run.
    """
    if from_version < 2:
        # v1 -> v2: replace the FULL unique index on `dedup_key` with a PARTIAL
        # unique index over live rows (Issue #16). Dropping and recreating is
        # safe: v1 data is globally unique by `dedup_key` (the old full index
        # enforced it), so a partial unique index over a subset never conflicts.
        conn.execute("DROP INDEX IF EXISTS ix_ledger_dedup")
        conn.execute(_DEDUP_INDEX_SQL)


def open_ledger_db(path: str | os.PathLike[str] | Literal[":memory:"]) -> sqlite3.Connection:
    """Open (creating if absent) a ledger database with the DDL applied.

    A fresh DB is created at the current `SCHEMA_VERSION`; an existing DB at an
    older version is migrated forward in place (idempotently) before it is
    handed back, so reopening a v1 database upgrades its dedup index to the
    partial (live-row) form rather than silently keeping the old full index.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    stored = conn.execute(
        "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
    ).fetchone()
    # No row => brand-new DB just created by SCHEMA_SQL above (already current).
    # A row below SCHEMA_VERSION => an older on-disk DB that must be migrated.
    if stored is not None and int(stored["value"]) < SCHEMA_VERSION:
        _migrate(conn, int(stored["value"]))
    conn.execute(
        "INSERT OR REPLACE INTO ledger_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
