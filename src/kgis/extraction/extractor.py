"""`LLMExtractor`: one chunk → typed candidates, via prompt + parse + build.

This is where the model meets the shared pipeline. `extract()` renders the
config's prompt for a chunk, asks the injected `CompletionClient`, parses the
response into `ExtractedItem`s, and hands each item's fields to the config's
`CandidateBuilder` as a `NormalizedRecord`. Reusing the structured builders is
deliberate: entity/relation/attribute construction, semantic keys, and
contract validation already live there and must not be reinvented for the LLM
path — the only new thing extraction adds is *where the row came from*.

Two finalizing touches turn a builder's structured candidate into an
extraction candidate:

- **Model-reported extraction confidence.** When an item reports its own
  confidence, it overrides the config default on the candidate's
  `extraction_confidence` axis — and *only* that axis. `source_reliability`
  stays what the config declared: the model's certainty about reading the
  passage says nothing about whether the passage's source is trustworthy
  (ADR-0004).
- **The passage as a representation.** A `source_passage` text representation
  carries the chunk text and the `model` that read it, so the candidate itself
  names its model — the envelope has no dedicated model field.

Malformed model output and un-buildable rows raise (`ExtractionParseError`,
`RecordDataError`, pydantic `ValidationError`); the runner catches them per
(extractor, chunk) so a failure is isolated and reported, never fatal.
"""

from __future__ import annotations

from kg_contracts.candidates import Candidate, CandidateScores, Representation
from kg_contracts.ingestion import CompletionClient
from kgis.builders import BuildContext
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import Chunk
from kgis.extraction.parse import ExtractedItem
from kgis.records import NormalizedRecord

# The inlined passage on the representation is capped for the same reason the
# evidence content is: a very long chunk should not bloat every candidate.
_MAX_PASSAGE_CHARS = 2000


class LLMExtractor:
    """Runs one configured extractor over chunks (spec §6).

    Stateless across chunks and reusable across runs: the run-specific facts
    (graph id, clock, ids, run id) arrive per call on the `BuildContext`, so
    one configured extractor can serve any run.
    """

    def __init__(self, config: ExtractorConfig, client: CompletionClient) -> None:
        self._config = config
        self._client = client

    @property
    def name(self) -> str:
        return self._config.extractor_id

    @property
    def config(self) -> ExtractorConfig:
        return self._config

    def extract(self, chunk: Chunk, context: BuildContext) -> list[Candidate]:
        """Prompt → parse → build for one chunk. May raise on malformed output.

        The candidates returned carry producer/model/version and model-reported
        confidence, but *not* evidence refs — the runner attaches those once it
        has written the passage evidence to the registry.
        """
        system, prompt = self._config.render(chunk.text)
        raw = self._client.complete(prompt, system=system)
        items = self._config.parser.parse(raw)

        candidates: list[Candidate] = []
        for position, item in enumerate(items):
            record = NormalizedRecord(
                index=position,
                coordinates=chunk.coordinates,
                values=item.values,
            )
            for built in self._config.builder.build(record, context):
                candidates.append(self._finalize(built, item, chunk))
        return candidates

    def _finalize(self, candidate: Candidate, item: ExtractedItem, chunk: Chunk) -> Candidate:
        """Overlay model-reported confidence and the source-passage representation."""
        scores = candidate.scores
        if item.confidence is not None:
            scores = self._with_extraction_confidence(scores, item.confidence)

        representations = dict(candidate.representations)
        representations["source_passage"] = Representation(
            kind="text",
            text=chunk.text[:_MAX_PASSAGE_CHARS],
            model=self._config.model_id,
        )
        return candidate.model_copy(
            update={"scores": scores, "representations": representations}
        )

    @staticmethod
    def _with_extraction_confidence(
        scores: CandidateScores, confidence: float
    ) -> CandidateScores:
        return scores.model_copy(update={"extraction_confidence": confidence})
