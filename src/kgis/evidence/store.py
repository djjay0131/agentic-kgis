"""Durable evidence registry (spec §5.3): Evidence never silently dropped."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence

from kg_contracts.evidence import Evidence, EvidenceRef, EvidenceRelationship

from kgis.evidence.schema import open_evidence_db


class EvidenceNotFoundError(KeyError):
    """A cited evidence_id has no stored Evidence (spec §5.3: never silently dropped)."""


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

    def add_refs(self, subject_id: str, refs: Sequence[EvidenceRef]) -> None:
        # Batch, multi-row write: if the executemany fails partway (e.g. a
        # constraint violation on one of the rows), the implicit transaction
        # must not be left uncommitted on the shared connection for a later,
        # unrelated call to commit(). Roll back and propagate, mirroring the
        # ledger's transition()/revoke()/erase() discipline.
        try:
            self._conn.executemany(
                "INSERT OR IGNORE INTO evidence_refs (subject_id, evidence_id, relationship) "
                "VALUES (?, ?, ?)",
                [(subject_id, r.evidence_id, r.relationship.value) for r in refs],
            )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

    def refs_for(
        self, subject_id: str, relationship: EvidenceRelationship | None = None
    ) -> list[EvidenceRef]:
        sql = "SELECT evidence_id, relationship FROM evidence_refs WHERE subject_id = ?"
        params: list[object] = [subject_id]
        if relationship is not None:
            sql += " AND relationship = ?"
            params.append(relationship.value)
        return [
            EvidenceRef(
                evidence_id=r["evidence_id"],
                relationship=EvidenceRelationship(r["relationship"]),
            )
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def resolve(
        self, subject_id: str, relationship: EvidenceRelationship | None = None
    ) -> list[Evidence]:
        resolved: list[Evidence] = []
        for ref in self.refs_for(subject_id, relationship):
            evidence = self.get(ref.evidence_id)
            if evidence is None:
                raise EvidenceNotFoundError(
                    f"evidence_id {ref.evidence_id!r} cited by {subject_id!r} is not stored"
                )
            resolved.append(evidence)
        return resolved
