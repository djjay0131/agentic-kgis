"""Durable evidence registry (spec §5.3): Evidence never silently dropped."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterable, Sequence

from kg_contracts.evidence import (
    Evidence,
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
)

from kgis.evidence.schema import ensure_evidence_schema, open_evidence_db


class EvidenceNotFoundError(KeyError):
    """A cited evidence_id has no stored Evidence (spec §5.3: never silently dropped)."""


def _content_digest(content: str) -> str:
    """A payload hash for PRESENT evidence that carried only inline content.

    Erasure (issue #61) keeps `payload_hash` and drops `content`; evidence that
    arrived without a hash still gets one, so the tombstone stays provable
    (PRESENT-by-hash) and the original bytes remain checkable without being
    readable.
    """
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


class SqliteEvidenceRegistry:
    def __init__(
        self, database: str | os.PathLike[str] | sqlite3.Connection = ":memory:"
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
            # A caller-supplied connection carries an already-applied schema;
            # bring it forward if it predates the redaction marker (issue #61).
            ensure_evidence_schema(self._conn)
        else:
            self._conn = open_evidence_db(database)

    def close(self) -> None:
        self._conn.close()

    def _put_stmt(self, evidence: Evidence) -> None:
        """Execute the INSERT for one Evidence without committing."""
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

    def put(self, evidence: Evidence) -> None:
        self._put_stmt(evidence)
        self._conn.commit()

    def put_many(self, items: Iterable[Evidence]) -> None:
        # Atomic batch write: all rows land in a single transaction. If any
        # insert fails partway, roll the whole batch back rather than leaving a
        # partially-applied write uncommitted on the shared connection — the
        # same discipline as `add_refs` and the ledger's transition writes.
        try:
            for item in items:
                self._put_stmt(item)
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

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

    # --- erasure cascade primitives (issue #61) ------------------------------
    #
    # These are the registry half of `kgis.erasure.ErasureCoordinator`. The
    # `_..._stmt` variants write without committing so a coordinator that shares
    # one SQLite connection can wrap ledger + registry changes in a single
    # transaction; the public variants commit with the same rollback-on-failure
    # discipline as the rest of this store.

    def _remove_subject_refs_stmt(self, subject_id: str) -> list[str]:
        """Delete every ref `subject_id` cites; return the evidence ids it cited."""
        cited = [
            row["evidence_id"]
            for row in self._conn.execute(
                "SELECT DISTINCT evidence_id FROM evidence_refs WHERE subject_id = ?",
                (subject_id,),
            ).fetchall()
        ]
        self._conn.execute("DELETE FROM evidence_refs WHERE subject_id = ?", (subject_id,))
        return cited

    def _orphan_evidence_stmt(self, evidence_ids: Iterable[str]) -> list[str]:
        """Of `evidence_ids`, those no subject references any more.

        Checked against the whole `evidence_refs` table, not just live
        candidates: a revoked (but not erased) candidate retains its refs, so
        evidence it shares must stay readable. "Orphan" means zero refs left.
        """
        orphans: list[str] = []
        for evidence_id in evidence_ids:
            still_referenced = self._conn.execute(
                "SELECT 1 FROM evidence_refs WHERE evidence_id = ? LIMIT 1",
                (evidence_id,),
            ).fetchone()
            if still_referenced is None:
                orphans.append(evidence_id)
        return orphans

    def _redact_evidence_stmt(
        self, evidence_id: str, *, reason: str | None, redacted_at: str
    ) -> str | None:
        """Drop inline content from one evidence row, keeping it PRESENT-by-hash.

        Returns the retained `payload_hash` when content was actually removed, or
        `None` when the row is absent, not PRESENT, or already content-free.
        ABSENT/ERROR evidence carries no content to redact.
        """
        row = self._conn.execute(
            "SELECT evidence_json, payload_hash FROM evidence WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            return None
        evidence = Evidence.model_validate_json(row["evidence_json"])
        if (
            evidence.availability is not EvidenceAvailability.PRESENT
            or evidence.content is None
        ):
            return None
        payload_hash = evidence.payload_hash or _content_digest(evidence.content)
        redacted = evidence.model_copy(
            update={"content": None, "payload_hash": payload_hash}
        )
        self._conn.execute(
            "UPDATE evidence SET evidence_json = ?, payload_hash = ?, redacted_at = ?, "
            "redaction_reason = ? WHERE evidence_id = ?",
            (redacted.model_dump_json(), payload_hash, redacted_at, reason, evidence_id),
        )
        return payload_hash

    def redaction(self, evidence_id: str) -> tuple[str | None, str | None] | None:
        """The `(redacted_at, redaction_reason)` marker, or `None` if no such row."""
        row = self._conn.execute(
            "SELECT redacted_at, redaction_reason FROM evidence WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            return None
        return (row["redacted_at"], row["redaction_reason"])
