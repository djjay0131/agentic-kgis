# tests/kgis/ledger/test_reader.py
from kg_contracts.stores import CandidateSink
from kg_contracts.testing.contract import LedgerReaderContract
from kgis.ledger.contract import PersistentLedgerContract
from kgis.ledger.store import SqliteCandidateLedger


class TestSqliteLedgerReader(LedgerReaderContract):
    def make_ledger(self) -> CandidateSink:
        return SqliteCandidateLedger(":memory:")


class TestSqliteLedgerPersistence(PersistentLedgerContract):
    def open_ledger(self, path: str) -> SqliteCandidateLedger:
        return SqliteCandidateLedger(path)


def test_capabilities_declare_temporal():
    assert SqliteCandidateLedger(":memory:").capabilities().supports_temporal_queries is True
