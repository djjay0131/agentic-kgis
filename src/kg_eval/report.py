"""One result model, two renderings: JSON and Markdown.

A report must be reproducible and machine-checkable, so `EvaluationResult` is a
frozen pydantic model and both renderers are pure functions of it: the same
result always produces byte-identical JSON and byte-identical Markdown. JSON is
the archival/diffable form; Markdown is the human-readable form; neither is
computed independently, so they can never disagree.

Every rendering path preserves honest-null: a `MetricValue` with no value is
shown as "insufficient (reason)", never as 0.000, in both formats. Confidence
intervals, when present, are rendered inline so a reader sees the uncertainty
next to the point estimate rather than having to trust a bare number.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from kg_eval.ablation import AblationResult
from kg_eval.arms import ArmConfig, ArmOutput, CostLatency
from kg_eval.bootstrap import BootstrapConfig
from kg_eval.goldset import GoldSet
from kg_eval.metrics import (
    PRF,
    EvidenceValidity,
    ExtractionMetrics,
    MetricValue,
    OntologySpec,
    evaluate_extraction,
)


class ArmResult(BaseModel):
    """One arm's identity plus its extraction scorecard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: ArmConfig
    metrics: ExtractionMetrics


class EvaluationResult(BaseModel):
    """The full, reproducible result of one evaluation run.

    `gold_set_hash` pins the ground truth the arms were graded against, so a
    stored report proves which truth produced these numbers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold_set_id: str
    gold_set_hash: str
    arms: tuple[ArmResult, ...] = ()
    ablations: tuple[AblationResult, ...] = ()


def evaluate_arms(
    outputs: tuple[ArmOutput, ...],
    gold: GoldSet,
    *,
    ontology: OntologySpec | None = None,
    boot: BootstrapConfig | None = None,
    ablations: tuple[AblationResult, ...] = (),
) -> EvaluationResult:
    """Grade every arm against the gold set into one `EvaluationResult`.

    Arms are graded in the order given (deterministic). `ablations` are
    computed by the caller via `compare_arms` and passed through, so a report
    can carry exactly the comparisons the caller cares about.
    """
    arm_results = tuple(
        ArmResult(
            arm=output.arm,
            metrics=evaluate_extraction(output, gold, ontology=ontology, boot=boot),
        )
        for output in outputs
    )
    return EvaluationResult(
        gold_set_id=gold.gold_set_id,
        gold_set_hash=gold.content_hash,
        arms=arm_results,
        ablations=ablations,
    )


def render_json(result: EvaluationResult) -> str:
    """Deterministic pretty JSON of the whole result, with sorted keys.

    `sort_keys=True` makes an archived report robustly diffable: two runs that
    produce equal results produce byte-identical JSON regardless of model field
    ordering, matching the stability guarantee `GoldSet.content_hash` already
    relies on.
    """
    return json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)


def _fmt_metric(metric: MetricValue) -> str:
    """Render a `MetricValue` — never a fabricated 0.000 for an unmeasured one."""
    if metric.value is None:
        return f"insufficient ({metric.note})"
    text = f"{metric.value:.3f}"
    if metric.ci is not None:
        text += f" [{metric.ci.lower:.3f}, {metric.ci.upper:.3f}]"
    return text


def _fmt_int(value: int | None) -> str:
    return "insufficient (not measured)" if value is None else str(value)


def _fmt_cost(cost: CostLatency | None) -> str:
    if cost is None:
        return "not measured"
    parts: list[str] = []
    parts.append("latency=" + ("n/a" if cost.latency_seconds is None else f"{cost.latency_seconds}s"))
    parts.append("cost=" + ("n/a" if cost.cost_usd is None else f"${cost.cost_usd}"))
    parts.append("tokens=" + ("n/a" if cost.tokens is None else str(cost.tokens)))
    return ", ".join(parts)


def _prf_rows(name: str, prf: PRF) -> list[str]:
    return [
        (
            f"| {name} | {_fmt_metric(prf.precision)} | {_fmt_metric(prf.recall)} "
            f"| {_fmt_metric(prf.f1)} | {prf.tp} | {prf.fp} | {prf.fn} |"
        )
    ]


def _evidence_lines(ev: EvidenceValidity) -> list[str]:
    return [
        (
            f"- Evidence resolvable rate: {_fmt_metric(ev.resolvable_rate)} "
            f"({ev.resolvable_refs}/{ev.total_refs} refs)"
        ),
        (
            f"- Evidence span coverage: {_fmt_metric(ev.span_coverage_rate)} "
            f"({ev.spans_covered}/{ev.spans_checked} spans)"
        ),
    ]


def _arm_section(arm_result: ArmResult) -> list[str]:
    m = arm_result.metrics
    lines: list[str] = [
        f"### Arm: {arm_result.arm.arm_id}",
        "",
    ]
    if arm_result.arm.description:
        lines += [f"_{arm_result.arm.description}_", ""]
    lines += [f"Config hash: `{arm_result.arm.config_hash}`", ""]
    lines += [
        "| Category | Precision | Recall | F1 | TP | FP | FN |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += _prf_rows("Entity", m.entity)
    lines += _prf_rows("Relation", m.relation)
    lines += _prf_rows("Attribute", m.attribute)
    lines += [""]
    lines += _evidence_lines(m.evidence)
    lines += [
        f"- Ontology violations: {_fmt_int(m.ontology_violations)}",
        f"- Hallucinations (false positives): {m.hallucination_count}",
        f"- Unsupported assertions: {m.unsupported_assertion_count}",
        f"- Abstention rate: {_fmt_metric(m.abstention_rate)}",
        f"- Failure rate: {_fmt_metric(m.failure_rate)}",
        f"- Cost/latency: {_fmt_cost(m.cost)}",
        "",
    ]
    return lines


def _ablation_section(ablations: tuple[AblationResult, ...]) -> list[str]:
    if not ablations:
        return []
    lines = ["## Ablations", ""]
    for ab in ablations:
        lines += [
            f"### {ab.enhanced_arm} vs {ab.baseline_arm} on `{ab.metric}`",
            "",
            f"- Verdict: **{ab.verdict.value}**",
            f"- Baseline: {_fmt_metric(ab.baseline)}",
            f"- Enhanced: {_fmt_metric(ab.enhanced)}",
        ]
        if ab.diff_ci is not None:
            lines.append(
                f"- Difference CI: {ab.diff_ci.point:.3f} "
                f"[{ab.diff_ci.lower:.3f}, {ab.diff_ci.upper:.3f}] "
                f"(level {ab.diff_ci.level}, n={ab.diff_ci.n_items})"
            )
        else:
            lines.append("- Difference CI: insufficient evidence")
        if ab.guardrail_concerns:
            lines.append("- Guardrail concerns: " + "; ".join(ab.guardrail_concerns))
        lines += [f"- Rationale: {ab.rationale}", ""]
    return lines


def render_markdown(result: EvaluationResult) -> str:
    """Deterministic Markdown report from the same result model as `render_json`."""
    lines: list[str] = [
        f"# kg_eval report: {result.gold_set_id}",
        "",
        f"Gold-set hash: `{result.gold_set_hash}`",
        "",
        "## Arms",
        "",
    ]
    for arm_result in result.arms:
        lines += _arm_section(arm_result)
    lines += _ablation_section(result.ablations)
    return "\n".join(lines).rstrip() + "\n"
