"""Durable SQLite candidate ledger (ADR-0006 store 1, ADR-0012)."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Callable

from kg_contracts.candidates import Candidate
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import (
    AdapterCapabilities,
    LedgerEntry,
    LedgerReadOptions,
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
)

from kgis.ledger.audit import SqliteAuditStream
from kgis.ledger.config import ConsumerProfile, IdentityMode, IdentityResolver
from kgis.ledger.lifecycle import assert_transition
from kgis.ledger.row import LedgerRow, _iso, dedup_key
from kgis.ledger.schema import open_ledger_db

_INSERT_ENTRY = """
INSERT INTO ledger_entries (
    candidate_id, graph_id, dedup_key, candidate_kind, processing_state,
    payload_json, payload_hash, retry_count, quarantine_reason,
    valid_from, valid_to, received_at, recorded_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SqliteCandidateLedger:
    """`CandidateSink` + `LedgerReader` over one SQLite database."""

    def __init__(
        self,
        database: str | os.PathLike[str] | sqlite3.Connection = ":memory:",
        *,
        now: Callable[[], datetime] | None = None,
        profile: ConsumerProfile | None = None,
        resolver: IdentityResolver | None = None,
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript("")  # no-op; schema assumed applied
        else:
            self._conn = open_ledger_db(database)
        self._now = now if now is not None else (lambda: datetime.now(UTC))
        self._profile = profile if profile is not None else ConsumerProfile()
        self._resolver = resolver
        self._audit = SqliteAuditStream(self._conn)

    def close(self) -> None:
        self._conn.close()

    def _insert_transition(
        self,
        candidate_id: str,
        from_state: ProcessingState | None,
        to_state: ProcessingState,
        *,
        reason: str | None,
        actor: str,
        kind: str = "transition",
    ) -> int:
        now = _iso(self._now())
        assert now is not None  # self._now() never returns None; _iso's None case is unreachable here
        cur = self._conn.execute(
            "INSERT INTO ledger_transitions (candidate_id, from_state, to_state, reason, actor, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                reason,
                actor,
                now,
            ),
        )
        transition_id = int(cur.lastrowid or 0)
        row = self.row(candidate_id)
        payload_hash = row.payload_hash if row is not None else ""
        self._audit.append(
            candidate_id=candidate_id,
            transition_id=transition_id,
            kind=kind,
            from_state=from_state.value if from_state is not None else None,
            to_state=to_state.value,
            payload_hash=payload_hash,
            reason=reason,
            actor=actor,
            recorded_at=now,
            detail=json.dumps({"reason": reason, "actor": actor}),
        )
        return transition_id

    def _duplicate_outcome(self, candidate: Candidate) -> SubmissionOutcome:
        return SubmissionOutcome(
            candidate_id=candidate.candidate_id,
            status=SubmissionStatus.DUPLICATE,
            reason=f"semantic_key already in ledger: {candidate.semantic_key!r}",
            trace_id=candidate.trace_id,
        )

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult:
        outcomes: list[SubmissionOutcome] = []
        try:
            for candidate in candidates:
                key = dedup_key(candidate)
                seen = self._conn.execute(
                    "SELECT 1 FROM ledger_entries WHERE dedup_key = ?", (key,)
                ).fetchone()
                if seen is not None:
                    outcomes.append(self._duplicate_outcome(candidate))
                    continue
                if (
                    self._profile.identity_mode is IdentityMode.REJECT_ONLY
                    and self._resolver is not None
                    and self._resolver.is_ambiguous(candidate)
                ):
                    outcomes.append(
                        SubmissionOutcome(
                            candidate_id=candidate.candidate_id,
                            status=SubmissionStatus.INVALID,
                            reason="ambiguous identity match rejected (REJECT_ONLY)",
                            trace_id=candidate.trace_id,
                        )
                    )
                    continue
                row = LedgerRow.for_candidate(candidate, recorded_at=self._now())
                try:
                    self._conn.execute(
                        _INSERT_ENTRY,
                        (
                            row.candidate_id, row.graph_id, row.dedup_key, row.candidate_kind,
                            row.processing_state.value, row.payload_json, row.payload_hash,
                            row.retry_count, row.quarantine_reason,
                            _iso(row.valid_from),
                            _iso(row.valid_to),
                            _iso(row.received_at), _iso(row.recorded_at),
                        ),
                    )
                except sqlite3.IntegrityError:
                    # Another writer committed the same candidate between our
                    # SELECT fast-path and this INSERT (SELECT-then-INSERT is
                    # inherently racy across connections). ledger_entries has
                    # exactly two UNIQUE constraints an insert of an
                    # already-validated `Candidate` can violate: the
                    # `candidate_id` PRIMARY KEY and the `dedup_key` UNIQUE
                    # index (schema.py `ix_ledger_dedup`). Both mean "this
                    # candidate (or its semantic key) was already admitted" —
                    # i.e. a replay — so treating the violation as DUPLICATE
                    # is correct rather than masking a genuine integrity bug.
                    # No other unique/PK constraint on this table can fire
                    # for a non-duplicate insert.
                    outcomes.append(self._duplicate_outcome(candidate))
                    continue
                self._insert_transition(
                    row.candidate_id, None, ProcessingState.RECEIVED,
                    reason=None, actor=candidate.producer,
                )
                outcomes.append(
                    SubmissionOutcome(
                        candidate_id=candidate.candidate_id,
                        status=SubmissionStatus.RECEIVED,
                        trace_id=candidate.trace_id,
                    )
                )
        except Exception:
            # An unexpected failure mid-batch (row construction, transition
            # insert, etc.) must not strand earlier iterations' uncommitted
            # inserts on the connection for a later, unrelated submit() call
            # to accidentally commit. Roll back the whole batch and propagate.
            self._conn.rollback()
            raise
        self._conn.commit()
        return SubmissionResult(outcomes=tuple(outcomes))

    def transition(
        self,
        candidate_id: str,
        to_state: ProcessingState,
        *,
        actor: str,
        reason: str | None = None,
        increment_retry: bool = False,
        quarantine_reason: str | None = None,
    ) -> LedgerRow:
        row = self.row(candidate_id)
        if row is None or row.is_revoked or row.is_erased:
            raise KeyError(f"no live ledger entry for candidate_id {candidate_id!r}")
        assert_transition(row.processing_state, to_state)
        new_retry = row.retry_count + (1 if increment_retry else 0)
        new_quarantine = quarantine_reason if quarantine_reason is not None else row.quarantine_reason
        try:
            self._conn.execute(
                "UPDATE ledger_entries SET processing_state = ?, retry_count = ?, "
                "quarantine_reason = ? WHERE candidate_id = ?",
                (to_state.value, new_retry, new_quarantine, candidate_id),
            )
            self._insert_transition(
                candidate_id, row.processing_state, to_state, reason=reason, actor=actor
            )
        except Exception:
            # A mid-write failure (e.g. the transition insert) must not
            # strand the just-applied UPDATE uncommitted on the shared
            # connection for a later, unrelated call to commit. Roll back
            # and propagate, mirroring submit()'s discipline.
            self._conn.rollback()
            raise
        self._conn.commit()
        updated = self.row(candidate_id)
        assert updated is not None  # just updated it
        return updated

    def revoke(self, candidate_id: str, *, reason: str, actor: str) -> None:
        row = self.row(candidate_id)
        if row is None or row.is_erased:
            raise KeyError(f"no live ledger entry for candidate_id {candidate_id!r}")
        try:
            self._conn.execute(
                "UPDATE ledger_entries SET revoked_at = ?, revocation_reason = ? "
                "WHERE candidate_id = ?",
                (_iso(self._now()), reason, candidate_id),
            )
            self._insert_transition(
                candidate_id, row.processing_state, row.processing_state,
                reason=f"revoked: {reason}", actor=actor, kind="revoke",
            )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

    def erase(self, candidate_id: str, *, reason: str, actor: str) -> None:
        if not self._profile.erasure_enabled:
            raise PermissionError("erasure not enabled for this consumer profile")
        row = self.row(candidate_id)
        if row is None:
            raise KeyError(f"no ledger entry for candidate_id {candidate_id!r}")
        try:
            self._conn.execute(
                "UPDATE ledger_entries SET payload_json = NULL, erased_at = ?, "
                "erasure_reason = ? WHERE candidate_id = ?",
                (_iso(self._now()), reason, candidate_id),
            )
            self._insert_transition(
                candidate_id, row.processing_state, row.processing_state,
                reason=f"erased: {reason}", actor=actor, kind="erase",
            )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

    def is_revoked(self, candidate_id: str) -> bool:
        row = self.row(candidate_id)
        return row is not None and row.is_revoked

    def is_erased(self, candidate_id: str) -> bool:
        row = self.row(candidate_id)
        return row is not None and row.is_erased

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(supports_temporal_queries=True)

    def row(self, candidate_id: str) -> LedgerRow | None:
        r = self._conn.execute(
            "SELECT * FROM ledger_entries WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return LedgerRow.from_sqlite(r) if r is not None else None

    def ledger_entry(self, candidate_id: str) -> LedgerEntry | None:
        row = self.row(candidate_id)
        return row.to_entry() if row is not None else None

    def ledger_entries(
        self, options: LedgerReadOptions = LedgerReadOptions()
    ) -> list[LedgerEntry]:
        clauses = ["payload_json IS NOT NULL", "revoked_at IS NULL"]
        params: list[object] = []
        if options.graph_id is not None:
            clauses.append("graph_id = ?")
            params.append(options.graph_id)
        if options.processing_states is not None:
            marks = ",".join("?" for _ in options.processing_states)
            clauses.append(f"processing_state IN ({marks})")
            params.extend(s.value for s in options.processing_states)
        sql = (
            "SELECT * FROM ledger_entries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY recorded_at, candidate_id"
        )
        entries: list[LedgerEntry] = []
        for r in self._conn.execute(sql, params).fetchall():
            entry = LedgerRow.from_sqlite(r).to_entry()
            if entry is not None:
                entries.append(entry)
        return entries
