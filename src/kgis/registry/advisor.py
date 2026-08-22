"""The extend-vs-new advisor (spec §8, ADR-0005 amended, Plan 7).

Deterministic and side-effect-free: `recommend()` is a pure function of a
registry snapshot, an `IncomingDataProfile`, and an `AdvisorConfig`. No
`random`, no clock, no I/O — the same three inputs always yield the same
`AdvisorRecommendation`, which is exactly what lets the recorded decision
corpus recalibrate the thresholds later.

The advisor **advises**; it never acts. Every recommendation in v1 routes to
a human (ADR-0005), and this module has no path that creates or extends a
graph. It scores the five automated factors (1, 2, 5, 6, 11), surfaces the
other seven as a checklist, and — when it cannot even score the automated
subset — returns `Outcome.INSUFFICIENT_INFORMATION` rather than a fabricated
number.
"""

from __future__ import annotations

from collections.abc import Sequence

from kgis.registry.models import (
    ATTR_CONTAINS_MINORS,
    ATTR_IDENTITY_AUTHORITY,
    ATTR_IS_COMPUTED_OUTPUT,
    ATTR_LIFECYCLE_CLASS,
    ATTR_RETENTION_CLASS,
    ATTR_TENANCY_CLASS,
    AUTOMATED_FACTORS,
    HUMAN_FACTORS,
    AdvisorConfig,
    AdvisorRecommendation,
    ChecklistItem,
    IncomingDataProfile,
    Outcome,
    RegisteredGraph,
    ScoredGraph,
)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float | None:
    """Overlap of two sets, or ``None`` when both are empty (no signal)."""
    if not left and not right:
        return None
    union = left | right
    if not union:
        return None
    return len(left & right) / len(union)


def _bool_attr(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


def _class_match(a: str | None, b: str | None) -> float | None:
    """1.0 if two class labels agree, 0.0 if they conflict, ``None`` if either
    is unknown (missing information, not a mismatch)."""
    if a is None or b is None:
        return None
    return 1.0 if a == b else 0.0


class GraphAdvisor:
    """Scores incoming data against a registry snapshot (spec §8)."""

    def __init__(self, config: AdvisorConfig | None = None) -> None:
        self._config = config or AdvisorConfig()

    # --- per-factor scorers (each returns None when it cannot be scored) ------

    def _score_identity(
        self, profile: IncomingDataProfile, graph: RegisteredGraph
    ) -> float | None:
        # Identity keys are not a `GraphDescriptor` field, so the only shared
        # identity signal the snapshot carries is the identity authority
        # (an extension attribute). Agreement on authority is the score;
        # unknown on either side is missing information, not a mismatch.
        graph_authority = graph.attributes.get(ATTR_IDENTITY_AUTHORITY)
        return _class_match(profile.identity_authority, graph_authority)

    def _score_ontology(
        self, profile: IncomingDataProfile, graph: RegisteredGraph
    ) -> float | None:
        incoming = profile.node_types | profile.edge_types | profile.attribute_types
        existing = (
            frozenset(graph.descriptor.node_types)
            | frozenset(graph.descriptor.edge_types)
            | graph.attribute_types()
        )
        return _jaccard(incoming, existing)

    def _score_tenancy(
        self, profile: IncomingDataProfile, graph: RegisteredGraph
    ) -> float | None:
        graph_minors = _bool_attr(graph.attributes.get(ATTR_CONTAINS_MINORS))
        # Minors' data flowing into a graph not marked for it is a hard push
        # apart (spec §8: inference leakage, purpose limitation).
        if profile.contains_minors_data is True and graph_minors is not True:
            return 0.0
        return _class_match(profile.tenancy_class, graph.attributes.get(ATTR_TENANCY_CLASS))

    def _score_lifecycle(
        self, profile: IncomingDataProfile, graph: RegisteredGraph
    ) -> float | None:
        life = _class_match(profile.lifecycle_class, graph.attributes.get(ATTR_LIFECYCLE_CLASS))
        retention = _class_match(
            profile.retention_class, graph.attributes.get(ATTR_RETENTION_CLASS)
        )
        scored = [s for s in (life, retention) if s is not None]
        if not scored:
            return None
        return sum(scored) / len(scored)

    def _score_coupling(
        self, profile: IncomingDataProfile, graph: RegisteredGraph
    ) -> float | None:
        if profile.is_computed_output is None:
            return None
        graph_computed = _bool_attr(graph.attributes.get(ATTR_IS_COMPUTED_OUTPUT))
        # Computed outputs joining a canonical-fact graph would be read as
        # canonical (spec §8, factor 11) — push apart.
        if profile.is_computed_output and graph_computed is not True:
            return 0.0
        if graph_computed is None:
            return None
        return 1.0 if profile.is_computed_output == graph_computed else 0.0

    def _score_graph(self, profile: IncomingDataProfile, graph: RegisteredGraph) -> ScoredGraph:
        scorers = {
            "identity_value": self._score_identity,
            "ontology_compatibility": self._score_ontology,
            "tenancy": self._score_tenancy,
            "lifecycle": self._score_lifecycle,
            "computational_coupling": self._score_coupling,
        }
        scores: dict[str, float] = {}
        unscored: list[str] = []
        # Deterministic iteration: contract-key order is fixed here.
        for factor in AUTOMATED_FACTORS:
            key = factor.contract_key
            assert key is not None  # every automated factor has a contract key
            result = scorers[key](profile, graph)
            if result is None:
                unscored.append(key)
            else:
                scores[key] = result
        aggregate = sum(scores.values()) / len(scores) if scores else None
        return ScoredGraph(
            graph_name=graph.descriptor.name,
            factor_scores=scores,
            unscored_factors=tuple(unscored),
            aggregate=aggregate,
        )

    # --- the recommendation itself -------------------------------------------

    def _checklist(self) -> tuple[ChecklistItem, ...]:
        return tuple(
            ChecklistItem(
                number=f.number, factor_id=f.factor_id, title=f.title, prompt=f.checklist_prompt
            )
            for f in HUMAN_FACTORS
        )

    def recommend(
        self, profile: IncomingDataProfile, snapshot: Sequence[RegisteredGraph]
    ) -> AdvisorRecommendation:
        """Recommend an outcome architecture for `profile` given `snapshot`.

        Pure and deterministic. With an empty registry there is nothing to
        extend, so the answer is a definite `FULLY_ISOLATED` create — that is
        not the same as `INSUFFICIENT_INFORMATION`, which is reserved for the
        case where candidate graphs exist but the automated factors cannot be
        scored.
        """

        checklist = self._checklist()
        if not snapshot:
            return AdvisorRecommendation(
                outcome=Outcome.FULLY_ISOLATED,
                target_graph=None,
                checklist=checklist,
                reasons=("registry is empty: no existing graph to extend, create a new one",),
            )

        scored = tuple(self._score_graph(profile, g) for g in snapshot)
        # Best graph: highest aggregate, then name for a deterministic tie-break.
        # Graphs with no scorable factors sort last.
        best = max(
            scored,
            key=lambda s: (s.aggregate if s.aggregate is not None else -1.0, _neg_name(s.graph_name)),
        )

        if best.aggregate is None or len(best.factor_scores) < self._config.min_scored_factors:
            missing = ", ".join(best.unscored_factors) or "all automated factors"
            return AdvisorRecommendation(
                outcome=Outcome.INSUFFICIENT_INFORMATION,
                target_graph=best.graph_name,
                factor_scores=dict(best.factor_scores),
                unscored_factors=best.unscored_factors,
                checklist=checklist,
                per_graph=scored,
                reasons=(
                    (
                        f"only {len(best.factor_scores)} of {len(AUTOMATED_FACTORS)} automated "
                        f"factors could be scored (need {self._config.min_scored_factors}); "
                        f"missing inputs for: {missing}"
                    ),
                ),
            )

        outcome, reasons = self._classify(best)
        return AdvisorRecommendation(
            outcome=outcome,
            target_graph=best.graph_name,
            factor_scores=dict(best.factor_scores),
            unscored_factors=best.unscored_factors,
            checklist=checklist,
            per_graph=scored,
            reasons=reasons,
        )

    def _classify(self, best: ScoredGraph) -> tuple[Outcome, tuple[str, ...]]:
        cfg = self._config
        assert best.aggregate is not None
        aggregate = best.aggregate
        tenancy = best.factor_scores.get("tenancy")
        coupling = best.factor_scores.get("computational_coupling")
        identity = best.factor_scores.get("identity_value")
        base = (
            f"best match {best.graph_name!r} scored aggregate {aggregate:.2f} over "
            f"{len(best.factor_scores)} automated factors"
        )

        tenancy_ok = tenancy is None or tenancy >= cfg.tenancy_floor
        coupling_ok = coupling is None or coupling >= cfg.coupling_floor

        if aggregate >= cfg.extend_threshold and tenancy_ok and coupling_ok:
            return Outcome.EXTEND_SAME_PHYSICAL, (
                base,
                (
                    f"aggregate >= extend_threshold ({cfg.extend_threshold:.2f}); tenancy and "
                    "coupling above their floors: extend the same logical and physical graph"
                ),
            )
        if aggregate >= cfg.shared_logical_threshold and not tenancy_ok:
            return Outcome.SHARED_LOGICAL_SEPARATE_PHYSICAL, (
                base,
                (
                    "ontology compatible but tenancy/privacy below floor: keep one logical "
                    "graph on separate physical partitions"
                ),
            )
        if identity is not None and identity >= cfg.shared_identity_threshold:
            return Outcome.SEPARATE_SHARED_IDENTITY, (
                base,
                (
                    f"shared identity ({identity:.2f} >= {cfg.shared_identity_threshold:.2f}) "
                    "but ontology/coupling incompatible: separate graphs behind a shared "
                    "identity registry"
                ),
            )
        return Outcome.FULLY_ISOLATED, (
            base,
            (
                "no factor argues for joining: create a fully isolated graph with explicit "
                "cross-graph mappings if ever needed"
            ),
        )


def _neg_name(name: str) -> tuple[int, ...]:
    """Sort key that makes the *lexicographically smallest* name win a tie
    (so ties are broken deterministically toward the earliest name)."""
    return tuple(-ord(c) for c in name)


__all__ = ["GraphAdvisor"]
