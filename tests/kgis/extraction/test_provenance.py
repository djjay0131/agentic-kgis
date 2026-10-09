"""Evidence + artifact construction for extraction."""

from __future__ import annotations

from kg_contracts.candidates import CandidateScores
from kg_contracts.evidence import EvidenceAvailability, EvidenceRelationship, TextSpan
from kgis.extraction.documents import ParagraphChunker
from kgis.extraction.provenance import (
    build_chunk_evidence,
    build_document_artifact,
    build_document_evidence,
    build_quote_evidence,
    chunk_evidence_id,
    chunk_evidence_ref,
    quote_evidence_id,
    quote_evidence_ref,
)

from .support import NOW, SAMPLE_DOC, player_config


def _chunk() -> object:
    return ParagraphChunker().chunk(SAMPLE_DOC)[0]


def test_chunk_evidence_id_is_deterministic() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    config = player_config()
    assert chunk_evidence_id(chunk, config) == chunk_evidence_id(chunk, config)


def test_chunk_evidence_id_differs_by_extractor() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    a = chunk_evidence_id(chunk, player_config())
    b = chunk_evidence_id(chunk, player_config(model_id="other-model"))
    assert a != b


def test_chunk_evidence_is_present_with_provenance() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    config = player_config(model_id="claude-fake")
    evidence = build_chunk_evidence(chunk, config, observed_at=NOW)
    assert evidence.availability is EvidenceAvailability.PRESENT
    assert evidence.provenance.model == "claude-fake"
    assert evidence.provenance.model_version == "2026-08"
    assert evidence.provenance.actor == "player"
    assert evidence.provenance.prompt_version == "p1"
    assert evidence.payload_hash == chunk.content_hash


def test_chunk_ref_is_derived_from() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    ref = chunk_evidence_ref(chunk, player_config())
    assert ref.relationship is EvidenceRelationship.DERIVED_FROM
    assert ref.evidence_id == chunk_evidence_id(chunk, player_config())


def test_document_evidence_round_trips() -> None:
    evidence = build_document_evidence(SAMPLE_DOC, observed_at=NOW)
    assert evidence.availability is EvidenceAvailability.PRESENT
    assert evidence.source_locator == SAMPLE_DOC.resolved_locator


def test_document_artifact_is_hash_addressed() -> None:
    artifact = build_document_artifact(
        SAMPLE_DOC,
        graph_id="g1",
        producer="kgis.extraction",
        producer_run_id="run_x",
        ontology_version="v1",
        scores=CandidateScores(extraction_confidence=1.0, source_reliability=1.0),
        candidate_id="cand_doc",
        trace_id="trace_doc",
        created_at=NOW,
    )
    assert artifact.candidate_kind == "artifact"
    assert artifact.artifact_type == "source_document"
    assert artifact.artifact_hash == SAMPLE_DOC.content_hash
    assert artifact.source_uri == SAMPLE_DOC.resolved_locator


def test_chunk_evidence_carries_a_document_span() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    evidence = build_chunk_evidence(chunk, player_config(), observed_at=NOW)
    assert evidence.span is not None
    assert evidence.span.start == chunk.start
    assert evidence.span.end == chunk.end
    # The span resolves exactly back to the chunk text — the acceptance claim.
    assert SAMPLE_DOC.text[evidence.span.start:evidence.span.end] == chunk.text
    # The legacy locator string is unchanged (backward compatible).
    assert evidence.source_locator == f"{chunk.locator}#{chunk.fragment}"


def _quote_span() -> TextSpan:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    local = chunk.text.index("shortstop")
    start = chunk.start + local
    return TextSpan(start=start, end=start + len("shortstop"), quote="shortstop")


def test_quote_evidence_is_narrowed_to_the_quote() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    span = _quote_span()
    evidence = build_quote_evidence(chunk, player_config(), span=span, observed_at=NOW)
    assert evidence.span == span
    assert evidence.content == "shortstop"
    assert evidence.availability is EvidenceAvailability.PRESENT
    assert SAMPLE_DOC.text[evidence.span.start:evidence.span.end] == "shortstop"
    assert evidence.provenance.actor == "player"


def test_quote_evidence_id_is_deterministic_and_offset_keyed() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    config = player_config()
    span = _quote_span()
    first = quote_evidence_id(chunk, config, start=span.start, end=span.end)
    second = quote_evidence_id(chunk, config, start=span.start, end=span.end)
    assert first == second
    # different offsets -> different id (two quotes in one chunk stay distinct)
    assert first != quote_evidence_id(chunk, config, start=span.start + 1, end=span.end)
    assert first.startswith("ev_") and len(first) == 3 + 26


def test_chunk_and_quote_evidence_ids_differ() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    config = player_config()
    span = _quote_span()
    assert chunk_evidence_id(chunk, config) != quote_evidence_id(
        chunk, config, start=span.start, end=span.end
    )


def test_quote_ref_is_derived_from() -> None:
    chunk = ParagraphChunker().chunk(SAMPLE_DOC)[0]
    span = _quote_span()
    ref = quote_evidence_ref(chunk, player_config(), span=span)
    assert ref.relationship is EvidenceRelationship.DERIVED_FROM
    assert ref.evidence_id == quote_evidence_id(
        chunk, player_config(), start=span.start, end=span.end
    )
