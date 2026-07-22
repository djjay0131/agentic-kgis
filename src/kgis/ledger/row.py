"""The full persisted ledger row the `LedgerEntry` projection defers to Plan 2."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import Candidate, candidate_adapter
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import LedgerEntry

_UNIT_SEP = ""


def dedup_key(candidate: Candidate) -> str:
    return f"{candidate.graph_id}{_UNIT_SEP}{candidate.semantic_key}"


def payload_hash(candidate: Candidate) -> str:
    return hashlib.sha256(candidate.model_dump_json().encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class LedgerRow(BaseModel):
    """The full persisted `ledger_entries` row (dedup key, retry counter,
    quarantine reason, bitemporal + revoke/erase columns).

    `LedgerEntry` (`kg_contracts.stores`) is deliberately a minimal read
    projection; this is the full row the ledger store persists and reads
    back, with (de)serialization to/from `Candidate` and `LedgerEntry`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    graph_id: str
    dedup_key: str
    candidate_kind: str
    processing_state: ProcessingState
    payload_json: str | None
    payload_hash: str
    retry_count: int = 0
    quarantine_reason: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    received_at: datetime
    recorded_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    erased_at: datetime | None = None
    erasure_reason: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_erased(self) -> bool:
        return self.erased_at is not None

    @classmethod
    def for_candidate(cls, candidate: Candidate, *, recorded_at: datetime) -> LedgerRow:
        period = getattr(candidate, "valid_period", None)
        return cls(
            candidate_id=candidate.candidate_id,
            graph_id=candidate.graph_id,
            dedup_key=dedup_key(candidate),
            candidate_kind=candidate.candidate_kind,
            processing_state=ProcessingState.RECEIVED,
            payload_json=candidate.model_dump_json(),
            payload_hash=payload_hash(candidate),
            received_at=candidate.created_at,
            recorded_at=recorded_at,
            valid_from=getattr(period, "valid_from", None),
            valid_to=getattr(period, "valid_to", None),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> LedgerRow:
        received_at = _parse(row["received_at"])
        recorded_at = _parse(row["recorded_at"])
        assert received_at is not None
        assert recorded_at is not None
        return cls(
            candidate_id=row["candidate_id"],
            graph_id=row["graph_id"],
            dedup_key=row["dedup_key"],
            candidate_kind=row["candidate_kind"],
            processing_state=ProcessingState(row["processing_state"]),
            payload_json=row["payload_json"],
            payload_hash=row["payload_hash"],
            retry_count=row["retry_count"],
            quarantine_reason=row["quarantine_reason"],
            valid_from=_parse(row["valid_from"]),
            valid_to=_parse(row["valid_to"]),
            received_at=received_at,
            recorded_at=recorded_at,
            revoked_at=_parse(row["revoked_at"]),
            revocation_reason=row["revocation_reason"],
            erased_at=_parse(row["erased_at"]),
            erasure_reason=row["erasure_reason"],
        )

    def to_entry(self) -> LedgerEntry | None:
        if self.payload_json is None:
            return None
        return LedgerEntry(
            candidate=candidate_adapter.validate_json(self.payload_json),
            processing_state=self.processing_state,
            received_at=self.received_at,
        )
