"""Evidence + artifact construction for extraction."""

from __future__ import annotations

from kg_contracts.candidates import CandidateScores
from kg_contracts.evidence import EvidenceAvailability, EvidenceRelationship
from kgis.extraction.documents import ParagraphChunker
from kgis.extraction.provenance import (
    build_chunk_evidence,
    build_document_artifact,
    build_document_evidence,
    chunk_evidence_id,
    chunk_evidence_ref,
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
