"""kgis-local reusable suite: any *persistent* candidate ledger must keep data
and idempotency across a reopen. NOT a kg_contracts edit — the ports' own
suites (`CandidateSinkContract`, `LedgerReaderContract`) stay in kg_contracts.
"""

from __future__ import annotations

from pathlib import Path

from kg_contracts.stores import SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.store import SqliteCandidateLedger


class PersistentLedgerContract:
    """Subclass and implement `open_ledger(path)`."""

    def open_ledger(self, path: str) -> SqliteCandidateLedger:
        raise NotImplementedError

    def test_data_survives_reopen(self, tmp_path: Path) -> None:
        path = str(tmp_path / "ledger.db")
        led = self.open_ledger(path)
        c = make_entity_candidate(key="persist/1")
        led.submit([c])
        led.close()

        reopened = self.open_ledger(path)
        entry = reopened.ledger_entry(c.candidate_id)
        assert entry is not None
        assert entry.candidate.candidate_id == c.candidate_id
        reopened.close()

    def test_cross_run_replay_is_duplicate(self, tmp_path: Path) -> None:
        path = str(tmp_path / "ledger.db")
        led = self.open_ledger(path)
        led.submit([make_entity_candidate(key="persist/2")])
        led.close()

        reopened = self.open_ledger(path)
        result = reopened.submit([make_entity_candidate(key="persist/2")])
        assert result.outcomes[0].status is SubmissionStatus.DUPLICATE
        reopened.close()
