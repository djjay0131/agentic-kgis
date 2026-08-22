"""Synthetic arm outputs for the kg_eval fixture-driven tests.

Three arms are hand-built against `fixtures/baseball_gold.json` so every metric
has a known-correct expected value:

- `perfect_arm` — every gold entity/relation/attribute, each with PRESENT
  supporting evidence that covers the gold span. P = R = F1 = 1.0.
- `lossy_arm` — a correct subset (6 of 10 entities): no false positives, so
  precision 1.0 but recall 0.6.
- `hallucinating_arm` — every gold item plus three invented entities with no
  evidence: recall 1.0 but false positives and unsupported assertions.

Candidates are constructed straight from `kg_contracts` models (not the
contract factories, which do not expose `evidence_refs`) so the evidence-
validity metrics have real citations to resolve.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    CandidateScores,
    EntityCandidate,
    RelationCandidate,
    SourceCoordinates,
)
from kg_contracts.evidence import (
    Evidence,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    present_evidence,
)
from kg_contracts.identity import EntityRef
from kg_eval.arms import ArmConfig, ArmOutput, CostLatency

NOW = datetime(2026, 7, 12, tzinfo=UTC)
_SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.9)
_PROV = Provenance(source="roster", actor="loader")


def _coords(locator: str) -> SourceCoordinates:
    return SourceCoordinates(source_type="csv", locator=locator)


def _evidence(evidence_id: str, locator: str, content: str) -> Evidence:
    return present_evidence(
        evidence_id=evidence_id,
        source_type="csv",
        source_locator=locator,
        observed_at=NOW,
        provenance=_PROV,
        content=content,
    )


def entity(
    i: int,
    *,
    with_evidence: bool = True,
    covers: bool = True,
) -> tuple[EntityCandidate, dict[str, Evidence]]:
    """A Player entity candidate for player i, plus its evidence store slice."""
    key = f"p{i}"
    ref = EntityRef(entity_type="Player", namespace="usssa", key=key)
    store: dict[str, Evidence] = {}
    refs: tuple[EvidenceRef, ...] = ()
    if with_evidence:
        eid = f"ev-entity-{key}"
        content = f"Player {i}" if covers else "unrelated text"
        store[eid] = _evidence(eid, f"roster.csv#row{i}", content)
        refs = (EvidenceRef(evidence_id=eid, relationship=EvidenceRelationship.SUPPORTS),)
    cand = EntityCandidate(
        graph_id="baseball",
        producer="test",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=_coords(f"roster.csv#row{i}"),
        semantic_key=f"player/{key}",
        scores=_SCORES,
        entity_type="Player",
        aliases=(ref,),
        evidence_refs=refs,
    )
    return cand, store


def relation(subject_key: str, team_key: str) -> tuple[RelationCandidate, dict[str, Evidence]]:
    eid = f"ev-rel-{subject_key}-{team_key}"
    store = {eid: _evidence(eid, f"games.csv#{subject_key}", "played")}
    cand = RelationCandidate(
        graph_id="baseball",
        producer="test",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=_coords(f"games.csv#{subject_key}"),
        semantic_key=f"plays_for/{subject_key}/{team_key}",
        scores=_SCORES,
        relation_type="PLAYS_FOR",
        subject=EntityRef(entity_type="Player", namespace="usssa", key=subject_key),
        object=EntityRef(entity_type="Team", namespace="usssa", key=team_key),
        evidence_refs=(EvidenceRef(evidence_id=eid, relationship=EvidenceRelationship.SUPPORTS),),
    )
    return cand, store


def attribute(
    subject_key: str, attr: str, value: object
) -> tuple[AttributeAssertionCandidate, dict[str, Evidence]]:
    eid = f"ev-attr-{subject_key}-{attr}"
    store = {eid: _evidence(eid, f"stats.csv#{subject_key}", "stat")}
    cand = AttributeAssertionCandidate(
        graph_id="baseball",
        producer="test",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=_coords(f"stats.csv#{subject_key}"),
        semantic_key=f"{subject_key}/{attr}",
        scores=_SCORES,
        subject=EntityRef(entity_type="Player", namespace="usssa", key=subject_key),
        attribute=attr,
        value=value,
        evidence_refs=(EvidenceRef(evidence_id=eid, relationship=EvidenceRelationship.SUPPORTS),),
    )
    return cand, store


_RELATIONS = [("p1", "t1"), ("p2", "t1"), ("p3", "t2"), ("p4", "t2")]
_ATTRS: list[tuple[str, str, object]] = [
    ("p1", "height_cm", 180),
    ("p2", "height_cm", 175),
    ("p3", "bats", "R"),
    ("p4", "throws", "L"),
]


def _assemble(
    arm: ArmConfig,
    parts: list[tuple[Candidate, dict[str, Evidence]]],
    *,
    abstained: int = 0,
    failed: int = 0,
    cost: CostLatency | None = None,
) -> ArmOutput:
    candidates: list[Candidate] = []
    store: dict[str, Evidence] = {}
    for cand, slice_ in parts:
        candidates.append(cand)
        store.update(slice_)
    return ArmOutput(
        arm=arm,
        candidates=tuple(candidates),
        evidence=store,
        attempted=10,
        abstained=abstained,
        failed=failed,
        cost=cost,
    )


def perfect_arm() -> ArmOutput:
    parts: list[tuple[Candidate, dict[str, Evidence]]] = [entity(i) for i in range(1, 11)]
    parts += [relation(s, t) for s, t in _RELATIONS]
    parts += [attribute(s, a, v) for s, a, v in _ATTRS]
    return _assemble(
        ArmConfig(arm_id="rules+llm", description="perfect", config={"llm": True}),
        parts,
        cost=CostLatency(latency_seconds=2.0, cost_usd=0.05, tokens=1000),
    )


def lossy_arm() -> ArmOutput:
    parts: list[tuple[Candidate, dict[str, Evidence]]] = [entity(i) for i in range(1, 7)]
    parts += [relation("p1", "t1"), relation("p2", "t1")]
    parts += [attribute("p1", "height_cm", 180), attribute("p2", "height_cm", 175)]
    return _assemble(
        ArmConfig(arm_id="rules-only", description="lossy baseline", config={"llm": False}),
        parts,
        abstained=2,
        failed=1,
        cost=CostLatency(latency_seconds=0.5, cost_usd=0.0, tokens=0),
    )


def subset_arm(arm_id: str, n_entities: int, *, cost: CostLatency | None = None) -> ArmOutput:
    """An arm that correctly recovers the first `n_entities` players, nothing else.

    No false positives, no cost by default — used to build clean ablation pairs
    where the only moving part is recall, so an IMPROVEMENT verdict is not
    confounded by a guardrail regression.
    """
    parts: list[tuple[Candidate, dict[str, Evidence]]] = [
        entity(i) for i in range(1, n_entities + 1)
    ]
    return _assemble(ArmConfig(arm_id=arm_id, config={"n": n_entities}), parts, cost=cost)


def hallucinating_arm() -> ArmOutput:
    parts: list[tuple[Candidate, dict[str, Evidence]]] = [entity(i) for i in range(1, 11)]
    # three invented players with no evidence at all -> false positives + unsupported
    parts += [entity(i, with_evidence=False) for i in (90, 91, 92)]
    parts += [relation(s, t) for s, t in _RELATIONS]
    parts += [attribute(s, a, v) for s, a, v in _ATTRS]
    return _assemble(
        ArmConfig(arm_id="llm-only", description="hallucinating", config={"llm": True}),
        parts,
        cost=CostLatency(latency_seconds=3.0, cost_usd=0.10, tokens=2000),
    )
