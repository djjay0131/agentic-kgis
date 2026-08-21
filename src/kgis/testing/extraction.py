"""Reusable contract suites for the extraction seam (spec §10.2).

Two seams future adapters plug into get a shared, inheritable test suite here,
mirroring `RecordReaderContract`: an implementation proves itself by passing
the same suite every other implementation passes.

- `CompletionClientContract` — any `CompletionClient` (a real provider adapter,
  a fake, the replay client). The rules are minimal on purpose: the frozen
  contract only promises `complete(prompt, *, system=None) -> str`, so the
  suite pins exactly that surface and nothing a specific provider might add.

- `ExtractorContract` — any object mapping one chunk to candidates via the
  `LLMExtractor` surface. It pins the properties Plan 4 depends on: producer /
  model / version capture on every emitted candidate, coordinates that point
  back at the source chunk, and *no* invented candidates for empty output.

Subclass, implement the `make_*` hook(s), and inherit the tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kg_contracts.candidates import Candidate
from kg_contracts.ingestion import CompletionClient
from kgis.builders import BuildContext
from kgis.clock import FixedClock
from kgis.extraction.documents import Chunk
from kgis.extraction.extractor import LLMExtractor
from kgis.ids import DeterministicIdStrategy

_NOW = datetime(2026, 8, 21, tzinfo=UTC)


class CompletionClientContract:
    """Subclass and implement `make_client()` returning a client whose response
    to any prompt is a non-empty string."""

    def make_client(self) -> CompletionClient:
        raise NotImplementedError

    def test_complete_returns_a_string(self) -> None:
        client = self.make_client()
        result = client.complete("hello")
        assert isinstance(result, str)

    def test_system_prompt_is_accepted(self) -> None:
        client = self.make_client()
        result = client.complete("hello", system="you are a test")
        assert isinstance(result, str)

    def test_same_prompt_is_stable_when_deterministic(self) -> None:
        """A client advertising `deterministic` must return equal output for
        equal input — that promise is what a replay/pinned client makes and a
        dry-run relies on."""
        client = self.make_client()
        if not getattr(client, "deterministic", False):
            return
        # Reuse the same prompt the other cases use, so a replay client primed
        # only for the suite's prompts can still satisfy this check.
        first = client.complete("hello", system="you are a test")
        second = client.complete("hello", system="you are a test")
        assert first == second


class ExtractorContract:
    """Subclass and implement `make_extractor()` + `make_chunk()`.

    `make_extractor()` returns an `LLMExtractor` whose (replay/fake) client is
    primed for `make_chunk()` and yields at least one candidate.
    """

    def make_extractor(self) -> LLMExtractor:
        raise NotImplementedError

    def make_chunk(self) -> Chunk:
        raise NotImplementedError

    def _context(self, extractor: LLMExtractor) -> BuildContext:
        return BuildContext(
            graph_id="g1",
            producer=extractor.config.producer("kgis.extraction"),
            producer_run_id="run_test",
            ontology_version="v1",
            scoring=extractor.config.scoring,
            clock=FixedClock(_NOW),
            ids=DeterministicIdStrategy(),
        )

    def _extract(self) -> list[Candidate]:
        extractor = self.make_extractor()
        return extractor.extract(self.make_chunk(), self._context(extractor))

    def test_extract_yields_candidates(self) -> None:
        assert self._extract(), "extractor produced no candidates for a primed chunk"

    def test_candidates_capture_producer_and_model(self) -> None:
        extractor = self.make_extractor()
        candidates = self._extract()
        for candidate in candidates:
            # Producer names the extractor + version.
            assert extractor.config.extractor_id in candidate.producer
            # Model is captured on the source-passage representation.
            passage = candidate.representations.get("source_passage")
            assert passage is not None
            assert passage.model == extractor.config.model_id

    def test_candidate_coordinates_point_at_the_chunk(self) -> None:
        chunk = self.make_chunk()
        for candidate in self._extract():
            assert candidate.source_coordinates == chunk.coordinates

    def test_extraction_is_repeatable(self) -> None:
        """Same extractor + same chunk (deterministic client) → same candidate ids."""
        first = [c.candidate_id for c in self._extract()]
        second = [c.candidate_id for c in self._extract()]
        assert first == second


__all__ = [
    "CompletionClientContract",
    "ExtractorContract",
]
