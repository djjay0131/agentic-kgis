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


def test_candidate_carries_model_and_extractor_versions() -> None:
    config = player_config(extractor_version="7")
    extractor = LLMExtractor(config, ScriptedModel(player_and_skill_script()))
    candidate = extractor.extract(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )[0]
    # ADR-0023: the candidate self-describes its producing model and versions.
    assert candidate.model_id == "fake-model-1"
    assert candidate.model_version == "2026-08"
    assert candidate.extractor_version == "7"
    assert candidate.prompt_version == "p1"


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


def _quoted_script(quote: str) -> ScriptedModel:
    return ScriptedModel(
        {
            ("Player", "Ada"): (
                '{"items": [{"player_id": "ada", "name": "Ada", '
                f'"quote": "{quote}"' + "}]}"
            )
        }
    )


def test_extract_result_carries_span_evidence_for_a_verified_quote() -> None:
    config = player_config()
    extractor = LLMExtractor(config, _quoted_script("Ada is a shortstop"))
    result = extractor.extract_result(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )
    assert len(result.candidates) == 1
    extracted = result.candidates[0]
    assert len(extracted.evidence) == 1
    evidence = extracted.evidence[0]
    assert evidence.span is not None
    assert evidence.span.quote == "Ada is a shortstop"
    # The candidate already cites the narrowed evidence.
    cited_ids = {ref.evidence_id for ref in extracted.candidate.evidence_refs}
    assert evidence.evidence_id in cited_ids
    assert result.warnings == ()


def test_extract_result_carries_no_evidence_for_a_rejected_quote() -> None:
    config = player_config()
    extractor = LLMExtractor(config, _quoted_script("Ada is a pitcher"))
    result = extractor.extract_result(
        _player_chunk(), _context(config.producer("kgis.extraction"), config.scoring)
    )
    assert result.candidates[0].evidence == ()
    assert result.candidates[0].candidate.evidence_refs == ()
    assert any("not an exact substring" in w for w in result.warnings)


def test_repeated_quote_items_get_distinct_spans_and_evidence_ids() -> None:
    # Two items quoting the same text must not collapse onto one span (and thus
    # one evidence id); each anchors to its own occurrence in the chunk.
    config = player_config()
    text = "Ada is a shortstop. Ada is a shortstop."
    chunk = Chunk(
        doc_id="doc-quotes",
        index=0,
        start=0,
        end=len(text),
        text=text,
        source_type="scouting_report",
        locator="s3://reports/doc-quotes.txt",
    )
    response = (
        '{"items": ['
        '{"player_id": "ada", "name": "Ada", "quote": "Ada is a shortstop"}, '
        '{"player_id": "ada2", "name": "Ada2", "quote": "Ada is a shortstop"}]}'
    )
    extractor = LLMExtractor(
        config, ScriptedModel({("Player", "Ada is a shortstop"): response})
    )
    result = extractor.extract_result(
        chunk, _context(config.producer("kgis.extraction"), config.scoring)
    )

    quote_evidence = [c.evidence[0] for c in result.candidates if c.evidence]
    assert len(quote_evidence) == 2
    starts = sorted(e.span.start for e in quote_evidence if e.span is not None)
    assert starts == [0, 20]
    ids = {e.evidence_id for e in quote_evidence}
    assert len(ids) == 2
