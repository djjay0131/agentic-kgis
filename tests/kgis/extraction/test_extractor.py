"""`LLMExtractor`: build via reused builders, capture producer/model/confidence."""

from __future__ import annotations

from kgis.builders import BuildContext
from kgis.clock import FixedClock
from kgis.extraction.documents import Chunk, ParagraphChunker
from kgis.extraction.extractor import LLMExtractor
from kgis.ids import DeterministicIdStrategy
from kgis.testing.extraction import ExtractorContract

from .support import NOW, SAMPLE_DOC, ScriptedModel, player_and_skill_script, player_config


def _context(config_producer: str, scoring: object) -> BuildContext:
    from kgis.builders import SourceScoring

    assert isinstance(scoring, SourceScoring)
    return BuildContext(
        graph_id="g1",
        producer=config_producer,
        producer_run_id="run_x",
        ontology_version="v1",
        scoring=scoring,
        clock=FixedClock(NOW),
        ids=DeterministicIdStrategy(),
    )


def _player_chunk() -> Chunk:
    return ParagraphChunker().chunk(SAMPLE_DOC)[0]  # the "Ada ... hitting" paragraph


class TestPlayerExtractorContract(ExtractorContract):
    def make_extractor(self) -> LLMExtractor:
        config = player_config()
        return LLMExtractor(config, ScriptedModel(player_and_skill_script()))

    def make_chunk(self) -> Chunk:
        return _player_chunk()


def test_extractor_reuses_builder_to_produce_entity_candidate() -> None:
    config = player_config()
    extractor = LLMExtractor(config, ScriptedModel(player_and_skill_script()))
    candidates = extractor.extract(_player_chunk(), _context(config.producer("kgis.extraction"), config.scoring))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.candidate_kind == "entity"
    assert candidate.semantic_key == "player/baseball/ada"


def test_model_reported_confidence_overrides_extraction_confidence_only() -> None:
    config = player_config()  # config default extraction_confidence=0.5, source_reliability=0.7
    extractor = LLMExtractor(config, ScriptedModel(player_and_skill_script()))
    candidate = extractor.extract(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )[0]
    # The item reported confidence 0.91 -> extraction_confidence overridden.
    assert candidate.scores.extraction_confidence == 0.91
    # source_reliability is the source's axis, untouched by the model's certainty.
    assert candidate.scores.source_reliability == 0.7


def test_producer_encodes_extractor_and_version() -> None:
    config = player_config(extractor_version="7")
    extractor = LLMExtractor(config, ScriptedModel(player_and_skill_script()))
    candidate = extractor.extract(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )[0]
    assert candidate.producer == "kgis.extraction:player@7"


def test_source_passage_representation_carries_model_and_text() -> None:
    config = player_config(model_id="claude-fake")
    extractor = LLMExtractor(config, ScriptedModel(player_and_skill_script()))
    candidate = extractor.extract(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )[0]
    passage = candidate.representations["source_passage"]
    assert passage.model == "claude-fake"
    assert "Ada" in (passage.text or "")


def test_empty_model_output_yields_no_candidates() -> None:
    config = player_config()
    # Script has no entry matching this chunk's marker -> default empty items.
    extractor = LLMExtractor(config, ScriptedModel({}))
    candidates = extractor.extract(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )
    assert candidates == []
