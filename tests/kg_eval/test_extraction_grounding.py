"""Regression (issue #60): real extraction output is grounded, not unsupported.

`evaluate_extraction` grades a `kgis` extraction run end to end. Every producer
in `kgis` cites its passage with a `DERIVED_FROM` ref, never `SUPPORTS`, so the
old `SUPPORTS`-only rule scored real extraction 100% unsupported. These tests
pin the split semantics against genuine pipeline output rather than hand-built
`SUPPORTS` refs, so a regression to the old rule fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kg_eval import ArmConfig, ArmOutput, GoldEntity, GoldSet, evaluate_extraction
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.clock import FixedClock
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.extraction.client import RecordingCompletionClient
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import (
    Document,
    IterableDocumentSource,
    ParagraphChunker,
)
from kgis.extraction.runner import ExtractionPipeline
from kgis.ledger.store import SqliteCandidateLedger

NOW = datetime(2026, 10, 8, tzinfo=UTC)


class _ScriptedModel:
    """A fake-live provider: routes on the extractor + chunk markers.

    Deliberately does not advertise `deterministic`; it stands in for a live
    model so the run goes through `RecordingCompletionClient` exactly as a real
    extraction would.
    """

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if "Player" in (system or ""):
            if "Ada" in prompt:
                return '{"items": [{"player_id": "ada", "name": "Ada", "confidence": 0.91}]}'
            if "Grace" in prompt:
                return '{"items": [{"player_id": "grace", "name": "Grace"}]}'
        return '{"items": []}'


def _player_config() -> ExtractorConfig:
    return ExtractorConfig(
        extractor_id="player",
        target_type="Player",
        builder=EntityCandidateBuilder(
            namespace="baseball",
            key_field="player_id",
            entity_type="Player",
            display_name_field="name",
        ),
        prompt_template="Extract players from:\n{text}",
        system_prompt="You extract Player entities.",
        model_id="fake-model-1",
        model_version="2026-08",
        extractor_version="1",
        prompt_version="p1",
        scoring=SourceScoring(source_reliability=0.7, extraction_confidence=0.5),
    )


def _run_extraction() -> ArmOutput:
    """Run a real `ExtractionPipeline` and adapt its output to an `ArmOutput`."""
    document = Document(
        doc_id="doc-1",
        text="Ada is a shortstop known for hitting.\n\nGrace coaches fielding.",
        source_type="scouting_report",
        locator="s3://reports/doc-1.txt",
    )
    source = IterableDocumentSource(
        [document], source_type="scouting_report", locator="s3://reports"
    )
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    try:
        ExtractionPipeline(
            graph_id="baseball",
            document_source=source,
            chunker=ParagraphChunker(),
            extractors=[_player_config()],
            client=RecordingCompletionClient(_ScriptedModel()),
            sink=ledger,
            evidence_registry=registry,
            clock=FixedClock(NOW),
            run_id="run-1",
        ).run()

        candidates = tuple(entry.candidate for entry in ledger.ledger_entries())
        evidence = {}
        for candidate in candidates:
            for ref in candidate.evidence_refs:
                stored = registry.get(ref.evidence_id)
                if stored is not None:
                    evidence[ref.evidence_id] = stored
    finally:
        ledger.close()
        registry.close()

    return ArmOutput(
        arm=ArmConfig(arm_id="llm-extraction"),
        candidates=candidates,
        evidence=evidence,
    )


def _gold() -> GoldSet:
    """Gold matching the two players the pipeline extracts (grounding only)."""
    return GoldSet(
        gold_set_id="extraction-regression",
        entities=(
            GoldEntity(entity_type="Player", semantic_key="player/baseball/ada"),
            GoldEntity(entity_type="Player", semantic_key="player/baseball/grace"),
        ),
    )


def test_real_extraction_produces_candidates_with_present_derived_from_refs() -> None:
    output = _run_extraction()
    assert len(output.candidates) == 2
    # Every candidate's citation resolves to PRESENT evidence.
    for candidate in output.candidates:
        assert candidate.evidence_refs
        resolved = [output.evidence.get(ref.evidence_id) for ref in candidate.evidence_refs]
        assert all(ev is not None for ev in resolved)


def test_real_extraction_is_grounded_not_reported_unsupported() -> None:
    """The bug: a `SUPPORTS`-only rule scored this run 2 unsupported."""
    m = evaluate_extraction(_run_extraction(), _gold())
    assert m.unsupported_assertion_count == 0


def test_real_extraction_is_grounded_but_unverified() -> None:
    """`DERIVED_FROM` grounds a claim; only `SUPPORTS` verifies it."""
    m = evaluate_extraction(_run_extraction(), _gold())
    assert m.unverified_assertion_count == 2
    assert m.evidence.resolvable_rate.value == 1.0


def test_grounding_metrics_agree_on_the_matched_entities() -> None:
    m = evaluate_extraction(_run_extraction(), _gold())
    # The two real candidates match both gold entities exactly.
    assert m.entity.precision.value == 1.0
    assert m.entity.recall.value == 1.0
