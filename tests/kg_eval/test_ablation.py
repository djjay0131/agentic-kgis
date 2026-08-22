"""Ablation enforces honest-null: wins need a CI above zero and clean guardrails."""

from pathlib import Path

from helpers import lossy_arm, perfect_arm, subset_arm

from kg_eval import AblationVerdict, BootstrapConfig, GoldSet, compare_arms

FIXTURE = Path(__file__).parent / "fixtures" / "baseball_gold.json"
BOOT = BootstrapConfig(seed=7, n_resamples=500, min_items=8)


def gold() -> GoldSet:
    return GoldSet.from_json_file(FIXTURE)


def test_clean_recall_gain_is_improvement() -> None:
    base = subset_arm("rules", 4)  # recall 0.4, no cost
    enh = subset_arm("rules+llm", 9)  # recall 0.9, no cost
    r = compare_arms(base, enh, gold(), metric="entity.recall", boot=BOOT)
    assert r.verdict is AblationVerdict.IMPROVEMENT
    assert r.diff_ci is not None and r.diff_ci.excludes_zero_above
    assert r.guardrail_concerns == ()


def test_recall_gain_bought_by_cost_regression_is_not_a_win() -> None:
    # perfect arm has better recall than lossy but higher cost + latency
    r = compare_arms(lossy_arm(), perfect_arm(), gold(), metric="entity.recall", boot=BOOT)
    assert r.verdict is AblationVerdict.NO_IMPROVEMENT
    assert r.guardrail_concerns  # cost/latency rose


def test_worse_arm_is_regression() -> None:
    r = compare_arms(perfect_arm(), lossy_arm(), gold(), metric="entity.recall", boot=BOOT)
    assert r.verdict is AblationVerdict.REGRESSION
    assert r.diff_ci is not None and r.diff_ci.excludes_zero_below


def test_tie_is_no_improvement_not_a_win() -> None:
    r = compare_arms(perfect_arm(), perfect_arm(), gold(), metric="entity.recall", boot=BOOT)
    assert r.verdict is AblationVerdict.NO_IMPROVEMENT
    assert r.diff_ci is not None
    assert r.diff_ci.lower == 0.0 and r.diff_ci.upper == 0.0


def test_precision_has_no_paired_test_so_insufficient() -> None:
    base = subset_arm("rules", 4)
    enh = subset_arm("rules+llm", 9)
    r = compare_arms(base, enh, gold(), metric="entity.precision", boot=BOOT)
    assert r.verdict is AblationVerdict.INSUFFICIENT_EVIDENCE


def test_too_few_items_is_insufficient_not_a_win() -> None:
    base = subset_arm("rules", 4)
    enh = subset_arm("rules+llm", 9)
    strict = BootstrapConfig(seed=7, n_resamples=100, min_items=50)
    r = compare_arms(base, enh, gold(), metric="entity.recall", boot=strict)
    assert r.verdict is AblationVerdict.INSUFFICIENT_EVIDENCE
    assert r.diff_ci is None
