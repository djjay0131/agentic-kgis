"""Per-entity-type extractor configuration: an extractor is *data, not code*.

Spec §6, decision 1: "an extractor = (entity schema, prompt template, model
config) registered per graph." An `ExtractorConfig` is exactly that tuple. It
names one target (usually one entity type), a prompt/template, a model
identifier and its versions, the policy/scoring metadata the candidates it
produces will carry, and — the piece that lets extraction reuse the whole
structured pipeline — a `CandidateBuilder` that maps each parsed item onto the
correct `Candidate` variant. The same `EntityCandidateBuilder` /
`RelationCandidateBuilder` / `AttributeCandidateBuilder` that serve structured
sync serve extraction; the LLM only supplies the rows they build from.

`scoring.source_reliability` is required (no default), for the same reason it
is on `SourceScoring`: how trustworthy a document is has nothing to do with
how confidently a model read it, and a default would let that distinction
quietly evaporate (ADR-0004). Model-reported *extraction* confidence, when the
model supplies it per item, overrides the config default on the candidate's
own `extraction_confidence` axis (see `extractor.py`).

Versions are captured explicitly (`model_id`, `model_version`,
`extractor_version`, `prompt_version`) because re-extraction identity and
audit both depend on knowing *which* extractor and *which* model produced a
candidate. Where those land on the emitted candidate is discussed in
`extractor.py` and the ADR candidate filed alongside this stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kgis.builders import CandidateBuilder, SourceScoring
from kgis.extraction.parse import JsonItemsParser, OutputParser

_DEFAULT_PARSER: OutputParser = JsonItemsParser()


@dataclass(frozen=True)
class ExtractorConfig:
    """One configured extractor: schema + prompt + model + policy metadata.

    A frozen dataclass rather than a pydantic model because it holds injected
    behavior (`builder`, `parser`) that is defined by Protocol, not by a
    validatable schema — the same reason `BuildContext` is a dataclass.
    """

    extractor_id: str
    target_type: str
    """The entity/relation type this extractor targets — one type per
    extractor (spec §6): baseball-ai's player/skill/drill extractors."""

    builder: CandidateBuilder
    """Maps each parsed `ExtractedItem` onto a `Candidate` variant. Reused
    verbatim from the structured pipeline — extraction invents no builders."""

    prompt_template: str
    """The user-prompt template. `{text}` is substituted with the chunk text."""

    model_id: str
    scoring: SourceScoring
    system_prompt: str | None = None
    model_version: str = "unversioned"
    extractor_version: str = "unversioned"
    prompt_version: str = "unversioned"
    parser: OutputParser = field(default=_DEFAULT_PARSER)

    def render(self, chunk_text: str) -> tuple[str | None, str]:
        """Produce `(system, prompt)` for one chunk.

        Substitution is `str.replace`, not `str.format`, so a chunk that
        happens to contain literal braces cannot raise or be misinterpreted as
        a format field.
        """
        prompt = self.prompt_template.replace("{text}", chunk_text)
        return self.system_prompt, prompt

    def producer(self, base: str) -> str:
        """The `producer` string stamped on this extractor's candidates.

        Encodes the extractor id and version alongside the base producer
        (`kgis.extraction:player@2`) so the candidate itself names which
        extractor made it — the envelope has no dedicated field for it (see
        the ADR candidate)."""
        return f"{base}:{self.extractor_id}@{self.extractor_version}"
