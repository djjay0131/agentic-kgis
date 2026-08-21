"""The SQLite registry store: CRUD, versioning, extension attributes, the
decision corpus, and — the property that matters most for a *persistent*
store — that everything survives a close/reopen of the same file.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kg_contracts.registry import Backend, GraphDescriptor, RegistryStore
from kgis.clock import FixedClock
from kgis.registry import (
    AdvisorRecommendation,
    Outcome,
    open_registry_db,
)
from kgis.registry.models import ATTR_BACKEND_OPEN_ID

_FIXED = FixedClock(datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC))


def _descriptor(name: str = "baseball-kg", **overrides: object) -> GraphDescriptor:
    base: dict[str, object] = {
        "name": name,
        "owner": "kgis-team",
        "domain": "baseball",
        "backend": Backend.MEMORY,
        "created_by": "djjay",
    }
    base.update(overrides)
    return GraphDescriptor(**base)  # type: ignore[arg-type]


def _recommendation() -> AdvisorRecommendation:
    return AdvisorRecommendation(
        outcome=Outcome.EXTEND_SAME_PHYSICAL,
        target_graph="baseball-kg",
        factor_scores={"identity_value": 1.0, "ontology_compatibility": 0.8},
        reasons=("aggregate above extend threshold",),
    )


def test_store_conforms_to_registry_store_protocol() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    assert isinstance(store, RegistryStore)


def test_register_get_all_roundtrip() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.register(_descriptor())
    got = store.get("baseball-kg")
    assert got is not None
    assert got.name == "baseball-kg"
    assert [d.name for d in store.all()] == ["baseball-kg"]


def test_get_unknown_returns_none() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    assert store.get("nope") is None


def test_register_bumps_version_and_get_returns_latest() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.register(_descriptor(owner="v1-owner"))
    store.register(_descriptor(owner="v2-owner"))
    assert store.versions("baseball-kg") == [1, 2]
    assert store.latest_version("baseball-kg") == 2
    latest = store.get("baseball-kg")
    assert latest is not None and latest.owner == "v2-owner"
    v1 = store.get_version("baseball-kg", 1)
    assert v1 is not None and v1.owner == "v1-owner"


def test_all_returns_latest_of_each_name_sorted() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.register(_descriptor(name="zebra-kg"))
    store.register(_descriptor(name="alpha-kg"))
    assert [d.name for d in store.all()] == ["alpha-kg", "zebra-kg"]


def test_extension_attributes_and_open_backend_persist() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.register(
        _descriptor(name="pg-graph"),
        attributes={"attribute_types": "height_cm,weight_kg"},
        backend_ref="postgres+age",
    )
    attrs = store.attributes_for("pg-graph")
    assert attrs["attribute_types"] == "height_cm,weight_kg"
    assert attrs[ATTR_BACKEND_OPEN_ID] == "postgres+age"
    (graph,) = store.snapshot()
    assert graph.resolved_backend == "postgres+age"
    assert graph.attribute_types() == frozenset({"height_cm", "weight_kg"})


def test_backend_enum_still_used_when_no_open_ref() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.register(_descriptor())
    (graph,) = store.snapshot()
    assert graph.resolved_backend == "MEMORY"


def test_record_decision_and_read_back() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    record = store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.EXTEND_SAME_PHYSICAL,
        decided_by="djjay",
        rationale="ontology and identity both align",
    )
    assert record.decided_by == "djjay"
    read = store.decision(record.decision_id)
    assert read is not None
    assert read.chosen_outcome is Outcome.EXTEND_SAME_PHYSICAL
    assert read.recommendation.target_graph == "baseball-kg"
    assert store.decisions() == [read]


def test_human_can_override_the_recommendation() -> None:
    # The advisor recommended EXTEND; the human decides to keep it separate.
    store = open_registry_db(":memory:", clock=_FIXED)
    record = store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.SEPARATE_SHARED_IDENTITY,
        decided_by="djjay",
        rationale="stewardship collision the advisor cannot see",
        graph_name="new-baseball-kg",
    )
    read = store.decision(record.decision_id)
    assert read is not None
    assert read.recommendation.outcome is Outcome.EXTEND_SAME_PHYSICAL
    assert read.chosen_outcome is Outcome.SEPARATE_SHARED_IDENTITY
    assert read.graph_name == "new-baseball-kg"


def test_record_outcome_appends_to_corpus() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    record = store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.EXTEND_SAME_PHYSICAL,
        decided_by="djjay",
        rationale="looks right",
    )
    store.record_outcome(record.decision_id, label="good_merge", note="no false merges after 30d")
    read = store.decision(record.decision_id)
    assert read is not None
    assert read.outcome_label == "good_merge"
    assert read.outcome_recorded_at is not None


def test_record_outcome_unknown_decision_raises() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    with pytest.raises(KeyError):
        store.record_outcome("dec_missing", label="x")


def test_decisions_filtered_by_graph_name() -> None:
    store = open_registry_db(":memory:", clock=_FIXED)
    store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.EXTEND_SAME_PHYSICAL,
        decided_by="a",
        rationale="r",
        graph_name="g1",
        decision_id="d1",
    )
    store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.FULLY_ISOLATED,
        decided_by="b",
        rationale="r",
        graph_name="g2",
        decision_id="d2",
    )
    assert [d.decision_id for d in store.decisions("g1")] == ["d1"]


def test_persistence_survives_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.db"
    store = open_registry_db(db_path, clock=_FIXED)
    store.register(
        _descriptor(name="durable-kg", node_types=("Player",)),
        attributes={"attribute_types": "height_cm"},
        backend_ref="postgres+age",
    )
    record = store.record_decision(
        _recommendation(),
        chosen_outcome=Outcome.EXTEND_SAME_PHYSICAL,
        decided_by="djjay",
        rationale="persist me",
        decision_id="dec_persist",
    )
    store.close()

    reopened = open_registry_db(db_path, clock=_FIXED)
    got = reopened.get("durable-kg")
    assert got is not None and got.node_types == ("Player",)
    assert reopened.attributes_for("durable-kg")["attribute_types"] == "height_cm"
    (graph,) = reopened.snapshot()
    assert graph.resolved_backend == "postgres+age"
    read = reopened.decision("dec_persist")
    assert read is not None and read.rationale == "persist me"
    assert record.decision_id == "dec_persist"


def test_reopen_does_not_reset_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.db"
    open_registry_db(db_path, clock=_FIXED).close()
    reopened = open_registry_db(db_path, clock=_FIXED)
    version = reopened._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
