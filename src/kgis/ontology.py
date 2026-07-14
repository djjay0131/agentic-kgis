"""The declared vocabulary of a graph, and how well an ingest covers it.

`Ontology` is the set of terms a graph says it accepts — read off a
`GraphDescriptor` (`node_types` / `edge_types`) or declared inline. It is
*data*, not code: which terms are legal is a property of the graph, never of
the pipeline.

Coverage is one of the two things a dry run exists to tell an operator
(spec §6): **"unknown types reported, never hidden."** So `CoverageCounter`
reports in both directions, and they answer different questions:

- **unknown** terms — used by the data, not declared by the graph. These are
  the ones that reject (or warn), and they usually mean the source drifted.
- **unused** terms — declared by the graph, never seen in the data. Nothing
  is wrong with these, but a "Player" ontology whose ingest produced zero
  Players is a mapping bug you want to see *before* you run it for real.

An ontology is optional. When no ontology is supplied, coverage reports
`declared=False` and a `coverage_ratio` of `None` — an honest null (ADR-0009),
not a reassuring 100%.
"""

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    EntityCandidate,
    RelationCandidate,
)
from kg_contracts.registry import GraphDescriptor


class Ontology(BaseModel):
    """The terms a graph declares (spec §7.3).

    An empty term set means *unconstrained*, not *forbidden*: a graph that
    declares no `entity_types` accepts any entity type. Declaring nothing and
    rejecting everything would make the registry's optional fields a trap.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    entity_types: frozenset[str] = frozenset()
    relation_types: frozenset[str] = frozenset()
    attributes: frozenset[str] = frozenset()

    @staticmethod
    def from_descriptor(descriptor: GraphDescriptor) -> "Ontology":
        """Read the ontology off a registered graph (spec §8).

        `GraphDescriptor` declares node and edge types but has no attribute
        vocabulary, so attributes come back unconstrained. That is a real gap
        in the registry contract, not an oversight here — see
        `docs/adr/candidates/`.
        """
        return Ontology(
            version=descriptor.ontology_version or "unversioned",
            entity_types=frozenset(descriptor.node_types),
            relation_types=frozenset(descriptor.edge_types),
        )

    def declares_entity_type(self, term: str) -> bool:
        return not self.entity_types or term in self.entity_types

    def declares_relation_type(self, term: str) -> bool:
        return not self.relation_types or term in self.relation_types

    def declares_attribute(self, term: str) -> bool:
        return not self.attributes or term in self.attributes


class OntologyCoverage(BaseModel):
    """What terms an ingest actually used, against what the graph declares.

    Every count is over *candidates built*, not records read: a record that
    fails validation never reaches a term, so counting it would overstate
    coverage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    declared: bool = False
    """False when the run had no ontology to check against. Distinguishes
    "everything is known" from "nothing was checkable" — they are not the
    same result and must not report the same number."""

    ontology_version: str | None = None

    declared_entity_types: tuple[str, ...] = ()
    declared_relation_types: tuple[str, ...] = ()
    declared_attributes: tuple[str, ...] = ()
    """What the graph's vocabulary actually is. Held explicitly rather than
    reconstructed from the used/unknown/unused fields: an *unconstrained*
    term set (declared nothing) and a *fully covered* one (declared and used
    everything) look identical from those, and collapsing them made an empty
    ontology report 100% coverage — precisely the reassuring lie ADR-0009
    exists to prevent."""

    entity_types: dict[str, int] = Field(default_factory=dict)
    relation_types: dict[str, int] = Field(default_factory=dict)
    attributes: dict[str, int] = Field(default_factory=dict)
    unknown_entity_types: tuple[str, ...] = ()
    unknown_relation_types: tuple[str, ...] = ()
    unknown_attributes: tuple[str, ...] = ()
    unused_entity_types: tuple[str, ...] = ()
    unused_relation_types: tuple[str, ...] = ()

    @property
    def has_unknown_terms(self) -> bool:
        return bool(
            self.unknown_entity_types or self.unknown_relation_types or self.unknown_attributes
        )

    @property
    def coverage_ratio(self) -> float | None:
        """Fraction of the graph's *declared* terms this run actually produced.

        `None` when there is nothing to measure — either no ontology was
        supplied, or the ontology declares no terms at all. Both are honest
        nulls (ADR-0009): "nothing was checkable" is not the same result as
        "everything was covered", and reporting `1.0` for either would be a
        lie an operator would act on.

        Unknown terms cannot inflate this: only *declared* terms count toward
        the numerator, so producing a thousand junk types still covers zero.
        """
        if not self.declared:
            return None
        declared = (
            set(self.declared_entity_types)
            | set(self.declared_relation_types)
            | set(self.declared_attributes)
        )
        if not declared:
            return None
        used = set(self.entity_types) | set(self.relation_types) | set(self.attributes)
        return len(declared & used) / len(declared)


class CoverageCounter:
    """Accumulates term usage across an ingest run, then summarizes it.

    Mutable by design (like `IngestReport`, the spec's one sanctioned
    accumulator): it is fed one candidate at a time as the pipeline builds
    them, and frozen into an `OntologyCoverage` at the end.
    """

    def __init__(self) -> None:
        self._entity_types: Counter[str] = Counter()
        self._relation_types: Counter[str] = Counter()
        self._attributes: Counter[str] = Counter()

    def observe(self, candidate: Candidate) -> None:
        """Tally whatever ontology term this candidate uses, if any.

        The five spec-level candidate kinds (observation, plan, ...) carry no
        ontology term that v1 checks, so they are counted nowhere here rather
        than being forced into a bucket they do not belong in.
        """
        if isinstance(candidate, EntityCandidate):
            self._entity_types[candidate.entity_type] += 1
        elif isinstance(candidate, RelationCandidate):
            self._relation_types[candidate.relation_type] += 1
        elif isinstance(candidate, AttributeAssertionCandidate):
            self._attributes[candidate.attribute] += 1

    def summarize(self, ontology: Ontology | None) -> OntologyCoverage:
        if ontology is None:
            return OntologyCoverage(
                declared=False,
                entity_types=dict(sorted(self._entity_types.items())),
                relation_types=dict(sorted(self._relation_types.items())),
                attributes=dict(sorted(self._attributes.items())),
            )

        return OntologyCoverage(
            declared=True,
            ontology_version=ontology.version,
            declared_entity_types=tuple(sorted(ontology.entity_types)),
            declared_relation_types=tuple(sorted(ontology.relation_types)),
            declared_attributes=tuple(sorted(ontology.attributes)),
            entity_types=dict(sorted(self._entity_types.items())),
            relation_types=dict(sorted(self._relation_types.items())),
            attributes=dict(sorted(self._attributes.items())),
            unknown_entity_types=_unknown(self._entity_types, ontology.entity_types),
            unknown_relation_types=_unknown(self._relation_types, ontology.relation_types),
            unknown_attributes=_unknown(self._attributes, ontology.attributes),
            unused_entity_types=_unused(self._entity_types, ontology.entity_types),
            unused_relation_types=_unused(self._relation_types, ontology.relation_types),
        )


def _unknown(used: Counter[str], declared: frozenset[str]) -> tuple[str, ...]:
    """Terms the data used that the graph never declared. Sorted, for determinism."""
    if not declared:
        return ()
    return tuple(sorted(term for term in used if term not in declared))


def _unused(used: Counter[str], declared: frozenset[str]) -> tuple[str, ...]:
    """Terms the graph declared that the data never produced."""
    return tuple(sorted(term for term in declared if term not in used))
