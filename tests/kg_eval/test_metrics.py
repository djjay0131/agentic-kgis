"""Extraction metrics: exact P/R/F1, evidence validity, and honest-null.

Every number here is checked against the hand-built arms in `helpers.py`, whose
outputs are known exactly, so a regression in the math is a test failure rather
than a plausible-looking wrong number.
"""

from pathlib import Path

import pytest
from helpers import (
    hallucinating_arm,
    lossy_arm,
    perfect_arm,
    relation_with_relationship,
)
from datetime import UTC, datetime

from pydantic import ValidationError

from kg_contracts.candidates import (
    CandidateScores,
    EntityCandidate,
    SourceCoordinates,
)
from kg_contracts.evidence import (
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    TextSpan,
    present_evidence,
)
from kg_contracts.identity import EntityRef
from kg_eval import (
    ArmConfig,
    ArmOutput,
    BootstrapConfig,
    EvidenceSpan,
    GoldEntity,
    GoldSet,
    MetricValue,
    OntologySpec,
    evaluate_extraction,
)

FIXTURE = Path(__file__).parent / "fixtures" / "baseball_gold.json"


def gold() -> GoldSet:
    return GoldSet.from_json_file(FIXTURE)


class TestPerfectArm:
    def test_all_categories_are_one(self) -> None:
        m = evaluate_extraction(perfect_arm(), gold())
        for prf in (m.entity, m.relation, m.attribute):
            assert prf.precision.value == 1.0
            assert prf.recall.value == 1.0
            assert prf.f1.value == 1.0

    def test_no_hallucinations_or_unsupported(self) -> None:
        m = evaluate_extraction(perfect_arm(), gold())
        assert m.hallucination_count == 0
        assert m.unsupported_assertion_count == 0

    def test_evidence_resolves_and_covers_spans(self) -> None:
        m = evaluate_extraction(perfect_arm(), gold())
        assert m.evidence.resolvable_rate.value == 1.0
        assert m.evidence.span_coverage_rate.value == 1.0
        assert m.evidence.spans_checked == 10


class TestLossyArm:
    def test_recall_below_one_precision_one(self) -> None:
        m = evaluate_extraction(lossy_arm(), gold())
        assert m.entity.recall.value == 0.6  # 6 of 10
        assert m.entity.precision.value == 1.0  # no false positives
        assert m.entity.tp == 6
        assert m.entity.fn == 4
        assert m.entity.fp == 0

    def test_abstention_and_failure_rates(self) -> None:
        m = evaluate_extraction(lossy_arm(), gold())
        assert m.abstention_rate.value == 0.2  # 2 / 10 attempted
        assert m.failure_rate.value == 0.1  # 1 / 10 attempted


class TestHallucinatingArm:
    def test_false_positives_count_as_hallucinations(self) -> None:
        m = evaluate_extraction(hallucinating_arm(), gold())
        assert m.entity.recall.value == 1.0
        assert m.entity.fp == 3
        assert m.hallucination_count == 3

    def test_evidence_free_candidates_are_unsupported(self) -> None:
        m = evaluate_extraction(hallucinating_arm(), gold())
        assert m.unsupported_assertion_count == 3

    def test_precision_is_a_real_number_not_null(self) -> None:
        m = evaluate_extraction(hallucinating_arm(), gold())
        # 10 true of 13 produced — a measured value, not honest-null
        assert m.entity.precision.sufficient is True
        assert abs(m.entity.precision.value - 10 / 13) < 1e-9


class TestEvidenceRelationshipSemantics:
    """Grounding and verification are different claims (issue #60)."""

    def test_derived_from_grounds_but_does_not_verify(self) -> None:
        m = evaluate_extraction(
            relation_with_relationship(EvidenceRelationship.DERIVED_FROM), gold()
        )
        assert m.unsupported_assertion_count == 0
        assert m.unverified_assertion_count == 1

    def test_supports_grounds_and_verifies(self) -> None:
        m = evaluate_extraction(
            relation_with_relationship(EvidenceRelationship.SUPPORTS), gold()
        )
        assert m.unsupported_assertion_count == 0
        assert m.unverified_assertion_count == 0

    def test_contradicts_grounds_nothing(self) -> None:
        m = evaluate_extraction(
            relation_with_relationship(EvidenceRelationship.CONTRADICTS), gold()
        )
        assert m.unsupported_assertion_count == 1
        assert m.unverified_assertion_count == 1

    def test_contextualizes_grounds_nothing(self) -> None:
        # Context evidence situates a claim; it is not evidence for it, so it
        # must not count as grounding (nor as verification).
        m = evaluate_extraction(
            relation_with_relationship(EvidenceRelationship.CONTEXTUALIZES), gold()
        )
        assert m.unsupported_assertion_count == 1
        assert m.unverified_assertion_count == 1


class TestHonestNull:
    def test_no_candidates_gives_insufficient_precision_not_zero(self) -> None:
        # lossy arm produces no relations at all in the relation category? it does;
        # use an arm slice with zero of a category: attributes-only-less case.
        m = evaluate_extraction(lossy_arm(), gold())
        # lossy has 2 relations, so relation precision is measured; assert the
        # honest-null path directly with an empty-category arm:
        empty = lossy_arm().model_copy(update={"candidates": ()})
        me = evaluate_extraction(empty, gold())
        assert me.entity.precision.value is None
        assert me.entity.precision.sufficient is False
        assert "no entity candidates" in (me.entity.precision.note or "")
        # recall is still measured 0.0 — gold exists, nothing found (a real zero)
        assert me.entity.recall.value == 0.0
        assert me.entity.recall.sufficient is True
        # keep the measured lossy relation reference used to avoid dead binding
        assert m.relation.precision.sufficient is True

    def test_unmeasured_abstention_is_null_not_zero(self) -> None:
        arm = lossy_arm().model_copy(update={"attempted": None})
        no_attempt_gold = gold().model_copy(update={"attempted": None})
        m = evaluate_extraction(arm, no_attempt_gold)
        assert m.abstention_rate.value is None
        assert m.abstention_rate.sufficient is False

    def test_ontology_violations_null_without_spec(self) -> None:
        m = evaluate_extraction(perfect_arm(), gold())
        assert m.ontology_violations is None  # honest null, not 0

    def test_ontology_violations_measured_with_spec(self) -> None:
        spec = OntologySpec(entity_types=frozenset({"Player"}), relation_types=frozenset({"PLAYS_FOR"}))
        m = evaluate_extraction(perfect_arm(), gold(), ontology=spec)
        assert m.ontology_violations == 0
        # a spec that forbids Player flags every entity
        strict = OntologySpec(entity_types=frozenset({"Coach"}))
        m2 = evaluate_extraction(perfect_arm(), gold(), ontology=strict)
        assert m2.ontology_violations == 10


class TestBootstrapAttached:
    def test_recall_carries_ci_when_boot_supplied(self) -> None:
        boot = BootstrapConfig(seed=42, n_resamples=200, min_items=8)
        m = evaluate_extraction(lossy_arm(), gold(), boot=boot)
        ci = m.entity.recall.ci
        assert ci is not None
        assert ci.lower <= m.entity.recall.value <= ci.upper

    def test_metric_value_factories(self) -> None:
        assert MetricValue.measured(0.5).value == 0.5
        assert MetricValue.insufficient("why").value is None


class TestArmOutputBounds:
    def test_abstained_plus_failed_over_attempted_raises(self) -> None:
        # 7 + 4 > 10 -> a rate could exceed 1.0, so construction is rejected
        with pytest.raises(ValidationError, match="exceeds attempted"):
            ArmOutput(arm=ArmConfig(arm_id="x"), attempted=10, abstained=7, failed=4)

    def test_at_the_boundary_is_allowed(self) -> None:
        out = ArmOutput(arm=ArmConfig(arm_id="x"), attempted=10, abstained=6, failed=4)
        assert out.abstained + out.failed == out.attempted

    def test_no_attempted_count_skips_the_bound(self) -> None:
        # honest-null path: no denominator, so counts pass through unbounded
        out = ArmOutput(arm=ArmConfig(arm_id="x"), attempted=None, abstained=9, failed=9)
        assert out.attempted is None
        m = evaluate_extraction(out, gold().model_copy(update={"attempted": None}))
        assert m.abstention_rate.value is None


class TestSpanOverlap:
    """The typed span-overlap metric: `Evidence.span` vs gold `EvidenceSpan` offsets."""

    LOCATOR = "doc#chunk:0@chars:0-20"
    _NOW = datetime(2026, 7, 12, tzinfo=UTC)

    def _arm(
        self, *, ev_start: int, ev_end: int, locator: str | None = None
    ) -> ArmOutput:
        locator = locator or self.LOCATOR
        eid = "ev-span"
        evidence = present_evidence(
            evidence_id=eid,
            source_type="document",
            source_locator=locator,
            observed_at=self._NOW,
            provenance=Provenance(source="doc", actor="extractor"),
            content="Ada is a shortstop",
            span=TextSpan(start=ev_start, end=ev_end, quote="Ada is"),
        )
        candidate = EntityCandidate(
            graph_id="g",
            producer="p",
            producer_run_id="r",
            ontology_version="1",
            source_coordinates=SourceCoordinates(source_type="document", locator=locator),
            semantic_key="player/p1",
            scores=CandidateScores(extraction_confidence=0.9, source_reliability=0.9),
            entity_type="Player",
            aliases=(EntityRef(entity_type="Player", namespace="usssa", key="p1"),),
            evidence_refs=(
                EvidenceRef(
                    evidence_id=eid, relationship=EvidenceRelationship.DERIVED_FROM
                ),
            ),
        )
        return ArmOutput(
            arm=ArmConfig(arm_id="span-arm"),
            candidates=(candidate,),
            evidence={eid: evidence},
        )

    def _gold(self, *, start: int | None = None, end: int | None = None) -> GoldSet:
        return GoldSet(
            gold_set_id="spans",
            entities=(
                GoldEntity(
                    entity_type="Player",
                    semantic_key="player/p1",
                    evidence=EvidenceSpan(
                        source_locator=self.LOCATOR,
                        quote="Ada is",
                        start=start,
                        end=end,
                    ),
                ),
            ),
        )

    def test_overlapping_span_scores_one(self) -> None:
        m = evaluate_extraction(self._arm(ev_start=5, ev_end=11), self._gold(start=0, end=10))
        assert m.evidence.span_overlap_rate.value == 1.0
        assert m.evidence.spans_with_offsets == 1
        assert m.evidence.spans_overlapping == 1

    def test_disjoint_spans_score_zero(self) -> None:
        m = evaluate_extraction(self._arm(ev_start=20, ev_end=30), self._gold(start=0, end=10))
        assert m.evidence.span_overlap_rate.value == 0.0
        assert m.evidence.spans_overlapping == 0

    def test_touching_spans_do_not_overlap(self) -> None:
        # Half-open: [10, 20) does not overlap [0, 10); the boundary is exclusive.
        m = evaluate_extraction(self._arm(ev_start=10, ev_end=20), self._gold(start=0, end=10))
        assert m.evidence.span_overlap_rate.value == 0.0

    def test_locator_mismatch_does_not_overlap(self) -> None:
        m = evaluate_extraction(
            self._arm(ev_start=5, ev_end=10, locator="other#x"),
            self._gold(start=0, end=10),
        )
        assert m.evidence.span_overlap_rate.value == 0.0

    def test_gold_without_offsets_is_honest_null(self) -> None:
        m = evaluate_extraction(self._arm(ev_start=5, ev_end=10), self._gold())
        assert m.evidence.span_overlap_rate.value is None
        assert m.evidence.span_overlap_rate.sufficient is False
        assert "offsets" in (m.evidence.span_overlap_rate.note or "")
        assert m.evidence.spans_with_offsets == 0

    def test_shipped_fixture_has_no_offsets_so_metric_is_null(self) -> None:
        # The baseball fixture names quotes but no character offsets.
        m = evaluate_extraction(perfect_arm(), gold())
        assert m.evidence.span_overlap_rate.value is None
