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
