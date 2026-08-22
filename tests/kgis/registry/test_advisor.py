"""The extend-vs-new advisor: determinism, explainability, the honest null,
the four outcome architectures, and the automated-vs-human factor split.
"""

from kg_contracts.registry import SCORED_FACTORS_V1, Backend, GraphDescriptor
from kgis.registry import (
    AUTOMATED_FACTORS,
    FACTORS,
    HUMAN_FACTORS,
    AdvisorConfig,
    GraphAdvisor,
    IncomingDataProfile,
    Outcome,
    RegisteredGraph,
)


def _graph(name: str, **attrs: str) -> RegisteredGraph:
    return RegisteredGraph(
        descriptor=GraphDescriptor(
            name=name,
            owner="t",
            domain="baseball",
            backend=Backend.MEMORY,
            created_by="dj",
            node_types=("Player", "Team"),
            edge_types=("PLAYS_FOR",),
        ),
        attributes=attrs,
    )


_ALIGNED = IncomingDataProfile(
    node_types=frozenset({"Player", "Team"}),
    edge_types=frozenset({"PLAYS_FOR"}),
    identity_authority="mlbam",
    tenancy_class="public",
    lifecycle_class="durable",
    is_computed_output=False,
)


def _graph_aligned(name: str = "baseball-kg") -> RegisteredGraph:
    return _graph(
        name,
        identity_authority="mlbam",
        tenancy_class="public",
        lifecycle_class="durable",
        is_computed_output="false",
    )


# --- factor split (spec §8: v1 automates 1,2,5,6,11) -------------------------


def test_twelve_factors_five_automated_seven_human() -> None:
    assert len(FACTORS) == 12
    assert len(AUTOMATED_FACTORS) == 5
    assert len(HUMAN_FACTORS) == 7
    assert {f.number for f in AUTOMATED_FACTORS} == {1, 2, 5, 6, 11}


def test_automated_factor_keys_are_exactly_contract_scored_factors() -> None:
    keys = {f.contract_key for f in AUTOMATED_FACTORS}
    assert keys == set(SCORED_FACTORS_V1)


def test_checklist_carries_the_seven_human_factors() -> None:
    rec = GraphAdvisor().recommend(_ALIGNED, [_graph_aligned()])
    assert {item.number for item in rec.checklist} == {3, 4, 7, 8, 9, 10, 12}


# --- determinism -------------------------------------------------------------


def test_recommendation_is_deterministic_for_fixed_snapshot_and_config() -> None:
    advisor = GraphAdvisor()
    snapshot = [_graph_aligned("alpha"), _graph_aligned("beta")]
    first = advisor.recommend(_ALIGNED, snapshot)
    second = advisor.recommend(_ALIGNED, snapshot)
    assert first == second


def test_tie_break_is_deterministic_toward_earliest_name() -> None:
    advisor = GraphAdvisor()
    snapshot = [_graph_aligned("zebra"), _graph_aligned("alpha")]
    rec = advisor.recommend(_ALIGNED, snapshot)
    assert rec.target_graph == "alpha"


# --- explainability ----------------------------------------------------------


def test_recommendation_exposes_per_factor_breakdown() -> None:
    rec = GraphAdvisor().recommend(_ALIGNED, [_graph_aligned()])
    assert set(rec.factor_scores) == set(SCORED_FACTORS_V1)
    assert all(0.0 <= v <= 1.0 for v in rec.factor_scores.values())
    assert rec.reasons  # never empty
    assert len(rec.per_graph) == 1


# --- the four outcome architectures ------------------------------------------


def test_extend_same_physical_when_everything_aligns() -> None:
    rec = GraphAdvisor().recommend(_ALIGNED, [_graph_aligned()])
    assert rec.outcome is Outcome.EXTEND_SAME_PHYSICAL
    contract = rec.to_contract()
    assert contract is not None and contract.action == "extend"
    assert contract.graph_name == "baseball-kg"


def test_shared_logical_separate_physical_when_tenancy_conflicts() -> None:
    # Ontology/identity align, but incoming minors' data hits a public graph:
    # tenancy is forced below its floor while the rest still score high.
    profile = _ALIGNED.model_copy(update={"contains_minors_data": True, "tenancy_class": "minors"})
    rec = GraphAdvisor().recommend(profile, [_graph_aligned()])
    assert rec.outcome is Outcome.SHARED_LOGICAL_SEPARATE_PHYSICAL
    contract = rec.to_contract()
    assert contract is not None and contract.action == "extend"


def test_separate_shared_identity_when_only_identity_aligns() -> None:
    # Same identity authority, but ontology disjoint and coupling conflicts.
    graph = _graph(
        "other-kg",
        identity_authority="mlbam",
        tenancy_class="internal",
        lifecycle_class="ephemeral",
        is_computed_output="false",
    )
    profile = IncomingDataProfile(
        node_types=frozenset({"Sensor"}),
        edge_types=frozenset({"MEASURES"}),
        identity_authority="mlbam",
        tenancy_class="public",
        lifecycle_class="durable",
        is_computed_output=True,
    )
    rec = GraphAdvisor().recommend(profile, [graph])
    assert rec.outcome is Outcome.SEPARATE_SHARED_IDENTITY
    contract = rec.to_contract()
    assert contract is not None and contract.action == "create"
    assert contract.graph_name is None


def test_fully_isolated_when_nothing_argues_for_joining() -> None:
    graph = _graph(
        "other-kg",
        identity_authority="usssa",
        tenancy_class="internal",
        lifecycle_class="ephemeral",
        is_computed_output="false",
    )
    profile = IncomingDataProfile(
        node_types=frozenset({"Sensor"}),
        edge_types=frozenset({"MEASURES"}),
        identity_authority="mlbam",
        tenancy_class="public",
        lifecycle_class="durable",
        is_computed_output=False,
    )
    rec = GraphAdvisor().recommend(profile, [graph])
    assert rec.outcome is Outcome.FULLY_ISOLATED
    contract = rec.to_contract()
    assert contract is not None and contract.action == "create"


def test_empty_registry_recommends_create_not_insufficient() -> None:
    rec = GraphAdvisor().recommend(_ALIGNED, [])
    assert rec.outcome is Outcome.FULLY_ISOLATED
    assert rec.to_contract() is not None


# --- the honest null ---------------------------------------------------------


def test_insufficient_information_when_inputs_missing() -> None:
    # A bare profile against a bare graph: no factor can be scored.
    bare_graph = RegisteredGraph(
        descriptor=GraphDescriptor(
            name="bare-kg", owner="t", domain="d", backend=Backend.MEMORY, created_by="dj"
        )
    )
    rec = GraphAdvisor().recommend(IncomingDataProfile(), [bare_graph])
    assert rec.outcome is Outcome.INSUFFICIENT_INFORMATION
    assert rec.to_contract() is None  # the contract has no honest-null member
    assert rec.factor_scores == {}
    assert set(rec.unscored_factors) == set(SCORED_FACTORS_V1)
    assert rec.reasons


def test_insufficient_information_respects_min_scored_factors() -> None:
    # Only ontology is scorable (one factor). Default min_scored_factors=2 ->
    # insufficient; lowering it to 1 -> a real recommendation.
    graph = _graph("baseball-kg")  # node/edge types present, no other attrs
    profile = IncomingDataProfile(node_types=frozenset({"Player"}))
    strict = GraphAdvisor().recommend(profile, [graph])
    assert strict.outcome is Outcome.INSUFFICIENT_INFORMATION
    lenient = GraphAdvisor(AdvisorConfig(min_scored_factors=1)).recommend(profile, [graph])
    assert lenient.outcome is not Outcome.INSUFFICIENT_INFORMATION
    assert "ontology_compatibility" in lenient.factor_scores


def test_partial_scores_are_never_fabricated() -> None:
    # Identity + ontology known, tenancy/lifecycle/coupling unknown: the known
    # factors are scored and the unknown ones are named, not zero-filled.
    graph = _graph("baseball-kg", identity_authority="mlbam")
    profile = IncomingDataProfile(
        node_types=frozenset({"Player", "Team"}),
        edge_types=frozenset({"PLAYS_FOR"}),
        identity_authority="mlbam",
    )
    rec = GraphAdvisor().recommend(profile, [graph])
    assert "identity_value" in rec.factor_scores
    assert "ontology_compatibility" in rec.factor_scores
    assert set(rec.unscored_factors) == {"tenancy", "lifecycle", "computational_coupling"}
