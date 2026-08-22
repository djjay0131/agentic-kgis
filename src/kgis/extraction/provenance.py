"""First-class evidence for extraction: passages become citable `Evidence`.

Every candidate an extractor emits is *derived from* a specific passage, and
that passage is recorded as `Evidence` the candidate cites with a resolvable
`EvidenceRef` (spec §5.3). This is the honest core of LLM extraction: a claim
a model made is only as good as the passage it read, so the passage travels
with the claim rather than being discarded once the candidate exists.

Evidence IDs are **deterministic** — derived from the chunk coordinates plus
the extractor's identity and model/prompt versions — so re-extracting the same
document with the same extractor re-collects the *same* evidence rather than
piling up duplicates (the registry's `put` is idempotent by id). The extractor
identity is part of the key because provenance differs by extractor: two
extractors reading one passage cite two `Evidence` rows whose `actor`/`model`
differ, and collapsing them would lose that.

The document-level `ArtifactCandidate` records the source document itself as a
produced object — useful when downstream curation wants to reason about, or
de-duplicate, the documents a corpus was built from, not only the facts pulled
from them.
"""

from __future__ import annotations

from datetime import datetime

from kg_contracts.candidates import ArtifactCandidate, CandidateScores, SourceCoordinates
from kg_contracts.evidence import (
    Evidence,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    present_evidence,
)
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import Chunk, Document
from kgis.ids import stable_suffix

# Cap the inlined passage/document text so a very long chunk does not bloat the
# evidence row; the payload_hash covers the full text for integrity, and the
# coordinates make the full passage resolvable from the source regardless.
_MAX_INLINE_CHARS = 4000


def chunk_evidence_id(chunk: Chunk, config: ExtractorConfig) -> str:
    """Deterministic evidence id for one (passage, extractor) pair.

    Keyed on the chunk coordinates and the extractor's identity + model/prompt
    versions, so re-extraction is idempotent but two different extractors (or
    model versions) reading the same passage keep distinct evidence."""
    return "ev_" + stable_suffix(
        chunk.doc_id,
        chunk.fragment,
        config.extractor_id,
        config.model_id,
        config.model_version,
        config.prompt_version,
    )


def build_chunk_evidence(
    chunk: Chunk, config: ExtractorConfig, *, observed_at: datetime
) -> Evidence:
    """PRESENT evidence for the passage an extractor read.

    `provenance` is where the model and prompt version are recorded — the
    envelope has no field for them, so the citing candidate carries them
    transitively through this evidence (see the ADR candidate)."""
    provenance = Provenance(
        source=chunk.locator,
        source_ref=chunk.fragment,
        actor=config.extractor_id,
        model=config.model_id,
        prompt_version=config.prompt_version,
    )
    return present_evidence(
        evidence_id=chunk_evidence_id(chunk, config),
        source_type=chunk.source_type,
        source_locator=f"{chunk.locator}#{chunk.fragment}",
        observed_at=observed_at,
        provenance=provenance,
        content=chunk.text[:_MAX_INLINE_CHARS],
        payload_hash=chunk.content_hash,
    )


def chunk_evidence_ref(chunk: Chunk, config: ExtractorConfig) -> EvidenceRef:
    """A `DERIVED_FROM` citation of the passage a candidate was extracted from."""
    return EvidenceRef(
        evidence_id=chunk_evidence_id(chunk, config),
        relationship=EvidenceRelationship.DERIVED_FROM,
    )


def document_evidence_id(document: Document) -> str:
    """Deterministic evidence id for a whole source document."""
    return "ev_" + stable_suffix(document.doc_id, "document", document.content_hash)


def build_document_evidence(document: Document, *, observed_at: datetime) -> Evidence:
    """PRESENT evidence for the source document as a whole."""
    provenance = Provenance(source=document.resolved_locator, actor="kgis.extraction")
    return present_evidence(
        evidence_id=document_evidence_id(document),
        source_type=document.source_type,
        source_locator=document.resolved_locator,
        observed_at=observed_at,
        provenance=provenance,
        content=document.text[:_MAX_INLINE_CHARS],
        payload_hash=document.content_hash,
    )


def build_document_artifact(
    document: Document,
    *,
    graph_id: str,
    producer: str,
    producer_run_id: str,
    ontology_version: str,
    scores: CandidateScores,
    candidate_id: str,
    trace_id: str,
    created_at: datetime,
) -> ArtifactCandidate:
    """The source document as an `ArtifactCandidate` (a produced object, not a fact).

    Identified by its content hash and locator, per the artifact contract — an
    artifact is not a claim about the world, so it carries no entity identity.
    """
    return ArtifactCandidate(
        candidate_id=candidate_id,
        graph_id=graph_id,
        producer=producer,
        producer_run_id=producer_run_id,
        ontology_version=ontology_version,
        source_coordinates=SourceCoordinates(
            source_type=document.source_type,
            locator=document.resolved_locator,
            fragment="document",
        ),
        semantic_key=f"artifact/source_document/{document.doc_id}",
        content_hash=document.content_hash,
        scores=scores,
        trace_id=trace_id,
        created_at=created_at,
        artifact_type="source_document",
        artifact_hash=document.content_hash,
        source_uri=document.resolved_locator,
        media_type="text/plain",
    )
