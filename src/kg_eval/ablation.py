"""Ablation comparison between a baseline and an enhanced arm.

This is where the honest-null policy (ADR-0009) is *enforced*, not just
documented. The rule: an enhanced arm (typically the LLM-assisted one) earns
the label IMPROVEMENT only when three things hold at once —

1. its point estimate on the named metric beats the baseline;
2. the paired bootstrap confidence interval of the per-item difference
   excludes 0 from below (the improvement is not a coin flip); and
3. no guardrail regresses — it did not buy recall by hallucinating more,
   leaving more assertions unsupported, or (when measured) costing more.

If the interval straddles 0, the verdict is NO_IMPROVEMENT: "the LLM did not
help" is a real, publishable result, not a bug. If the metric or the interval
cannot be computed at all — too few gold items, or a metric with no paired
per-item signal such as precision/F1 — the verdict is INSUFFICIENT_EVIDENCE. A
false win is never manufactured to fill the gap.

Only recall-style metrics carry a paired per-item signal (both arms are graded
against the *same* gold items), so only they can be tested with a paired
interval; precision and F1 can be compared as point estimates but a win on them
is deliberately downgraded to INSUFFICIENT_EVIDENCE for lack of a valid paired
test.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from kg_eval.arms import ArmOutput
from kg_eval.bootstrap import BootstrapConfig, ConfidenceInterval, bootstrap_diff_ci
from kg_eval.goldset import GoldSet
from kg_eval.matching import CategoryMatch, match_attributes, match_entities, match_relations
from kg_eval.metrics import (
    PRF,
    ExtractionMetrics,
    MetricValue,
    OntologySpec,
    evaluate_extraction,
)


class AblationVerdict(StrEnum):
    """The four honest outcomes of comparing two arms."""

    IMPROVEMENT = "IMPROVEMENT"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    REGRESSION = "REGRESSION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


_RECALL_METRICS = {"entity.recall", "relation.recall", "attribute.recall"}


def _category_match(output: ArmOutput, gold: GoldSet, category: str) -> CategoryMatch:
    if category == "entity":
        return match_entities(output.candidates, gold)
    if category == "relation":
        return match_relations(output.candidates, gold)
    return match_attributes(output.candidates, gold)


def _select_metric(metrics: ExtractionMetrics, metric: str) -> MetricValue:
    category, _, field = metric.partition(".")
    prf: PRF = getattr(metrics, category)
    value: MetricValue = getattr(prf, field)
    return value


class AblationResult(BaseModel):
    """One baseline-vs-enhanced comparison on a single named metric.

    `verdict` is the honest-null judgment; `rationale` says why in one line;
    `guardrail_concerns` lists any metric that regressed and negated a win.
    `diff_ci` is the paired bootstrap interval when one could be computed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    baseline_arm: str
    enhanced_arm: str
    baseline: MetricValue
    enhanced: MetricValue
    diff_ci: ConfidenceInterval | None
    verdict: AblationVerdict
    rationale: str
    guardrail_concerns: tuple[str, ...] = Field(default_factory=tuple)


def _guardrail_concerns(baseline: ExtractionMetrics, enhanced: ExtractionMetrics) -> list[str]:
    """List guardrails the enhanced arm worsened (ADR-0009 honest-null clause).

    An improvement bought by more hallucinations, more unsupported assertions,
    or (when both measured) more cost/latency is not a default-worthy win.

    Known limitation: the cost and latency guardrails only fire when *both*
    arms report the value. An enhanced arm that stops measuring cost/latency
    (`cost=None`, or a `CostLatency` field left `None`) therefore escapes the
    cost/latency check entirely — the comparison is skipped rather than treated
    as a regression. Hallucination and unsupported-assertion guardrails have no
    such gap; they are always measurable from the candidates. A future revision
    could treat "stopped measuring a previously-measured cost" as a concern in
    its own right; today it does not.
    """
    concerns: list[str] = []
    if enhanced.hallucination_count > baseline.hallucination_count:
        concerns.append(
            f"hallucinations rose {baseline.hallucination_count}->{enhanced.hallucination_count}"
        )
    if enhanced.unsupported_assertion_count > baseline.unsupported_assertion_count:
        concerns.append(
            "unsupported assertions rose "
            f"{baseline.unsupported_assertion_count}->{enhanced.unsupported_assertion_count}"
        )
    b_cost, e_cost = baseline.cost, enhanced.cost
    if b_cost is not None and e_cost is not None:
        if (
            b_cost.cost_usd is not None
            and e_cost.cost_usd is not None
            and e_cost.cost_usd > b_cost.cost_usd
        ):
            concerns.append(f"cost rose {b_cost.cost_usd}->{e_cost.cost_usd} usd")
        if (
            b_cost.latency_seconds is not None
            and e_cost.latency_seconds is not None
            and e_cost.latency_seconds > b_cost.latency_seconds
        ):
            concerns.append(
                f"latency rose {b_cost.latency_seconds}->{e_cost.latency_seconds}s"
            )
    return concerns


def compare_arms(
    baseline: ArmOutput,
    enhanced: ArmOutput,
    gold: GoldSet,
    *,
    metric: str,
    boot: BootstrapConfig,
    ontology: OntologySpec | None = None,
) -> AblationResult:
    """Compare two arms on `metric` under the honest-null policy.

    `metric` is `"<category>.<field>"`, e.g. `"entity.recall"`. Recall metrics
    get a paired bootstrap interval and can yield IMPROVEMENT/REGRESSION;
    precision/F1 have no valid paired test and a nominal win on them is
    reported as INSUFFICIENT_EVIDENCE. Guardrail regressions downgrade an
    otherwise-improving verdict to NO_IMPROVEMENT.
    """
    base_metrics = evaluate_extraction(baseline, gold, ontology=ontology, boot=boot)
    enh_metrics = evaluate_extraction(enhanced, gold, ontology=ontology, boot=boot)

    base_value = _select_metric(base_metrics, metric)
    enh_value = _select_metric(enh_metrics, metric)
    concerns = tuple(_guardrail_concerns(base_metrics, enh_metrics))

    def result(
        verdict: AblationVerdict, rationale: str, diff_ci: ConfidenceInterval | None
    ) -> AblationResult:
        return AblationResult(
            metric=metric,
            baseline_arm=baseline.arm.arm_id,
            enhanced_arm=enhanced.arm.arm_id,
            baseline=base_value,
            enhanced=enh_value,
            diff_ci=diff_ci,
            verdict=verdict,
            rationale=rationale,
            guardrail_concerns=concerns,
        )

    if base_value.value is None or enh_value.value is None:
        return result(
            AblationVerdict.INSUFFICIENT_EVIDENCE,
            f"{metric} is not measurable on both arms",
            None,
        )

    if metric not in _RECALL_METRICS:
        return result(
            AblationVerdict.INSUFFICIENT_EVIDENCE,
            f"{metric} has no paired per-item signal for a bootstrap test; "
            "point estimates are not a valid win",
            None,
        )

    category = metric.split(".")[0]
    base_hits = _category_match(baseline, gold, category).gold_hits
    enh_hits = _category_match(enhanced, gold, category).gold_hits
    diff_ci = bootstrap_diff_ci(base_hits, enh_hits, boot)

    if diff_ci is None:
        return result(
            AblationVerdict.INSUFFICIENT_EVIDENCE,
            f"too few gold items (< {boot.min_items}) for a bootstrap interval",
            None,
        )

    if diff_ci.excludes_zero_below:
        return result(
            AblationVerdict.REGRESSION,
            f"enhanced arm is worse: diff CI [{diff_ci.lower:.3f}, {diff_ci.upper:.3f}] < 0",
            diff_ci,
        )

    if diff_ci.excludes_zero_above:
        if concerns:
            return result(
                AblationVerdict.NO_IMPROVEMENT,
                "metric improved but a guardrail regressed; not a default-worthy win",
                diff_ci,
            )
        return result(
            AblationVerdict.IMPROVEMENT,
            f"enhanced arm improves: diff CI [{diff_ci.lower:.3f}, {diff_ci.upper:.3f}] > 0",
            diff_ci,
        )

    return result(
        AblationVerdict.NO_IMPROVEMENT,
        f"diff CI [{diff_ci.lower:.3f}, {diff_ci.upper:.3f}] straddles 0; the LLM did not help",
        diff_ci,
    )
