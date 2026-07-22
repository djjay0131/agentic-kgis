"""Durable SQLite candidate ledger (ADR-0006 store 1, ADR-0012)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Callable

from kg_contracts.candidates import Candidate
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import (
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
)

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
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript("")  # no-op; schema assumed applied
        else:
            self._conn = open_ledger_db(database)
        self._now = now if now is not None else (lambda: datetime.now(UTC))

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
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO ledger_transitions (candidate_id, from_state, to_state, reason, actor, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                reason,
                actor,
                _iso(self._now()),
            ),
        )
        return int(cur.lastrowid or 0)

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult:
        outcomes: list[SubmissionOutcome] = []
        for candidate in candidates:
            key = dedup_key(candidate)
            seen = self._conn.execute(
                "SELECT 1 FROM ledger_entries WHERE dedup_key = ?", (key,)
            ).fetchone()
            if seen is not None:
                outcomes.append(
                    SubmissionOutcome(
                        candidate_id=candidate.candidate_id,
                        status=SubmissionStatus.DUPLICATE,
                        reason=f"semantic_key already in ledger: {candidate.semantic_key!r}",
                        trace_id=candidate.trace_id,
                    )
                )
                continue
            row = LedgerRow.for_candidate(candidate, recorded_at=self._now())
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
        self._conn.commit()
        return SubmissionResult(outcomes=tuple(outcomes))
