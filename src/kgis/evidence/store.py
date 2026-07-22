"""Durable evidence registry (spec §5.3): Evidence never silently dropped."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable

from kg_contracts.evidence import Evidence

from kgis.evidence.schema import open_evidence_db


class SqliteEvidenceRegistry:
    def __init__(
        self, database: str | os.PathLike[str] | sqlite3.Connection = ":memory:"
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn = open_evidence_db(database)

    def close(self) -> None:
        self._conn.close()

    def put(self, evidence: Evidence) -> None:
        vt = evidence.valid_time
        self._conn.execute(
            "INSERT OR REPLACE INTO evidence (evidence_id, source_type, source_locator, "
            "observed_at, availability, absence_reason, payload_hash, valid_from, valid_to, "
            "evidence_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.evidence_id, evidence.source_type, evidence.source_locator,
                evidence.observed_at.isoformat(), evidence.availability.value,
                evidence.absence_reason.value if evidence.absence_reason else None,
                evidence.payload_hash,
                vt.valid_from.isoformat() if vt and vt.valid_from else None,
                vt.valid_to.isoformat() if vt and vt.valid_to else None,
                evidence.model_dump_json(),
            ),
        )
        self._conn.commit()

    def put_many(self, items: Iterable[Evidence]) -> None:
        for item in items:
            self.put(item)

    def get(self, evidence_id: str) -> Evidence | None:
        r = self._conn.execute(
            "SELECT evidence_json FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        return Evidence.model_validate_json(r["evidence_json"]) if r is not None else None
