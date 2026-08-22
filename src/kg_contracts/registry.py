"""Graph registry contracts: `GraphDescriptor`, `Recommendation`, `RegistryStore`
(spec §8, ADR-0005 as amended, disposition D3).

This module is schema + protocol only. The SQLite-backed `RegistryStore`
implementation lives in `kgis`; the advisor that produces `Recommendation`s
lives in `kgcs` (Plan 7). Nothing here does I/O, and nothing here decides:
the registry *advises* on the new-graph-vs-extend-existing question, a
human or `ConfidencePolicy`-routed decision acts on that advice. There is
no auto-creation path anywhere in this module.

A single `confidence` float is banned here just as it is for
`CandidateScores` (spec §5.2, disposition A2). `Recommendation.factor_scores`
keeps the five v1-scored factors — identity value, ontology compatibility,
tenancy, lifecycle, computational coupling — explicit and separately
readable rather than collapsed into one number. The remaining factors a
human should weigh are not silently dropped either: they surface in
`checklist` as a structured list for the human who is in the loop in v1
anyway (disposition D3). `Recommendation` carries no overall score field at
all — routing a recommendation to auto/assess/human still goes through
`ConfidencePolicy` like every other scored artifact in this package.
"""

from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._frozen import FrozenDictFloat


class Backend(StrEnum):
    """Storage backends a registered graph can live on."""

    SPANNER = "SPANNER"
    NEO4J = "NEO4J"
    MEMORY = "MEMORY"


class GraphDescriptor(BaseModel):
    """A registered graph's identity, ownership, and shape (spec §8).

    `connection_ref` is a secret **name** (e.g. a Secret Manager key), never
    a secret value — this package does no I/O and must never carry a
    credential that could be logged or serialized alongside a descriptor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    tags: tuple[str, ...] = ()
    backend: Backend
    connection_ref: str | None = None
    node_types: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    ontology_version: str | None = None
    policy_ref: str | None = None
    created_by: str = Field(min_length=1)
    decision_record: str | None = None


SCORED_FACTORS_V1: frozenset[str] = frozenset(
    {
        "identity_value",
        "ontology_compatibility",
        "tenancy",
        "lifecycle",
        "computational_coupling",
    }
)
"""The five factors v1 scores explicitly (spec §8, disposition D3):
identity value, ontology compatibility, tenancy, lifecycle, and
computational coupling. `Recommendation.factor_scores` keys must be a
subset of this set; any other factor a human should weigh belongs in
`Recommendation.checklist` instead."""


class Recommendation(BaseModel):
    """The advisor's scored extend-vs-create output (spec §8, disposition D3).

    Carries no single overall score: routing this recommendation through
    `AUTO`/`LLM_ASSESS`/`HUMAN` goes through `ConfidencePolicy` like
    everything else in this package (disposition A2) — collapsing the five
    factors into one number here would defeat the point of scoring them
    separately. `extend` requires `graph_name` naming which existing graph
    to extend; `create` carries no target graph. The advisor never decides
    on its own: this model is advice for a human or a policy to act on, not
    an instruction that gets executed automatically.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    action: Literal["extend", "create"]
    graph_name: str | None = None
    factor_scores: FrozenDictFloat = Field(default_factory=dict)
    checklist: tuple[str, ...] = ()
    reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_extend_requires_graph_name(self) -> "Recommendation":
        if self.action == "extend" and self.graph_name is None:
            raise ValueError("action='extend' requires graph_name")
        return self

    @model_validator(mode="after")
    def _check_factor_scores(self) -> "Recommendation":
        for factor, score in self.factor_scores.items():
            if factor not in SCORED_FACTORS_V1:
                raise ValueError(
                    f"unknown factor {factor!r}: factor_scores keys must be a "
                    f"subset of SCORED_FACTORS_V1 {sorted(SCORED_FACTORS_V1)}"
                )
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"factor_scores[{factor!r}] = {score!r} must be in [0.0, 1.0]"
                )
        return self


@runtime_checkable
class RegistryStore(Protocol):
    """Persistence for `GraphDescriptor`s (spec §8).

    The registry only stores and answers "what graphs exist" questions;
    the new-graph-vs-extend-existing decision itself is made elsewhere, by
    a human or a `ConfidencePolicy`-routed process consuming a
    `Recommendation` — never by this protocol or its implementations.
    """

    def register(self, descriptor: GraphDescriptor) -> None: ...

    def get(self, name: str) -> GraphDescriptor | None: ...

    def all(self) -> list[GraphDescriptor]: ...
