"""KGIS graph registry + extend-vs-new advisor (Plan 7, spec §8, ADR-0005).

A persistent registry of `GraphDescriptor`s and a deterministic, human-gated
advisor that recommends one of four outcome architectures (or an honest
"insufficient information") for whether incoming data should extend an
existing graph or start a new one. Nothing here creates or extends a graph
automatically — in v1 every recommendation routes to a human, whose decision
and its later outcome are recorded for threshold calibration.

The frozen `kg_contracts.registry` module owns the `GraphDescriptor`,
`RegistryStore`, and `Recommendation` shapes; this package implements them and
carries — behind those contracts — the richer factors, outcomes, extension
attributes, and decision corpus the amended ADR-0005 and spec §8 ask for. The
contract gaps are filed as ADR candidates 0004/0005/0006.
"""

from kgis.registry.advisor import GraphAdvisor
from kgis.registry.models import (
    AUTOMATED_FACTORS,
    FACTORS,
    HUMAN_FACTORS,
    AdvisorConfig,
    AdvisorRecommendation,
    ChecklistItem,
    Factor,
    IncomingDataProfile,
    Outcome,
    RegisteredGraph,
    ScoredGraph,
)
from kgis.registry.store import DecisionRecord, SqliteRegistryStore, open_registry_db

__all__ = [
    "AUTOMATED_FACTORS",
    "FACTORS",
    "HUMAN_FACTORS",
    "AdvisorConfig",
    "AdvisorRecommendation",
    "ChecklistItem",
    "DecisionRecord",
    "Factor",
    "GraphAdvisor",
    "IncomingDataProfile",
    "Outcome",
    "RegisteredGraph",
    "ScoredGraph",
    "SqliteRegistryStore",
    "open_registry_db",
]
