"""Extraction metrics: exact P/R/F1, evidence validity, and honest-null.

Every number here is checked against the hand-built arms in `helpers.py`, whose
outputs are known exactly, so a regression in the math is a test failure rather
than a plausible-looking wrong number.
"""

from pathlib import Path

from helpers import hallucinating_arm, lossy_arm, perfect_arm

from kg_eval import (
    BootstrapConfig,
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
