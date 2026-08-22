import sqlite3

import pytest

from kg_contracts.curation import ProcessingState as PS
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.config import BASEBALL_AI_PROFILE
from kgis.ledger.store import SqliteCandidateLedger


def test_every_transition_appends_an_audit_record():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="a/1")
    ledger.submit([c])                                  # None -> RECEIVED
    ledger.transition(c.candidate_id, PS.VALIDATED, actor="v")
    kinds = [r["kind"] for r in ledger._audit.records_for(c.candidate_id)]
    assert kinds == ["transition", "transition"]


def test_audit_records_are_append_only():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="a/2")
    ledger.submit([c])
    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("UPDATE audit_records SET actor='x'")
    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("DELETE FROM audit_records")


def test_erase_leaves_hash_only_tombstone_in_audit():
    ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
    c = make_entity_candidate(key="a/3")
    ledger.submit([c])
    ledger.erase(c.candidate_id, reason="gdpr", actor="dpo")
    tomb = [r for r in ledger._audit.records_for(c.candidate_id) if r["kind"] == "erase"]
    assert len(tomb) == 1
    assert tomb[0]["payload_hash"]           # hash retained
    assert ledger.row(c.candidate_id).payload_json is None  # payload gone
