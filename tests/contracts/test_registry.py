import pytest
from pydantic import ValidationError

from kg_contracts.registry import (
    SCORED_FACTORS_V1,
    Backend,
    GraphDescriptor,
    Recommendation,
    RegistryStore,
)


def _descriptor(**overrides: object) -> GraphDescriptor:
    base: dict[str, object] = dict(
        name="baseball-kg",
        owner="kgis-team",
        domain="baseball",
        backend=Backend.MEMORY,
        created_by="djjay",
    )
    base.update(overrides)
    return GraphDescriptor(**base)  # type: ignore[arg-type]


# --- 1. GraphDescriptor valid + frozen (mutation raises) ---


def test_graph_descriptor_valid_construction():
    descriptor = _descriptor(
        tags=("sports", "baseball"),
        connection_ref="secret-name-not-value",
        node_types=("Player", "Team"),
        edge_types=("PLAYS_FOR",),
        ontology_version="1",
        policy_ref="policy-1",
        decision_record="dr-1",
    )
    assert descriptor.name == "baseball-kg"
    assert descriptor.backend is Backend.MEMORY
    assert descriptor.tags == ("sports", "baseball")


def test_graph_descriptor_is_frozen():
    descriptor = _descriptor()
    with pytest.raises(ValidationError):
        descriptor.name = "other-kg"  # type: ignore[misc]


# --- 2. Recommendation extend without graph_name rejected ---


def test_recommendation_extend_without_graph_name_rejected():
    with pytest.raises(ValidationError, match="graph_name"):
        Recommendation(
            action="extend",
            factor_scores={},
            checklist=(),
            reasons=("looks similar",),
        )


def test_recommendation_extend_with_graph_name_accepted():
    rec = Recommendation(
        action="extend",
        graph_name="baseball-kg",
        factor_scores={"identity_value": 0.8},
        checklist=(),
        reasons=("high identity overlap",),
    )
    assert rec.graph_name == "baseball-kg"


def test_recommendation_create_without_graph_name_accepted():
    rec = Recommendation(
        action="create",
        factor_scores={},
        checklist=(),
        reasons=("no matching graph found",),
    )
    assert rec.graph_name is None


# --- 3. Recommendation with factor_scores key outside SCORED_FACTORS_V1 rejected ---


def test_recommendation_rejects_unknown_factor_score_key():
    with pytest.raises(ValidationError, match="factor"):
        Recommendation(
            action="create",
            factor_scores={"not_a_real_factor": 0.5},
            checklist=(),
            reasons=("test",),
        )


def test_recommendation_rejects_factor_score_out_of_range():
    with pytest.raises(ValidationError, match="factor"):
        Recommendation(
            action="create",
            factor_scores={"tenancy": 1.5},
            checklist=(),
            reasons=("test",),
        )


# --- 4. Recommendation carries checklist entries for unscored factors ---


def test_recommendation_carries_checklist_for_unscored_factors():
    rec = Recommendation(
        action="create",
        factor_scores={
            "identity_value": 0.9,
            "ontology_compatibility": 0.7,
            "tenancy": 0.5,
            "lifecycle": 0.6,
            "computational_coupling": 0.4,
        },
        checklist=(
            "confirm data residency requirements",
            "confirm ownership handoff plan",
        ),
        reasons=("all five factors scored; residency still needs human sign-off",),
    )
    assert set(rec.factor_scores) == SCORED_FACTORS_V1
    assert rec.checklist == (
        "confirm data residency requirements",
        "confirm ownership handoff plan",
    )


def test_recommendation_requires_at_least_one_reason():
    with pytest.raises(ValidationError):
        Recommendation(
            action="create",
            factor_scores={},
            checklist=(),
            reasons=(),
        )


# --- 5. Duck-typed fake satisfies RegistryStore ---


class _FakeRegistryStore:
    def __init__(self) -> None:
        self._graphs: dict[str, GraphDescriptor] = {}

    def register(self, descriptor: GraphDescriptor) -> None:
        self._graphs[descriptor.name] = descriptor

    def get(self, name: str) -> GraphDescriptor | None:
        return self._graphs.get(name)

    def all(self) -> list[GraphDescriptor]:
        return list(self._graphs.values())


def test_duck_typed_fake_satisfies_registry_store():
    store = _FakeRegistryStore()
    assert isinstance(store, RegistryStore)
    descriptor = _descriptor()
    store.register(descriptor)
    assert store.get("baseball-kg") == descriptor
    assert store.get("missing") is None
    assert store.all() == [descriptor]
