"""kgis-local reusable suite for any evidence registry (NOT a kg_contracts edit).

Imports `pytest`, which is a **dev-only** dependency (`[project.optional-dependencies]
.dev`). Nothing reachable from a runtime `__init__` chain may import this module
eagerly, or `import kgis` breaks for every consumer who installed without the `[dev]`
extra — that was issue #37. `kgis.evidence` therefore resolves
`EvidenceRegistryContract` lazily; see `kgis/evidence/__init__.py`.

`tests/test_packaging.py` enumerates this module in `DEV_ONLY_MODULES` and proves
nothing else in the three packages imports outside the runtime dependency closure.
"""

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

    def test_subjects_for_is_the_reverse_of_refs_for(self) -> None:
        # Issue #59: KGPS `impacted_by(evidence_id)` needs the evidence ->
        # subjects direction. Every subject that cites an id is returned, with
        # a relationship filter narrowing the result.
        reg = self.make_registry()
        reg.add_refs("s1", [
            EvidenceRef(evidence_id="e", relationship=EvidenceRelationship.SUPPORTS),
        ])
        reg.add_refs("s2", [
            EvidenceRef(evidence_id="e", relationship=EvidenceRelationship.CONTRADICTS),
        ])
        assert set(reg.subjects_for("e")) == {"s1", "s2"}
        assert reg.subjects_for("e", EvidenceRelationship.SUPPORTS) == ["s1"]
        assert reg.subjects_for("e", EvidenceRelationship.CONTRADICTS) == ["s2"]
        # An id nobody cites has no subjects — empty, not an error.
        assert reg.subjects_for("uncited") == []

    def test_subjects_for_deduplicates_a_subject_citing_under_two_relationships(self) -> None:
        # The ref primary key is (subject, evidence, relationship), so one
        # subject may cite one evidence item several times; the reverse lookup
        # must name the subject once.
        reg = self.make_registry()
        reg.add_refs("s1", [
            EvidenceRef(evidence_id="e", relationship=EvidenceRelationship.SUPPORTS),
            EvidenceRef(evidence_id="e", relationship=EvidenceRelationship.CONTEXTUALIZES),
        ])
        assert reg.subjects_for("e") == ["s1"]
