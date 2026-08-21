"""Extraction gold-set representation and its JSON loader.

A gold set is the ground truth an extraction arm is graded against: the
entities, relations, and attributes a perfect run *should* have produced from a
corpus, plus, for each, the evidence span that should support it. The models
here are deliberately independent of the `Candidate` union — a gold item states
*what is true*, not *what some pipeline emitted* — but they carry exactly the
fields needed to derive the same match keys the candidates do (see
`matching.py`), so grading is a set comparison rather than fuzzy alignment.

Evidence spans (`EvidenceSpan`) are first-class: ADR-0009's evidence-span
accuracy metric is only measurable if the gold set says where the support was
supposed to come from. A span names a `source_locator` and, optionally, a
`quote` (and character offsets) the supporting evidence must actually cover.

Gold sets load from plain JSON fixtures (`GoldSet.from_json` /
`from_json_file`) so labeling is a data-editing task, not a code-editing one,
and so the golden-set line item of the adoption plan (ADR-0009, Phase 1) has a
stable on-disk format.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

GoldKey = tuple[str, ...]


def norm_value(value: object) -> str:
    """Stable string normalization of an attribute value.

    JSON with sorted keys for containers, the raw string for strings, so that
    `200` and `"200"` collapse to the same key and dict ordering never matters.
    Lives here (not in `matching`) so both a `GoldAttribute` match key and a
    candidate match key derive value identity through the exact same function.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return str(value)


class EvidenceSpan(BaseModel):
    """Where a gold item's support is supposed to live in a source.

    `source_locator` is the stable locator (mirroring `Evidence.source_locator`
    on the candidate side). `quote` is the exact text the supporting evidence
    must contain; `start`/`end` are optional character offsets into the source.
    A candidate's cited evidence "covers" this span when it resolves to PRESENT
    evidence at the same locator whose content contains the quote.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_locator: str = Field(min_length=1)
    quote: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class GoldEntity(BaseModel):
    """One entity that a perfect extraction run must produce.

    `entity_type` + `semantic_key` reproduce the candidate-side match key
    exactly, so grading needs no heuristic alignment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: str = Field(min_length=1)
    semantic_key: str = Field(min_length=1)
    display_name: str | None = None
    evidence: EvidenceSpan | None = None

    def match_key(self) -> GoldKey:
        """The grading key, identical to the candidate-side entity key."""
        return ("entity", self.entity_type, self.semantic_key)


class GoldRelation(BaseModel):
    """One relation a perfect run must produce.

    `subject`/`object` are the canonical *string* form of the endpoints
    (`Type:namespace:key` for a namespaced ref, or a bare identity id), which
    is what `matching.canon_ref` reduces a candidate endpoint to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    relation_type: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    object: str = Field(min_length=1)
    evidence: EvidenceSpan | None = None

    def match_key(self) -> GoldKey:
        """The grading key, identical to the candidate-side relation key."""
        return ("relation", self.relation_type, self.subject, self.object)


class GoldAttribute(BaseModel):
    """One attribute assertion a perfect run must produce.

    `value` is compared by stable string normalization, so `200` and `"200"`
    are graded as the same value (see `matching.norm_value`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: Any
    evidence: EvidenceSpan | None = None

    def match_key(self) -> GoldKey:
        """The grading key, identical to the candidate-side attribute key."""
        return ("attribute", self.subject, self.attribute, norm_value(self.value))


class GoldSet(BaseModel):
    """A named, hashable ground-truth set for one extraction corpus.

    `gold_set_id` names it; `content_hash` is a stable digest of the labeled
    content (never the id or description) so a report can prove two arms were
    graded against the *same* truth. `attempted` is the number of source inputs
    the corpus contains, used as the denominator for abstention/failure rates
    when an arm reports how many inputs it processed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold_set_id: str = Field(min_length=1)
    description: str | None = None
    attempted: int | None = Field(default=None, ge=0)
    entities: tuple[GoldEntity, ...] = ()
    relations: tuple[GoldRelation, ...] = ()
    attributes: tuple[GoldAttribute, ...] = ()

    @model_validator(mode="after")
    def _check_unique_keys(self) -> GoldSet:
        """Reject a gold set containing two items with the same match key.

        Grading matches on a match key, and only the first item with a given
        key can ever be matched (see `matching._match`); a second item with an
        identical key is a permanent false negative that silently caps recall.
        A gold set with duplicate keys is almost certainly an authoring error,
        so it is rejected loudly at construction/load time rather than quietly
        distorting every metric computed against it.
        """
        for label, items in (
            ("entity", self.entities),
            ("relation", self.relations),
            ("attribute", self.attributes),
        ):
            seen: set[GoldKey] = set()
            for item in items:
                key = item.match_key()
                if key in seen:
                    raise ValueError(
                        f"duplicate {label} gold key {key!r}: two gold items share a "
                        "match key, which would make the second permanently unmatchable"
                    )
                seen.add(key)
        return self

    @property
    def content_hash(self) -> str:
        """A stable SHA-256 over the labeled content (excludes id/description).

        Deterministic: the JSON is dumped with sorted keys so the hash depends
        only on the labels, not on field ordering or on what the set is called.
        """
        payload = self.model_dump(
            mode="json", include={"entities", "relations", "attributes", "attempted"}
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def from_json(data: str | bytes) -> GoldSet:
        """Load a gold set from a JSON string/bytes fixture."""
        return GoldSet.model_validate_json(data)

    @staticmethod
    def from_json_file(path: str | Path) -> GoldSet:
        """Load a gold set from a JSON fixture file."""
        return GoldSet.model_validate_json(Path(path).read_bytes())
