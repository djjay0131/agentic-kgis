import pytest
from kg_contracts.stores import SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.config import BASEBALL_AI_PROFILE, ConsumerProfile, IdentityMode
from kgis.ledger.store import SqliteCandidateLedger


class _AlwaysAmbiguous:
    def is_ambiguous(self, candidate) -> bool:
        return True


def test_reject_only_rejects_ambiguous_identity():
    ledger = SqliteCandidateLedger(
        ":memory:",
        profile=ConsumerProfile(identity_mode=IdentityMode.REJECT_ONLY),
        resolver=_AlwaysAmbiguous(),
    )
    result = ledger.submit([make_entity_candidate(key="ambi/1")])
    assert result.outcomes[0].status is SubmissionStatus.INVALID
    assert "REJECT_ONLY" in (result.outcomes[0].reason or "")
    assert ledger.ledger_entries() == []


def test_revoke_hides_from_listing_but_retains_data():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="rev/1")
    ledger.submit([c])
    ledger.revoke(c.candidate_id, reason="source retraction", actor="ops")
    assert ledger.is_revoked(c.candidate_id)
    assert ledger.ledger_entries() == []                 # hidden by default
    assert ledger.ledger_entry(c.candidate_id) is not None  # data retained


def test_erase_requires_enabled_profile_then_nulls_payload():
    plain = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="er/1")
    plain.submit([c])
    with pytest.raises(PermissionError):
        plain.erase(c.candidate_id, reason="gdpr", actor="dpo")

    ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
    ledger.submit([c])
    ledger.erase(c.candidate_id, reason="gdpr", actor="dpo")
    assert ledger.is_erased(c.candidate_id)
    assert ledger.ledger_entry(c.candidate_id) is None      # full Candidate gone
    row = ledger.row(c.candidate_id)
    assert row.payload_json is None and row.payload_hash    # hash-only tombstone kept


def test_revoked_key_is_resubmittable_as_new_live_row():
    """A revoked semantic_key releases its dedup_key: a fresh candidate with
    the same semantic_key (new candidate_id) is admitted as a new LIVE row,
    while the revoked tombstone is retained (Issue #16, T2)."""
    ledger = SqliteCandidateLedger(":memory:")
    c1 = make_entity_candidate(key="resub/rev")
    c2 = make_entity_candidate(key="resub/rev")  # same semantic_key, new candidate_id
    assert c1.candidate_id != c2.candidate_id

    assert ledger.submit([c1]).outcomes[0].status is SubmissionStatus.RECEIVED
    ledger.revoke(c1.candidate_id, reason="source retraction", actor="ops")

    # Resubmission of the same semantic_key is admitted, not deduped.
    assert ledger.submit([c2]).outcomes[0].status is SubmissionStatus.RECEIVED

    # Tombstone retained; new row is the only live entry.
    assert ledger.is_revoked(c1.candidate_id)
    assert ledger.ledger_entry(c1.candidate_id) is not None       # revoke retains payload
    live_ids = {e.candidate.candidate_id for e in ledger.ledger_entries()}
    assert live_ids == {c2.candidate_id}
    total = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert total == 2  # tombstone + new live row coexist

    # Audit trail intact: the revoke transition survives the resubmission.
    revokes = ledger._conn.execute(
        "SELECT COUNT(*) c FROM audit_records WHERE candidate_id = ? AND kind = 'revoke'",
        (c1.candidate_id,),
    ).fetchone()["c"]
    assert revokes == 1


def test_erased_key_is_resubmittable_as_new_live_row():
    """An erased semantic_key likewise releases its dedup_key; the hash-only
    tombstone is retained and the resubmission is admitted (Issue #16, T2)."""
    ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
    c1 = make_entity_candidate(key="resub/er")
    c2 = make_entity_candidate(key="resub/er")  # same semantic_key, new candidate_id

    assert ledger.submit([c1]).outcomes[0].status is SubmissionStatus.RECEIVED
    ledger.erase(c1.candidate_id, reason="gdpr", actor="dpo")

    assert ledger.submit([c2]).outcomes[0].status is SubmissionStatus.RECEIVED

    assert ledger.is_erased(c1.candidate_id)
    assert ledger.ledger_entry(c1.candidate_id) is None           # payload gone
    assert ledger.row(c1.candidate_id).payload_hash               # hash tombstone kept
    live_ids = {e.candidate.candidate_id for e in ledger.ledger_entries()}
    assert live_ids == {c2.candidate_id}
    total = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert total == 2
