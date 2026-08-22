"""Append-only audit stream (spec §7.8). Immutability enforced at rest by
SQLite triggers that abort any UPDATE/DELETE on `audit_records`.
"""

from __future__ import annotations

import sqlite3

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_records
BEGIN SELECT RAISE(ABORT, 'audit_records is append-only (spec 7.8)'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_records
BEGIN SELECT RAISE(ABORT, 'audit_records is append-only (spec 7.8)'); END;
"""


class SqliteAuditStream:
    """Append-only writer/reader for the `audit_records` table (spec §7.8)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_TRIGGERS)

    def append(
        self,
        *,
        candidate_id: str,
        transition_id: int,
        kind: str,
        from_state: str | None,
        to_state: str | None,
        payload_hash: str,
        reason: str | None,
        actor: str,
        recorded_at: str,
        detail: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_records (candidate_id, transition_id, kind, from_state, "
            "to_state, payload_hash, reason, actor, recorded_at, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (candidate_id, transition_id, kind, from_state, to_state, payload_hash,
             reason, actor, recorded_at, detail),
        )

    def records_for(self, candidate_id: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM audit_records WHERE candidate_id = ? ORDER BY audit_id",
                (candidate_id,),
            ).fetchall()
        )
