"""Registry/advisor value types (Plan 7, ADR-0005 as amended, spec §8).

The frozen `kg_contracts.registry` module gives us `GraphDescriptor`,
`RegistryStore`, and a *binary* `Recommendation` (extend / create) scored on
five factors. The amended ADR-0005 and spec §8 ask for more than that frozen
shape can currently express:

- **Twelve factors**, of which v1 automates five (1, 2, 5, 6, 11) and leaves
  the other seven as a structured human checklist.
- **Four outcome architectures**, not a binary — extend-same-physical, a
  shared logical graph on separate physical partitions, separate graphs
  behind a shared identity registry, and fully isolated graphs.
- An honest **"insufficient information"** result when the inputs a factor
  needs are absent, rather than a fabricated score.

None of that fits inside the frozen contract without editing it, so the
richer decision is modelled here in `kgis` and projected *down* to the
contract `Recommendation` via `AdvisorRecommendation.to_contract()` (which
returns ``None`` for the insufficient-information case the contract cannot
represent). The contract gaps this reveals are filed as ADR candidates
0005 (open backend identifier) and 0006 (four outcomes + insufficient
information); see also candidate 0004 (attribute vocabulary), resolved here
through registry extension attributes rather than a contract change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.registry import GraphDescriptor
from kg_contracts.registry import Recommendation as ContractRecommendation

# --- Reserved extension-attribute keys ---------------------------------------
# These live at the registry layer, not in the frozen contract. They let a
# graph declare an attribute vocabulary (candidate 0004) and an open backend
# identifier (candidate 0005) without editing the frozen `GraphDescriptor`.

ATTR_ATTRIBUTE_TYPES = "attribute_types"
ATTR_BACKEND_OPEN_ID = "backend.open_id"
ATTR_IDENTITY_AUTHORITY = "identity_authority"
ATTR_TENANCY_CLASS = "tenancy_class"
ATTR_CONTAINS_MINORS = "contains_minors_data"
ATTR_LIFECYCLE_CLASS = "lifecycle_class"
ATTR_RETENTION_CLASS = "retention_class"
ATTR_IS_COMPUTED_OUTPUT = "is_computed_output"

# --- The twelve factors (spec §8, ADR-0005 amended) --------------------------


@dataclass(frozen=True)
class Factor:
    """One of the twelve extend-vs-new factors.

    `automated` marks the v1 subset the advisor scores from data; the rest
    surface only as `checklist_prompt`s for the human in the loop.
    `contract_key`, on automated factors, is the exact
    `SCORED_FACTORS_V1` key the score must be filed under so it round-trips
    into a contract `Recommendation.factor_scores` without renaming.
    """

    number: int
    factor_id: str
    title: str
    automated: bool
    checklist_prompt: str
    contract_key: str | None = None


FACTORS: tuple[Factor, ...] = (
    Factor(
        1,
        "shared_identity_value",
        "Shared identity value",
        automated=True,
        contract_key="identity_value",
        checklist_prompt=(
            "Who is the identity authority, and is shared identity a reason to "
            "join or a reason to stay apart?"
        ),
    ),
    Factor(
        2,
        "ontology_compatibility",
        "Ontology compatibility",
        automated=True,
        contract_key="ontology_compatibility",
        checklist_prompt=(
            "Do concepts, relationship semantics, cardinality, identity rules, "
            "and governance authority actually agree?"
        ),
    ),
    Factor(
        3,
        "assertion_evidence_semantics",
        "Assertion and evidence semantics",
        automated=False,
        checklist_prompt="Do the two sides mean the same thing by an assertion and its evidence?",
    ),
    Factor(
        4,
        "temporal_model_compatibility",
        "Temporal-model compatibility",
        automated=False,
        checklist_prompt="Are the bitemporal / validity models compatible?",
    ),
    Factor(
        5,
        "tenancy_privacy_access",
        "Tenancy, privacy, and access",
        automated=True,
        contract_key="tenancy",
        checklist_prompt=(
            "Tenancy, privacy, access — including minors' data, purpose "
            "limitation, and inference leakage through traversal or embeddings."
        ),
    ),
    Factor(
        6,
        "lifecycle_retention",
        "Lifecycle and retention",
        automated=True,
        contract_key="lifecycle",
        checklist_prompt="Do the lifecycle and retention regimes match?",
    ),
    Factor(
        7,
        "workload_backend_compatibility",
        "Workload and backend compatibility",
        automated=False,
        checklist_prompt="Are the workload profile and storage backend compatible?",
    ),
    Factor(
        8,
        "governance_stewardship",
        "Governance and stewardship",
        automated=False,
        checklist_prompt="Is there a single accountable steward, or two that would collide?",
    ),
    Factor(
        9,
        "failure_blast_radius",
        "Failure / blast-radius requirements",
        automated=False,
        checklist_prompt="Would joining widen the blast radius of a failure unacceptably?",
    ),
    Factor(
        10,
        "cross_domain_traversal_value",
        "Cross-domain traversal value",
        automated=False,
        checklist_prompt=(
            "Is there real cross-domain traversal value, or overlap without "
            "cross-domain questions (cost without benefit)?"
        ),
    ),
    Factor(
        11,
        "computational_model_coupling",
        "Computational-model coupling",
        automated=True,
        contract_key="computational_coupling",
        checklist_prompt=(
            "Would joining cause one domain's computed outputs to be read as "
            "another's canonical facts?"
        ),
    ),
    Factor(
        12,
        "rebuild_deletion_boundaries",
        "Rebuild and deletion boundaries",
        automated=False,
        checklist_prompt="Regenerable data vs. irreplaceable human curation — do the boundaries align?",
    ),
)

AUTOMATED_FACTORS: tuple[Factor, ...] = tuple(f for f in FACTORS if f.automated)
HUMAN_FACTORS: tuple[Factor, ...] = tuple(f for f in FACTORS if not f.automated)

# Sanity: the automated subset's contract keys must be exactly the frozen
# SCORED_FACTORS_V1 set, or scores will not round-trip into the contract.
_AUTOMATED_CONTRACT_KEYS: frozenset[str] = frozenset(
    f.contract_key for f in AUTOMATED_FACTORS if f.contract_key is not None
)


# --- Four outcome architectures + the honest null ----------------------------


class Outcome(StrEnum):
    """The advisor's outcome space (spec §8): four architectures plus an
    explicit insufficient-information result.

    The first four are the spec's four outcome architectures; the last is
    emitted instead of a fabricated score when the automated factors cannot
    be evaluated. Only `EXTEND_SAME_PHYSICAL` and
    `SHARED_LOGICAL_SEPARATE_PHYSICAL` project to a contract `extend`; the two
    separation outcomes project to `create`; `INSUFFICIENT_INFORMATION` has no
    contract projection at all.
    """

    EXTEND_SAME_PHYSICAL = "EXTEND_SAME_PHYSICAL"
    SHARED_LOGICAL_SEPARATE_PHYSICAL = "SHARED_LOGICAL_SEPARATE_PHYSICAL"
    SEPARATE_SHARED_IDENTITY = "SEPARATE_SHARED_IDENTITY"
    FULLY_ISOLATED = "FULLY_ISOLATED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


_EXTEND_OUTCOMES: frozenset[Outcome] = frozenset(
    {Outcome.EXTEND_SAME_PHYSICAL, Outcome.SHARED_LOGICAL_SEPARATE_PHYSICAL}
)


# --- Advisor inputs ----------------------------------------------------------


class IncomingDataProfile(BaseModel):
    """What the incoming data looks like, as far as the advisor can tell.

    Every scoring-relevant field is optional: a missing field is missing
    *information*, and the advisor reports it as such rather than inventing a
    value. This is the deterministic input to scoring — no I/O, no clock.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str | None = None
    identity_authority: str | None = None
    identity_keys: frozenset[str] = frozenset()
    node_types: frozenset[str] = frozenset()
    edge_types: frozenset[str] = frozenset()
    attribute_types: frozenset[str] = frozenset()
    tenancy_class: str | None = None
    contains_minors_data: bool | None = None
    lifecycle_class: str | None = None
    retention_class: str | None = None
    is_computed_output: bool | None = None


class RegisteredGraph(BaseModel):
    """A registry snapshot row: a descriptor plus its extension attributes.

    Extension attributes (`attributes`) carry the things the frozen
    `GraphDescriptor` cannot yet declare — an attribute vocabulary
    (candidate 0004) and an open backend identifier (candidate 0005) — so the
    advisor can compare against them without the contract changing.
    `resolved_backend` prefers the open identifier when present, else the
    descriptor's enum value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    descriptor: GraphDescriptor
    version: int = 1
    attributes: Mapping[str, str] = Field(default_factory=dict)

    @property
    def resolved_backend(self) -> str:
        return self.attributes.get(ATTR_BACKEND_OPEN_ID, str(self.descriptor.backend))

    def attribute_types(self) -> frozenset[str]:
        raw = self.attributes.get(ATTR_ATTRIBUTE_TYPES)
        if not raw:
            return frozenset()
        return frozenset(part for part in (p.strip() for p in raw.split(",")) if part)


class AdvisorConfig(BaseModel):
    """Deterministic thresholds for the advisor (spec §8 calibration corpus).

    Recommendations are a pure function of (registry snapshot, incoming
    profile, this config). No randomness, no clock: change nothing here and
    the same snapshot always yields the same recommendation, which is what
    makes the recorded decision corpus usable to recalibrate these numbers
    later through `ConfidencePolicy`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    extend_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    shared_logical_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    shared_identity_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    tenancy_floor: float = Field(default=0.5, ge=0.0, le=1.0)
    coupling_floor: float = Field(default=0.5, ge=0.0, le=1.0)
    min_scored_factors: int = Field(default=2, ge=1, le=5)


# --- Advisor output ----------------------------------------------------------


class ChecklistItem(BaseModel):
    """One human-assessed factor surfaced for adjudication (spec §8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    factor_id: str
    title: str
    prompt: str

    def render(self) -> str:
        return f"{self.number}. {self.title}: {self.prompt}"


class ScoredGraph(BaseModel):
    """The per-graph automated factor breakdown, kept for explainability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_name: str
    factor_scores: dict[str, float] = Field(default_factory=dict)
    unscored_factors: tuple[str, ...] = ()
    aggregate: float | None = None


class AdvisorRecommendation(BaseModel):
    """The advisor's full, explainable output (richer than the contract).

    Carries no single collapsed score — routing to auto/assess/human still
    goes through `ConfidencePolicy`, exactly as the frozen contract intends.
    `factor_scores` holds only the automated factors that could actually be
    scored (keys are `SCORED_FACTORS_V1`); `checklist` holds the seven human
    factors; `unscored_factors` names any automated factor whose inputs were
    missing, so a reader can see *why* a score is absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Outcome
    target_graph: str | None = None
    factor_scores: dict[str, float] = Field(default_factory=dict)
    unscored_factors: tuple[str, ...] = ()
    checklist: tuple[ChecklistItem, ...] = ()
    per_graph: tuple[ScoredGraph, ...] = ()
    reasons: tuple[str, ...] = Field(min_length=1)

    def to_contract(self) -> ContractRecommendation | None:
        """Project down to the frozen `kg_contracts.registry.Recommendation`.

        Returns ``None`` for `INSUFFICIENT_INFORMATION`: the contract's
        `action` is `extend | create` with no honest-null member, so the
        caller must *not* be handed a fabricated extend/create. The two
        extend-shaped outcomes become `action="extend"` (with `graph_name`);
        the two separation outcomes become `action="create"`.
        """

        if self.outcome is Outcome.INSUFFICIENT_INFORMATION:
            return None
        action: str = "extend" if self.outcome in _EXTEND_OUTCOMES else "create"
        graph_name = self.target_graph if action == "extend" else None
        return ContractRecommendation(
            action=action,  # type: ignore[arg-type]
            graph_name=graph_name,
            factor_scores=dict(self.factor_scores),
            checklist=tuple(item.render() for item in self.checklist),
            reasons=self.reasons,
        )


__all__ = [
    "AUTOMATED_FACTORS",
    "FACTORS",
    "HUMAN_FACTORS",
    "AdvisorConfig",
    "AdvisorRecommendation",
    "ChecklistItem",
    "ContractRecommendation",
    "Factor",
    "IncomingDataProfile",
    "Outcome",
    "RegisteredGraph",
    "ScoredGraph",
]
