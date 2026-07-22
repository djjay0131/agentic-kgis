import pytest
from kg_contracts.curation import ProcessingState as PS
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.lifecycle import IllegalTransitionError
from kgis.ledger.store import SqliteCandidateLedger


def _seed():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="team/9")
    ledger.submit([c])
    return ledger, c


def test_legal_transition_persists_state_and_history():
    ledger, c = _seed()
    row = ledger.transition(c.candidate_id, PS.VALIDATED, actor="validator")
    assert row.processing_state is PS.VALIDATED
    assert ledger.row(c.candidate_id).processing_state is PS.VALIDATED
    hist = ledger._conn.execute(
        "SELECT to_state FROM ledger_transitions WHERE candidate_id=? ORDER BY transition_id",
        (c.candidate_id,),
    ).fetchall()
    assert [h["to_state"] for h in hist] == [PS.RECEIVED.value, PS.VALIDATED.value]


def _transition_count(ledger, candidate_id):
    row = ledger._conn.execute(
        "SELECT COUNT(*) AS n FROM ledger_transitions WHERE candidate_id=?",
        (candidate_id,),
    ).fetchone()
    return row["n"]


def test_illegal_transition_rejected():
    ledger, c = _seed()
    ledger.transition(c.candidate_id, PS.VALIDATED, actor="v")
    ledger.transition(c.candidate_id, PS.ACCEPTED, actor="v")
    before = _transition_count(ledger, c.candidate_id)
    with pytest.raises(IllegalTransitionError, match="ACCEPTED -> RECEIVED"):
        ledger.transition(c.candidate_id, PS.RECEIVED, actor="v")
    assert ledger.row(c.candidate_id).processing_state is PS.ACCEPTED
    assert _transition_count(ledger, c.candidate_id) == before


def test_transition_write_failure_rolls_back(monkeypatch):
    ledger, c = _seed()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ledger, "_insert_transition", _boom)
    with pytest.raises(RuntimeError, match="boom"):
        ledger.transition(c.candidate_id, PS.VALIDATED, actor="v")
    assert ledger.row(c.candidate_id).processing_state is PS.RECEIVED
    assert _transition_count(ledger, c.candidate_id) == 1


def test_retry_and_quarantine_recorded():
    ledger, c = _seed()
    row = ledger.transition(
        c.candidate_id, PS.RETRYABLE_ERROR, actor="worker",
        increment_retry=True, quarantine_reason="db timeout",
    )
    assert row.retry_count == 1
    assert row.quarantine_reason == "db timeout"


def test_transition_missing_candidate_raises():
    ledger = SqliteCandidateLedger(":memory:")
    with pytest.raises(KeyError, match="cand_missing"):
        ledger.transition("cand_missing", PS.VALIDATED, actor="v")
    assert _transition_count(ledger, "cand_missing") == 0


def test_transition_missing_candidate_leaves_other_candidates_untouched():
    ledger, c = _seed()
    before = _transition_count(ledger, c.candidate_id)
    with pytest.raises(KeyError, match="cand_missing"):
        ledger.transition("cand_missing", PS.VALIDATED, actor="v")
    assert ledger.row(c.candidate_id).processing_state is PS.RECEIVED
    assert _transition_count(ledger, c.candidate_id) == before
