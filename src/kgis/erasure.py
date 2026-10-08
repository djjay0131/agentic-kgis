"""Atomic erasure across the candidate ledger and the evidence registry (issue #61).

`SqliteCandidateLedger.erase()` governs one row of one store. The passage text a
candidate cites lives in a different store — the evidence registry — where up to
`_MAX_INLINE_CHARS` (4000) characters of source text plus the candidate's refs
survive a ledger-only erase. The 2026-10-07 KGPS provenance audit recorded this as
upstream prerequisite U8. `ErasureCoordinator` closes the gap:

- remove the erased candidate's evidence refs;
- redact every evidence item those refs orphaned — `content=None`, `payload_hash`
  retained, availability still `PRESENT`, plus a `redacted_at` / `redaction_reason`
  marker — so it stays provable by hash and no inline passage survives;
- record each redaction in the ledger's append-only `audit_records` stream
  (`kind='redact'`), keyed to the erased candidate.

Evidence still referenced by any other candidate is left intact. A revoked (but
not erased) candidate keeps its refs, so shared evidence stays readable and
`resolve()` keeps returning it.

Connection shapes
-----------------

The two stores share a SQLite database only sometimes, so both are handled:

- **Same connection** — one `sqlite3.Connection` handed to both stores. The
  ledger erase and the registry cascade run inside a single transaction and
  commit together; any failure rolls the whole thing back. Fully atomic.
- **Separate connections** — the ordinary case, often separate files. Both
  writes are staged and then committed registry-first, ledger-second, so a
  failure before any commit rolls both back and a failure between the two
  commits leaves content already redacted rather than leaked. That residual
  window — registry committed, ledger commit failing — is surfaced as
  `ErasureIncompleteError`, never hidden.

Deliberate limit: with separate connections to the *same* database file, two
SQLite writers cannot both stage changes, so the cascade can never be atomic.
`ErasureCoordinator` refuses that shape at construction with
`ConfigurationError` (detected by comparing each connection's `PRAGMA
database_list` file), rather than letting it fail later as an opaque lock error.
Wire the two stores to the *same connection* when they share a file.

Idempotence: erasing an already-erased candidate is a no-op. The ledger row
keeps its `erased_at` tombstone and the operation records no second erase
transition and no duplicate redaction audit; `ErasureReport.already_erased` is
`True`.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from kgis.errors import ConfigurationError, KgisError
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.ledger.row import _iso
from kgis.ledger.store import SqliteCandidateLedger


def _database_file(conn: sqlite3.Connection) -> str | None:
    """The on-disk path behind a connection's `main` database, or `None`.

    `None` for an in-memory database (SQLite reports an empty file), so two
    distinct `:memory:` connections are correctly seen as *different*
    databases, not the same one.
    """
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            path: str = row[2]
            return path or None
    return None


class ErasureIncompleteError(KgisError):
    """The evidence cascade committed but the ledger erase did not.

    Only reachable for separate connections when the final ledger `commit()`
    fails (disk or I/O fault) *after* the registry commit succeeded. Nothing is
    hidden: the refs are removed and the passage text is already redacted, so
    the privacy objective is met; only the ledger erase row and its redaction
    audit were rolled back. Retrying `ErasureCoordinator.erase` finishes the
    ledger half. The retry cannot re-emit the redaction audit because the refs
    are already gone, but the redaction stays provable from the evidence table's
    durable `redacted_at` / `redaction_reason` marker.
    """


@dataclass(frozen=True)
class ErasureReport:
    """What one `ErasureCoordinator.erase` did.

    `removed_refs` is every evidence id the candidate cited; `redacted` is the
    orphaned subset whose inline content was dropped; `preserved` is the subset
    still referenced elsewhere and therefore left readable. `already_erased` is
    `True` for the idempotent no-op path, where the candidate already carried an
    erasure tombstone and nothing was written.
    """

    candidate_id: str
    removed_refs: tuple[str, ...]
    redacted: tuple[str, ...]
    preserved: tuple[str, ...]
    already_erased: bool = False


class ErasureCoordinator:
    """Erase a candidate across the ledger *and* its evidence atomically.

    Construct once per `(ledger, registry)` pair. Two different connections to
    the *same* database file are rejected here with `ConfigurationError`:
    SQLite admits one writer, so the cascade could not be staged atomically and
    would surface later as an opaque lock error. Passing the *same* connection
    object to both stores is the supported shared-file shape.
    """

    def __init__(
        self, ledger: SqliteCandidateLedger, registry: SqliteEvidenceRegistry
    ) -> None:
        ledger_conn = ledger._conn
        registry_conn = registry._conn
        if ledger_conn is not registry_conn:
            ledger_file = _database_file(ledger_conn)
            registry_file = _database_file(registry_conn)
            if (
                ledger_file is not None
                and registry_file is not None
                and os.path.realpath(ledger_file) == os.path.realpath(registry_file)
            ):
                raise ConfigurationError(
                    "ledger and evidence registry point at the same SQLite file "
                    f"({ledger_file!r}) through different connections; SQLite admits "
                    "one writer, so the erasure cascade cannot be atomic. Pass the "
                    "same connection object to both stores."
                )
        self._ledger = ledger
        self._registry = registry

    def erase(self, candidate_id: str, *, reason: str, actor: str) -> ErasureReport:
        """Erase `candidate_id` and cascade to its evidence.

        Idempotent: erasing an already-erased candidate writes nothing and
        returns `ErasureReport(already_erased=True)` with empty tuples, so a
        retry never records a second erase transition or a duplicate redaction
        audit.

        Raises `PermissionError` when the ledger's consumer profile has not
        enabled erasure, `KeyError` when no row carries `candidate_id`, and
        `ErasureIncompleteError` on the separate-connection residual window.
        """
        if not self._ledger.profile.erasure_enabled:
            raise PermissionError("erasure not enabled for this consumer profile")
        row = self._ledger.row(candidate_id)
        if row is None:
            raise KeyError(f"no ledger entry for candidate_id {candidate_id!r}")
        if row.is_erased:
            return ErasureReport(
                candidate_id=candidate_id,
                removed_refs=(),
                redacted=(),
                preserved=(),
                already_erased=True,
            )
        redacted_at = _iso(self._ledger._now())
        assert redacted_at is not None  # self._ledger._now() never returns None

        if self._ledger._conn is self._registry._conn:
            return self._erase_shared(
                candidate_id, reason=reason, actor=actor, redacted_at=redacted_at
            )
        return self._erase_separate(
            candidate_id, reason=reason, actor=actor, redacted_at=redacted_at
        )

    def revoke(self, candidate_id: str, *, reason: str, actor: str) -> None:
        """Withdraw a candidate, retaining its evidence refs by design.

        A revoke hides the ledger row from default listings but retains the
        payload and its support (ADR-0013), so `registry.resolve(candidate_id)`
        still returns the cited evidence afterwards. Only `erase` redacts;
        `revoke` is a documented ledger-only operation.
        """
        self._ledger.revoke(candidate_id, reason=reason, actor=actor)

    # --- internals -----------------------------------------------------------

    def _cascade(
        self, candidate_id: str, *, reason: str, redacted_at: str
    ) -> tuple[list[str], list[tuple[str, str]], list[str]]:
        """Stage ref removal + orphan redaction. Writes on the registry conn."""
        removed = self._registry._remove_subject_refs_stmt(candidate_id)
        orphan_set = set(self._registry._orphan_evidence_stmt(removed))
        redacted: list[tuple[str, str]] = []
        for evidence_id in removed:
            if evidence_id not in orphan_set:
                continue
            payload_hash = self._registry._redact_evidence_stmt(
                evidence_id, reason=reason, redacted_at=redacted_at
            )
            if payload_hash is not None:
                redacted.append((evidence_id, payload_hash))
        preserved = [eid for eid in removed if eid not in orphan_set]
        return removed, redacted, preserved

    def _audit(
        self,
        candidate_id: str,
        redacted: list[tuple[str, str]],
        *,
        reason: str,
        actor: str,
    ) -> None:
        for evidence_id, payload_hash in redacted:
            self._ledger.record_redaction(
                candidate_id,
                evidence_id=evidence_id,
                evidence_payload_hash=payload_hash,
                reason=reason,
                actor=actor,
            )

    def _erase_shared(
        self, candidate_id: str, *, reason: str, actor: str, redacted_at: str
    ) -> ErasureReport:
        conn = self._ledger._conn
        try:
            self._ledger._apply_erase(candidate_id, reason=reason, actor=actor)
            removed, redacted, preserved = self._cascade(
                candidate_id, reason=reason, redacted_at=redacted_at
            )
            self._audit(candidate_id, redacted, reason=reason, actor=actor)
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        return ErasureReport(
            candidate_id=candidate_id,
            removed_refs=tuple(removed),
            redacted=tuple(evidence_id for evidence_id, _ in redacted),
            preserved=tuple(preserved),
        )

    def _erase_separate(
        self, candidate_id: str, *, reason: str, actor: str, redacted_at: str
    ) -> ErasureReport:
        ledger_conn = self._ledger._conn
        registry_conn = self._registry._conn
        try:
            removed, redacted, preserved = self._cascade(
                candidate_id, reason=reason, redacted_at=redacted_at
            )
            self._ledger._apply_erase(candidate_id, reason=reason, actor=actor)
            self._audit(candidate_id, redacted, reason=reason, actor=actor)
        except Exception:
            ledger_conn.rollback()
            registry_conn.rollback()
            raise
        # Registry first: content is unreadable even if the ledger commit then
        # fails, so the privacy objective is met before the row governance lands.
        try:
            registry_conn.commit()
        except Exception:
            ledger_conn.rollback()
            registry_conn.rollback()
            raise
        try:
            ledger_conn.commit()
        except Exception as exc:
            ledger_conn.rollback()
            raise ErasureIncompleteError(
                "evidence cascade committed but the ledger erase did not "
                f"(candidate_id={candidate_id!r}); retry the erase to finish"
            ) from exc
        return ErasureReport(
            candidate_id=candidate_id,
            removed_refs=tuple(removed),
            redacted=tuple(evidence_id for evidence_id, _ in redacted),
            preserved=tuple(preserved),
        )
