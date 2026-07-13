from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.assertions import (
    Assertion,
    CanonicalEntity,
    ConflictRecord,
    ConflictStatus,
    CurationStatus,
)
from kg_contracts.candidates import CandidateScores
from kg_contracts.evidence import EvidenceRef, EvidenceRelationship, Provenance, ValidPeriod
from kg_contracts.identity import EntityRef, new_identity_id

PROV = Provenance(source="unit-test", actor="tester")
SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
NOW = datetime(2026, 7, 12, tzinfo=UTC)


def test_curation_status_has_exactly_three_members():
    assert set(CurationStatus.__members__) == {"ACTIVE", "SUPERSEDED", "REVOKED"}
    assert "PROVISIONAL" not in CurationStatus.__members__


def test_canonical_entity_valid_and_frozen():
    iid = new_identity_id("baseball")
    alias = EntityRef(entity_type="Player", namespace="usssa", key="12345")
    entity = CanonicalEntity(
        identity_id=iid,
        entity_type="Player",
        aliases=(alias,),
        created_at=NOW,
        curation_epoch=1,
    )
    assert entity.status is CurationStatus.ACTIVE
    with pytest.raises(ValidationError):
        entity.entity_type = "Coach"  # frozen


def test_canonical_entity_rejects_bad_identity_and_empty_aliases():
    alias = EntityRef(entity_type="Player", namespace="usssa", key="12345")
    with pytest.raises(ValidationError, match="identity"):
        CanonicalEntity(
            identity_id="Player:usssa:12345",
            entity_type="Player",
            aliases=(alias,),
            created_at=NOW,
            curation_epoch=1,
        )
    iid = new_identity_id("baseball")
    with pytest.raises(ValidationError, match="aliases"):
        CanonicalEntity(
            identity_id=iid,
            entity_type="Player",
            aliases=(),
            created_at=NOW,
            curation_epoch=1,
        )


def test_assertion_valid_with_object_value_and_open_valid_period():
    subject = new_identity_id("baseball")
    assertion = Assertion(
        subject_identity=subject,
        predicate="batting_avg",
        object_value=0.312,
        object_identity=None,
        status=CurationStatus.ACTIVE,
        valid_period=ValidPeriod(),
        recorded_at=NOW,
        scores=SCORES,
        evidence_refs=(),
        authority="usssa",
        provenance=PROV,
        curation_epoch=1,
        trace_id="trace_test",
    )
    assert assertion.assertion_id.startswith("as_")
    assert assertion.superseded_at is None
    assert assertion.valid_period.valid_from is None
    assert assertion.valid_period.valid_to is None


def test_assertion_requires_exactly_one_object_field():
    subject = new_identity_id("baseball")
    kwargs = dict(
        subject_identity=subject,
        predicate="plays_for",
        status=CurationStatus.ACTIVE,
        valid_period=ValidPeriod(),
        recorded_at=NOW,
        scores=SCORES,
        evidence_refs=(),
        authority="usssa",
        provenance=PROV,
        curation_epoch=1,
        trace_id="trace_test",
    )
    with pytest.raises(ValidationError, match="exactly one"):
        Assertion(**kwargs, object_value=None, object_identity=None)
    with pytest.raises(ValidationError, match="exactly one"):
        Assertion(**kwargs, object_value="x", object_identity=new_identity_id("baseball"))
    with pytest.raises(ValidationError, match="identity"):
        Assertion(**kwargs, object_value=None, object_identity="Team:usssa:red-sox")


def test_assertion_scores_and_nonempty_authority():
    subject = new_identity_id("baseball")
    object_id = new_identity_id("baseball")
    assertion = Assertion(
        subject_identity=subject,
        predicate="plays_for",
        object_value=None,
        object_identity=object_id,
        status=CurationStatus.ACTIVE,
        valid_period=ValidPeriod(),
        recorded_at=NOW,
        scores=SCORES,
        evidence_refs=(EvidenceRef(evidence_id="ev_1", relationship=EvidenceRelationship.SUPPORTS),),
        authority="usssa",
        provenance=PROV,
        curation_epoch=1,
        trace_id="trace_test",
    )
    assert assertion.scores == SCORES
    with pytest.raises(ValidationError):
        Assertion(
            subject_identity=subject,
            predicate="plays_for",
            object_value=None,
            object_identity=object_id,
            status=CurationStatus.ACTIVE,
            valid_period=ValidPeriod(),
            recorded_at=NOW,
            scores=SCORES,
            evidence_refs=(),
            authority="",
            provenance=PROV,
            curation_epoch=1,
            trace_id="trace_test",
        )


def test_conflict_record_requires_at_least_two_assertion_ids_and_preferred_membership():
    with pytest.raises(ValidationError):
        ConflictRecord(
            assertion_ids=("as_1",),
            preferred_assertion_id=None,
            resolution_policy=None,
            status=ConflictStatus.UNRESOLVED,
        )
    with pytest.raises(ValidationError, match="member"):
        ConflictRecord(
            assertion_ids=("as_1", "as_2"),
            preferred_assertion_id="as_3",
            resolution_policy=None,
            status=ConflictStatus.RESOLVED,
        )


def test_conflict_record_setting_preferred_forces_resolved():
    with pytest.raises(ValidationError, match="RESOLVED"):
        ConflictRecord(
            assertion_ids=("as_1", "as_2"),
            preferred_assertion_id="as_1",
            resolution_policy=None,
            status=ConflictStatus.UNRESOLVED,
        )
    record = ConflictRecord(
        assertion_ids=("as_1", "as_2"),
        preferred_assertion_id="as_1",
        resolution_policy="highest_authority",
        status=ConflictStatus.RESOLVED,
    )
    assert record.conflict_id.startswith("cf_")
    assert record.status is ConflictStatus.RESOLVED
