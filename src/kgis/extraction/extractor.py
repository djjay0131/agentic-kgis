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
  names its model.
- **Model/extractor provenance on the envelope.** `model_id`, `model_version`,
  `extractor_version`, and `prompt_version` are stamped onto the candidate from
  its `ExtractorConfig` (ADR-0023), so a consumer holding only the candidate can
  answer "which model version produced this?" without a registry round-trip.

Malformed model output and un-buildable rows raise (`ExtractionParseError`,
`RecordDataError`, pydantic `ValidationError`); the runner catches them per
(extractor, chunk) so a failure is isolated and reported, never fatal.
"""

from __future__ import annotations

from dataclasses import dataclass

from kg_contracts.candidates import Candidate, CandidateScores, Representation
from kg_contracts.evidence import Evidence, TextSpan
from kg_contracts.ingestion import CompletionClient
from kgis.builders import BuildContext
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import Chunk
from kgis.extraction.parse import ExtractedItem
from kgis.extraction.provenance import build_quote_evidence, quote_evidence_ref
from kgis.records import NormalizedRecord

# The inlined passage on the representation is capped for the same reason the
# evidence content is: a very long chunk should not bloat every candidate.
_MAX_PASSAGE_CHARS = 2000


@dataclass(frozen=True)
class ExtractedCandidate:
    """One emitted candidate plus any span-narrowed evidence its item verified.

    `evidence` is the per-item quote evidence (empty when the item carried no
    verified quote). The candidate already cites it via `evidence_refs`; the
    evidence objects travel alongside so the runner — the only writer to the
    registry, and the thread-safe reduce point — can persist them.
    """

    candidate: Candidate
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
    """What one (extractor, chunk) produced: candidates, evidence, and warnings.

    `warnings` are non-fatal parse notes the runner surfaces on the report (a
    dropped non-substring quote, chiefly). They are collected per chunk, not
    per candidate, so a warning is never duplicated across an item's candidates.
    """

    candidates: tuple[ExtractedCandidate, ...] = ()
    warnings: tuple[str, ...] = ()



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
        confidence, but the runner attaches the *chunk* evidence ref once it has
        written that evidence; a verified per-item quote is already attached
        here (see `extract_result`). Kept as the plain-candidate surface the
        published `ExtractorContract` and downstream callers use.
        """
        return [item.candidate for item in self.extract_result(chunk, context).candidates]

    def extract_result(self, chunk: Chunk, context: BuildContext) -> ExtractionResult:
        """Full extraction result: candidates, per-item span evidence, warnings.

        This is the runner's entry point. It is `extract()` plus the
        span-narrowed evidence each verified quote produces and the parse
        warnings collected per chunk.
        """
        system, prompt = self._config.render(chunk.text)
        raw = self._client.complete(prompt, system=system)
        items = self._config.parser.parse(
            raw, chunk_text=chunk.text, chunk_start=chunk.start
        )

        candidates: list[ExtractedCandidate] = []
        warnings: list[str] = []
        for position, item in enumerate(items):
            warnings.extend(item.warnings)
            record = NormalizedRecord(
                index=position,
                coordinates=chunk.coordinates,
                values=item.values,
            )
            for built in self._config.builder.build(record, context):
                candidates.append(self._finalize(built, item, chunk, context))
        return ExtractionResult(candidates=tuple(candidates), warnings=tuple(warnings))

    def _finalize(
        self, candidate: Candidate, item: ExtractedItem, chunk: Chunk, context: BuildContext
    ) -> ExtractedCandidate:
        """Overlay model-reported confidence, the source-passage representation,
        the extractor/model provenance block (ADR-0023), and — when the item
        carries a parser-verified quote — the span-narrowed evidence citation."""
        scores = candidate.scores
        if item.confidence is not None:
            scores = self._with_extraction_confidence(scores, item.confidence)

        representations = dict(candidate.representations)
        representations["source_passage"] = Representation(
            kind="text",
            text=chunk.text[:_MAX_PASSAGE_CHARS],
            model=self._config.model_id,
        )
        finalized = candidate.model_copy(
            update={
                "scores": scores,
                "representations": representations,
                "model_id": self._config.model_id,
                "model_version": self._config.model_version,
                "extractor_version": self._config.extractor_version,
                "prompt_version": self._config.prompt_version,
            }
        )

        span = self._verified_span(item)
        if span is None:
            return ExtractedCandidate(candidate=finalized)
        evidence = build_quote_evidence(
            chunk, self._config, span=span, observed_at=context.clock.now()
        )
        ref = quote_evidence_ref(chunk, self._config, span=span)
        cited = finalized.model_copy(
            update={"evidence_refs": (*finalized.evidence_refs, ref)}
        )
        return ExtractedCandidate(candidate=cited, evidence=(evidence,))

    @staticmethod
    def _verified_span(item: ExtractedItem) -> TextSpan | None:
        """The item's verified quote as a document span, or `None` if it has none."""
        if item.quote is None or item.quote_start is None or item.quote_end is None:
            return None
        return TextSpan(start=item.quote_start, end=item.quote_end, quote=item.quote)

    @staticmethod
    def _with_extraction_confidence(
        scores: CandidateScores, confidence: float
    ) -> CandidateScores:
        return scores.model_copy(update={"extraction_confidence": confidence})
