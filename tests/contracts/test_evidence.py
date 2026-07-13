from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.evidence import (
    AbsenceReason,
    Evidence,
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    ValidPeriod,
)

NOW = datetime(2026, 7, 12, tzinfo=UTC)
PROV = Provenance(source="unit-test", actor="tester")


def _evidence(**overrides: object) -> Evidence:
    base: dict[str, object] = dict(
        source_type="document",
        source_locator="s3://bucket/doc.pdf#page=3",
        observed_at=NOW,
        availability=EvidenceAvailability.PRESENT,
        content="Player X hit .312 in 2025",
        provenance=PROV,
    )
    base.update(overrides)
    return Evidence(**base)  # type: ignore[arg-type]


def test_valid_period_ordering_enforced():
    with pytest.raises(ValidationError, match="valid_from"):
        ValidPeriod(valid_from=datetime(2026, 1, 2, tzinfo=UTC),
                    valid_to=datetime(2026, 1, 1, tzinfo=UTC))
    assert ValidPeriod(valid_from=NOW).valid_to is None  # open-ended OK


def test_evidence_id_generated_and_stable_shape():
    e = _evidence()
    assert e.evidence_id.startswith("ev_") and len(e.evidence_id) == 3 + 26


def test_present_requires_content_or_hash():
    with pytest.raises(ValidationError, match="PRESENT"):
        _evidence(content=None, payload_hash=None)


def test_absent_requires_absence_reason_and_forbids_content():
    a = _evidence(
        availability=EvidenceAvailability.ABSENT,
        content=None,
        absence_reason=AbsenceReason.SOURCE_UNAVAILABLE,
    )
    assert a.absence_reason is AbsenceReason.SOURCE_UNAVAILABLE
    with pytest.raises(ValidationError, match="ABSENT"):
        _evidence(availability=EvidenceAvailability.ABSENT, content=None)


def test_error_requires_error_message():
    err = _evidence(availability=EvidenceAvailability.ERROR, content=None,
                    error="timeout fetching source")
    assert err.error == "timeout fetching source"
    with pytest.raises(ValidationError, match="ERROR"):
        _evidence(availability=EvidenceAvailability.ERROR, content=None)


def test_evidence_ref_relationships():
    r = EvidenceRef(evidence_id="ev_x", relationship=EvidenceRelationship.CONTRADICTS)
    assert r.relationship is EvidenceRelationship.CONTRADICTS
    assert {v.value for v in EvidenceRelationship} == {
        "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "CONTEXTUALIZES"
    }


def test_constructor_helpers_and_deterministic_ids():
    from kg_contracts.evidence import absent_evidence, present_evidence

    e = present_evidence(
        evidence_id="openalex:W123@2026-07",  # caller-supplied, citable
        source_type="api", source_locator="openalex/W123",
        observed_at=NOW, content="...", provenance=PROV,
    )
    assert e.evidence_id == "openalex:W123@2026-07"
    a = absent_evidence(source_type="api", source_locator="openalex/W999",
                        observed_at=NOW, reason=AbsenceReason.SOURCE_OMITTED,
                        provenance=PROV)
    assert a.availability is EvidenceAvailability.ABSENT
