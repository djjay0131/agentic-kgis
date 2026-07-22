from kg_contracts.stores import CandidateSink, SubmissionStatus
from kg_contracts.testing.contract import CandidateSinkContract
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.store import SqliteCandidateLedger


class TestSqliteLedgerSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return SqliteCandidateLedger(":memory:")


def test_duplicate_semantic_key_writes_no_second_row():
    ledger = SqliteCandidateLedger(":memory:")
    c1 = make_entity_candidate(key="team/42")
    c2 = make_entity_candidate(key="team/42")  # same semantic key, new candidate_id
    assert ledger.submit([c1]).outcomes[0].status is SubmissionStatus.RECEIVED
    r2 = ledger.submit([c2])
    assert r2.outcomes[0].status is SubmissionStatus.DUPLICATE
    count = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert count == 1
