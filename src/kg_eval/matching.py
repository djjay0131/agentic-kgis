"""Reducing candidates and gold items to comparable match keys.

Grading is a set comparison, and this module is what makes that honest: it
reduces both a produced `Candidate` and a `Gold*` item to the *same* tuple key,
so a true positive is literal key equality rather than a similarity threshold
someone could tune to flatter an arm. Entities key on `(entity_type,
semantic_key)`; relations on `(relation_type, subject, object)`; attributes on
`(subject, attribute, normalized-value)`.

Endpoints (`SubjectRef`) are canonicalized identically on both sides
(`canon_ref`): a namespaced `EntityRef` renders to `Type:namespace:key`, a bare
identity-id string passes through. Values are normalized (`norm_value`) so that
`200` and `"200"` grade equal — the gold set should not have to guess the exact
Python type a producer chose.

A `CategoryMatch` carries not just the TP/FP/FN counts but the per-item
outcomes (`gold_hits`, ordered by gold item; `candidate_hits`, ordered by
candidate), which is exactly the per-unit signal the bootstrap resamples over.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    EntityCandidate,
    RelationCandidate,
    SubjectRef,
)
from kg_contracts.identity import EntityRef
from kg_eval.goldset import GoldAttribute, GoldEntity, GoldRelation, GoldSet

MatchKey = tuple[str, ...]


def canon_ref(ref: SubjectRef) -> str:
    """Canonical string for a relation/attribute endpoint.

    An `EntityRef` renders to `Type:namespace:key`; a bare identity-id string
    passes through unchanged. Both sides of grading go through this, so a gold
    endpoint string and a candidate endpoint compare as equals.
    """
    if isinstance(ref, EntityRef):
        return ref.render()
    return ref


def norm_value(value: object) -> str:
    """Stable string normalization of an attribute value.

    JSON with sorted keys for containers, `repr`-free scalars otherwise, so
    `200` and `"200"` collapse to the same key and dict ordering never matters.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return str(value)


def entity_key_candidate(c: EntityCandidate) -> MatchKey:
    return ("entity", c.entity_type, c.semantic_key)


def entity_key_gold(g: GoldEntity) -> MatchKey:
    return ("entity", g.entity_type, g.semantic_key)


def relation_key_candidate(c: RelationCandidate) -> MatchKey:
    return ("relation", c.relation_type, canon_ref(c.subject), canon_ref(c.object))


def relation_key_gold(g: GoldRelation) -> MatchKey:
    return ("relation", g.relation_type, g.subject, g.object)


def attribute_key_candidate(c: AttributeAssertionCandidate) -> MatchKey:
    return ("attribute", canon_ref(c.subject), c.attribute, norm_value(c.value))


def attribute_key_gold(g: GoldAttribute) -> MatchKey:
    return ("attribute", g.subject, g.attribute, norm_value(g.value))


class CategoryMatch(BaseModel):
    """The outcome of matching one candidate category against its gold slice.

    `gold_hits[i]` is 1.0 iff gold item i was produced (the per-item recall
    signal); `candidate_hits[j]` is 1.0 iff candidate j matched a gold item
    (the per-item precision signal). `tp/fp/fn` are the aggregate counts, and
    `matched_gold_indices[j]` maps each *matched* candidate back to the gold
    item it hit (used to look up the expected evidence span).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tp: int
    fp: int
    fn: int
    gold_hits: tuple[float, ...]
    candidate_hits: tuple[float, ...]
    matched_gold_indices: tuple[int | None, ...]


def _match(gold_keys: list[MatchKey], candidate_keys: list[MatchKey]) -> CategoryMatch:
    """Set-compare two key lists into a `CategoryMatch` with per-item signals.

    A gold key present in the candidate multiset counts once; duplicate
    candidates for the same key are false positives after the first. This makes
    precision sensitive to an arm that pads output with repeats.
    """
    gold_index: dict[MatchKey, int] = {}
    for i, key in enumerate(gold_keys):
        gold_index.setdefault(key, i)

    gold_hits = [0.0] * len(gold_keys)
    candidate_hits: list[float] = []
    matched_indices: list[int | None] = []
    consumed: set[int] = set()

    for key in candidate_keys:
        gi = gold_index.get(key)
        if gi is not None and gi not in consumed:
            consumed.add(gi)
            gold_hits[gi] = 1.0
            candidate_hits.append(1.0)
            matched_indices.append(gi)
        else:
            candidate_hits.append(0.0)
            matched_indices.append(None)

    tp = len(consumed)
    fp = len(candidate_keys) - tp
    fn = len(gold_keys) - tp
    return CategoryMatch(
        tp=tp,
        fp=fp,
        fn=fn,
        gold_hits=tuple(gold_hits),
        candidate_hits=tuple(candidate_hits),
        matched_gold_indices=tuple(matched_indices),
    )


def _entities(candidates: tuple[Candidate, ...]) -> list[EntityCandidate]:
    return [c for c in candidates if isinstance(c, EntityCandidate)]


def _relations(candidates: tuple[Candidate, ...]) -> list[RelationCandidate]:
    return [c for c in candidates if isinstance(c, RelationCandidate)]


def _attributes(candidates: tuple[Candidate, ...]) -> list[AttributeAssertionCandidate]:
    return [c for c in candidates if isinstance(c, AttributeAssertionCandidate)]


def match_entities(candidates: tuple[Candidate, ...], gold: GoldSet) -> CategoryMatch:
    cands = _entities(candidates)
    return _match(
        [entity_key_gold(g) for g in gold.entities],
        [entity_key_candidate(c) for c in cands],
    )


def match_relations(candidates: tuple[Candidate, ...], gold: GoldSet) -> CategoryMatch:
    cands = _relations(candidates)
    return _match(
        [relation_key_gold(g) for g in gold.relations],
        [relation_key_candidate(c) for c in cands],
    )


def match_attributes(candidates: tuple[Candidate, ...], gold: GoldSet) -> CategoryMatch:
    cands = _attributes(candidates)
    return _match(
        [attribute_key_gold(g) for g in gold.attributes],
        [attribute_key_candidate(c) for c in cands],
    )
