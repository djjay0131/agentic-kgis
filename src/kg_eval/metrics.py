"""Extraction metrics with honest-null semantics baked into every value.

The unit of measurement here is `MetricValue`, not a bare `float`, and that is
the whole point of ADR-0009: a metric that could not be measured returns
`MetricValue.insufficient(reason)` — value `None` plus a human reason — never a
`0.0` that reads like a real, terrible score. The distinction is load-bearing:
"precision is 0.0" means the arm produced candidates and every one was wrong;
"precision is insufficient" means the arm produced nothing to measure. An
operator acts on those two facts completely differently.

The metric set (ADR-0009 §extraction metrics, scoped to what is measurable
against a `Candidate`/`Evidence` gold set):

- entity / relation / attribute precision, recall, F1 (with optional bootstrap
  confidence intervals);
- evidence-reference resolvability and evidence-span coverage;
- ontology-violation count (only when an `OntologySpec` is supplied — otherwise
  `None`, honestly);
- hallucination (false-positive) count and unsupported-assertion count;
- abstention and failure rates (denominator from the arm or the gold set;
  `None` when no denominator is known);
- cost/latency, passed through as-is and `None` when unmeasured.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    EntityCandidate,
    RelationCandidate,
)
from kg_contracts.evidence import Evidence, EvidenceAvailability, EvidenceRelationship
from kg_eval.arms import ArmOutput, CostLatency
from kg_eval.bootstrap import BootstrapConfig, ConfidenceInterval, bootstrap_ci
from kg_eval.goldset import EvidenceSpan, GoldSet
from kg_eval.matching import (
    CategoryMatch,
    match_attributes,
    match_entities,
    match_relations,
)


class MetricValue(BaseModel):
    """A single metric that is honest about not being measurable.

    Exactly one of two states: *measured* (`value` set, `sufficient=True`) or
    *insufficient* (`value=None`, `sufficient=False`, `note` explains why). A
    measured value may carry a bootstrap `ci`. Constructing it directly is
    allowed, but the `measured`/`insufficient` factories make the invariant
    obvious at call sites.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | None = None
    sufficient: bool = True
    ci: ConfidenceInterval | None = None
    note: str | None = None

    @staticmethod
    def measured(value: float, ci: ConfidenceInterval | None = None) -> MetricValue:
        return MetricValue(value=value, sufficient=True, ci=ci, note=None)

    @staticmethod
    def insufficient(note: str) -> MetricValue:
        """An unmeasurable metric — `None`, not `0.0`, with a reason (ADR-0009)."""
        return MetricValue(value=None, sufficient=False, ci=None, note=note)


class OntologySpec(BaseModel):
    """The allowed vocabulary, so ontology violations become measurable.

    Any category left empty is treated as "not constrained" and never
    contributes a violation, so a gold set can constrain only what it defines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_types: frozenset[str] = frozenset()
    relation_types: frozenset[str] = frozenset()
    attributes: frozenset[str] = frozenset()


class PRF(BaseModel):
    """Precision, recall, and F1 for one candidate category, plus raw counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    precision: MetricValue
    recall: MetricValue
    f1: MetricValue
    tp: int
    fp: int
    fn: int


class EvidenceValidity(BaseModel):
    """Do candidates' evidence citations resolve and cover their claimed spans?"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolvable_rate: MetricValue
    span_coverage_rate: MetricValue
    total_refs: int
    resolvable_refs: int
    spans_checked: int
    spans_covered: int


class ExtractionMetrics(BaseModel):
    """The full extraction scorecard for one arm against one gold set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: PRF
    relation: PRF
    attribute: PRF
    evidence: EvidenceValidity
    ontology_violations: int | None
    hallucination_count: int
    unsupported_assertion_count: int
    abstention_rate: MetricValue
    failure_rate: MetricValue
    cost: CostLatency | None


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _prf(match: CategoryMatch, category: str, boot: BootstrapConfig | None) -> PRF:
    """Precision/recall/F1 from a `CategoryMatch`, honest-null on empty sides.

    Precision is insufficient when the arm produced no candidates of this
    category (no denominator); recall is insufficient when the gold set has no
    items of this category. A real 0.0 — candidates produced but all wrong, or
    gold items none of which were found — is reported as a measured 0.0.
    """
    n_candidates = match.tp + match.fp
    n_gold = match.tp + match.fn

    if n_candidates == 0:
        precision = MetricValue.insufficient(f"no {category} candidates produced")
    else:
        p_ci = bootstrap_ci(match.candidate_hits, boot) if boot is not None else None
        precision = MetricValue.measured(match.tp / n_candidates, p_ci)

    if n_gold == 0:
        recall = MetricValue.insufficient(f"no {category} gold items")
    else:
        r_ci = bootstrap_ci(match.gold_hits, boot) if boot is not None else None
        recall = MetricValue.measured(match.tp / n_gold, r_ci)

    if precision.value is None or recall.value is None:
        f1 = MetricValue.insufficient(f"{category} F1 needs both precision and recall")
    else:
        f1 = MetricValue.measured(_f1(precision.value, recall.value))

    return PRF(precision=precision, recall=recall, f1=f1, tp=match.tp, fp=match.fp, fn=match.fn)


def _present_supporting(refs_evidence: Sequence[Evidence]) -> bool:
    return any(e.availability is EvidenceAvailability.PRESENT for e in refs_evidence)


def _covers_span(
    candidate: Candidate,
    span: EvidenceSpan,
    store: Mapping[str, Evidence],
) -> bool:
    """Does any of the candidate's cited evidence cover the expected span?

    Coverage = a cited `evidence_id` resolves in the store to PRESENT evidence
    at the same `source_locator`, and — when the span names a `quote` — that
    quote appears in the evidence content. A span with no quote is covered by
    locator match alone.
    """
    for ref in candidate.evidence_refs:
        evidence = store.get(ref.evidence_id)
        if evidence is None or evidence.availability is not EvidenceAvailability.PRESENT:
            continue
        if evidence.source_locator != span.source_locator:
            continue
        if span.quote is None:
            return True
        if evidence.content is not None and span.quote in evidence.content:
            return True
    return False


def _evidence_validity(output: ArmOutput, gold: GoldSet) -> EvidenceValidity:
    """Resolvability of every cited ref, and span coverage over matched items."""
    store = output.evidence

    total_refs = 0
    resolvable_refs = 0
    for candidate in output.candidates:
        for ref in candidate.evidence_refs:
            total_refs += 1
            if ref.evidence_id in store:
                resolvable_refs += 1

    if total_refs == 0:
        resolvable = MetricValue.insufficient("no evidence references to resolve")
    else:
        resolvable = MetricValue.measured(resolvable_refs / total_refs)

    spans_checked, spans_covered = _span_coverage_counts(output, gold)
    if spans_checked == 0:
        coverage = MetricValue.insufficient("no matched gold items carry an evidence span")
    else:
        coverage = MetricValue.measured(spans_covered / spans_checked)

    return EvidenceValidity(
        resolvable_rate=resolvable,
        span_coverage_rate=coverage,
        total_refs=total_refs,
        resolvable_refs=resolvable_refs,
        spans_checked=spans_checked,
        spans_covered=spans_covered,
    )


def _span_coverage_counts(output: ArmOutput, gold: GoldSet) -> tuple[int, int]:
    """Over each category, count matched gold items with a span and how many are covered."""
    store = output.evidence
    checked = 0
    covered = 0

    entity_cands = [c for c in output.candidates if isinstance(c, EntityCandidate)]
    ent_match = match_entities(output.candidates, gold)
    checked_e, covered_e = _category_span_counts(
        entity_cands, list(gold.entities), ent_match, store
    )
    checked += checked_e
    covered += covered_e

    relation_cands = [c for c in output.candidates if isinstance(c, RelationCandidate)]
    rel_match = match_relations(output.candidates, gold)
    checked_r, covered_r = _category_span_counts(
        relation_cands, list(gold.relations), rel_match, store
    )
    checked += checked_r
    covered += covered_r

    attr_cands = [c for c in output.candidates if isinstance(c, AttributeAssertionCandidate)]
    attr_match = match_attributes(output.candidates, gold)
    checked_a, covered_a = _category_span_counts(
        attr_cands, list(gold.attributes), attr_match, store
    )
    checked += checked_a
    covered += covered_a

    return checked, covered


def _category_span_counts(
    candidates: Sequence[Candidate],
    gold_items: Sequence[object],
    match: CategoryMatch,
    store: Mapping[str, Evidence],
) -> tuple[int, int]:
    """For one category, count (matched gold items with a span, of which covered).

    Iterates candidates in the same order the match keys were built, so
    `match.matched_gold_indices[j]` names the gold item candidate j hit.
    """
    checked = 0
    covered = 0
    for j, candidate in enumerate(candidates):
        gi = match.matched_gold_indices[j]
        if gi is None:
            continue
        span = getattr(gold_items[gi], "evidence", None)
        if span is None:
            continue
        checked += 1
        if _covers_span(candidate, span, store):
            covered += 1
    return checked, covered


def _ontology_violations(output: ArmOutput, ontology: OntologySpec | None) -> int | None:
    """Count candidates using a type/attribute outside the allowed vocabulary.

    `None` — not `0` — when no `OntologySpec` was supplied: without a
    vocabulary the violation count is unmeasurable, and honesty says so.
    """
    if ontology is None:
        return None
    violations = 0
    for candidate in output.candidates:
        if isinstance(candidate, EntityCandidate):
            if ontology.entity_types and candidate.entity_type not in ontology.entity_types:
                violations += 1
        elif isinstance(candidate, RelationCandidate):
            if ontology.relation_types and candidate.relation_type not in ontology.relation_types:
                violations += 1
        elif (
            isinstance(candidate, AttributeAssertionCandidate)
            and ontology.attributes
            and candidate.attribute not in ontology.attributes
        ):
            violations += 1
    return violations


def _unsupported_assertions(output: ArmOutput) -> int:
    """Candidates with no resolvable PRESENT+SUPPORTS evidence backing them."""
    store = output.evidence
    count = 0
    for candidate in output.candidates:
        supported = False
        for ref in candidate.evidence_refs:
            if ref.relationship is not EvidenceRelationship.SUPPORTS:
                continue
            evidence = store.get(ref.evidence_id)
            if evidence is not None and evidence.availability is EvidenceAvailability.PRESENT:
                supported = True
                break
        if not supported:
            count += 1
    return count


def _rate(numerator: int, denominator: int | None, note: str) -> MetricValue:
    if denominator is None or denominator == 0:
        return MetricValue.insufficient(note)
    return MetricValue.measured(numerator / denominator)


def evaluate_extraction(
    output: ArmOutput,
    gold: GoldSet,
    *,
    ontology: OntologySpec | None = None,
    boot: BootstrapConfig | None = None,
) -> ExtractionMetrics:
    """Grade one arm's output against a gold set into an `ExtractionMetrics`.

    `boot` enables bootstrap confidence intervals on precision/recall (omit for
    point estimates only). `ontology` enables the violation count. Every metric
    that cannot be measured comes back as `MetricValue.insufficient(...)` or,
    for the integer counts, `None` — never a fabricated zero.
    """
    ent_match = match_entities(output.candidates, gold)
    rel_match = match_relations(output.candidates, gold)
    attr_match = match_attributes(output.candidates, gold)

    # Hallucinations are the false positives across all categories. Note the
    # deliberate semantic (see `matching._match`): a *duplicate correct*
    # candidate — a second emission of a fact already matched — counts as a
    # false positive and therefore as a hallucination here, because
    # `fp = len(candidates) - tp` and only the first emission consumes the gold
    # item. This is intentional: an arm that pads output with repeats is
    # over-producing, and precision/hallucination should reflect that. It is
    # NOT a claim that the repeated fact is fabricated — redundant emission and
    # a fabricated fact are both penalized here, but they are different faults.
    hallucination = ent_match.fp + rel_match.fp + attr_match.fp

    attempted = output.attempted if output.attempted is not None else gold.attempted

    return ExtractionMetrics(
        entity=_prf(ent_match, "entity", boot),
        relation=_prf(rel_match, "relation", boot),
        attribute=_prf(attr_match, "attribute", boot),
        evidence=_evidence_validity(output, gold),
        ontology_violations=_ontology_violations(output, ontology),
        hallucination_count=hallucination,
        unsupported_assertion_count=_unsupported_assertions(output),
        abstention_rate=_rate(output.abstained, attempted, "no attempted-input count known"),
        failure_rate=_rate(output.failed, attempted, "no attempted-input count known"),
        cost=output.cost,
    )
