"""kgis-local reusable suite for any evidence registry (NOT a kg_contracts edit)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    AbsenceReason,
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    absent_evidence,
    present_evidence,
)

from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

_NOW = datetime(2026, 7, 21, tzinfo=UTC)
_PROV = Provenance(source="suite", actor="suite")


class EvidenceRegistryContract:
    """Subclass and implement `make_registry()`."""

    def make_registry(self) -> SqliteEvidenceRegistry:
        raise NotImplementedError

    def test_present_and_absent_both_persist(self) -> None:
        reg = self.make_registry()
        reg.put(present_evidence(evidence_id="p", source_type="a", source_locator="k",
                                 observed_at=_NOW, content="x", provenance=_PROV))
        reg.put(absent_evidence(evidence_id="a", source_type="a", source_locator="k",
                                observed_at=_NOW, reason=AbsenceReason.NOT_QUERIED,
                                provenance=_PROV))
        got_p = reg.get("p")
        got_a = reg.get("a")
        assert got_p is not None and got_p.availability is EvidenceAvailability.PRESENT
        assert got_a is not None and got_a.availability is EvidenceAvailability.ABSENT

    def test_missing_get_returns_none(self) -> None:
        assert self.make_registry().get("nope") is None

    def test_ref_resolution_and_dangling(self) -> None:
        reg = self.make_registry()
        reg.put(present_evidence(evidence_id="e", source_type="a", source_locator="k",
                                 observed_at=_NOW, content="x", provenance=_PROV))
        reg.add_refs("s", [EvidenceRef(evidence_id="e",
                                       relationship=EvidenceRelationship.DERIVED_FROM)])
        assert [x.evidence_id for x in reg.resolve("s")] == ["e"]
        reg.add_refs("s", [EvidenceRef(evidence_id="gone",
                                       relationship=EvidenceRelationship.SUPPORTS)])
        with pytest.raises(EvidenceNotFoundError):
            reg.resolve("s")
