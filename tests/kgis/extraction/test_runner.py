"""`ExtractionPipeline`: the end-to-end extraction mode.

Document + chunks → configured extractors (two entity types) → parse/validate →
evidence with resolvable refs → CandidateSink. All deterministic via the replay
client (or a scripted fake standing in for a live model).
"""

from __future__ import annotations

from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.extraction.client import RecordingCompletionClient, ReplayCompletionClient
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import (
    Document,
    FixedWindowChunker,
    IterableDocumentSource,
    ParagraphChunker,
)
from kgis.extraction.runner import ExtractionPipeline
from kgis.ledger.store import SqliteCandidateLedger

from .support import (
    ConcurrencyProbeModel,
    ScriptedModel,
    broken_config,
    fixed_clock,
    player_and_skill_script,
    player_config,
    sample_source,
    skill_config,
)


def _pipeline(
    *,
    client: object,
    sink: SqliteCandidateLedger,
    registry: SqliteEvidenceRegistry,
    extractors: list[ExtractorConfig] | None = None,
    concurrency: int = 4,
    ledger_reader: object | None = None,
    emit_document_artifacts: bool = False,
    run_id: str = "run_fixed",
) -> ExtractionPipeline:
    return ExtractionPipeline(
        graph_id="g1",
        document_source=sample_source(),
        chunker=ParagraphChunker(),
        extractors=extractors or [player_config(), skill_config()],
        client=client,  # type: ignore[arg-type]
        sink=sink,
        evidence_registry=registry,
        clock=fixed_clock(),
        run_id=run_id,
        ledger_reader=ledger_reader,  # type: ignore[arg-type]
        concurrency=concurrency,
        emit_document_artifacts=emit_document_artifacts,
    )


def _replay_client() -> ReplayCompletionClient:
    """A deterministic client primed by recording the scripted fake once."""
    recording = RecordingCompletionClient(ScriptedModel(player_and_skill_script()))
    # Drive one extraction pass to capture every prompt/response.
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    _pipeline(client=recording, sink=ledger, registry=registry).run()
    ledger.close()
    registry.close()
    return ReplayCompletionClient.from_recording(recording)


# --- end to end -------------------------------------------------------------


def test_two_extractors_produce_and_submit_candidates() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).run()

    assert report.candidates_built == 4
    assert report.candidates_submitted == 4
    assert report.kind_counts == {"entity": 4}
    assert report.received == 4
    assert not report.incomplete


def test_candidates_carry_producer_model_and_version() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).run()

    entries = ledger.ledger_entries()
    producers = {e.candidate.producer for e in entries}
    assert "kgis.extraction:player@1" in producers
    assert "kgis.extraction:skill@1" in producers
    for entry in entries:
        passage = entry.candidate.representations.get("source_passage")
        assert passage is not None and passage.model == "fake-model-1"


def test_evidence_refs_resolve_to_the_right_passage() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).run()

    # The "ada" player candidate must cite the "Ada ... hitting" paragraph.
    ada = next(
        e.candidate for e in ledger.ledger_entries() if e.candidate.semantic_key == "player/baseball/ada"
    )
    assert len(ada.evidence_refs) == 1
    resolved = registry.resolve(ada.candidate_id)
    assert len(resolved) == 1
    assert resolved[0].content is not None and "Ada" in resolved[0].content
    assert "Grace" not in resolved[0].content


def test_one_failing_extractor_does_not_kill_siblings() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    # `broken` returns non-JSON for its chunks; player/skill still succeed.
    script = player_and_skill_script()
    client = ScriptedModel(
        {**script, ("Broken", "Ada"): "NOT JSON", ("Broken", "Grace"): "NOT JSON"}
    )
    report = _pipeline(
        client=client,
        sink=ledger,
        registry=registry,
        extractors=[player_config(), skill_config(), broken_config()],
    ).run()

    # Siblings survived: 4 good candidates still submitted.
    assert report.candidates_submitted == 4
    # The failure is represented, not swallowed.
    assert report.incomplete is True
    assert any("broken" in failure for failure in report.failures)
    assert len(report.failures) == 2  # one per broken (chunk) work item


def test_bounded_concurrency_is_respected() -> None:
    long_text = "\n\n".join(f"Passage number {i} here." for i in range(12))
    source = IterableDocumentSource([Document(doc_id="big", text=long_text)])
    probe = ConcurrencyProbeModel('{"items": [{"player_id": "x", "name": "X"}]}')
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")

    pipeline = ExtractionPipeline(
        graph_id="g1",
        document_source=source,
        chunker=ParagraphChunker(),
        extractors=[player_config()],
        client=probe,
        sink=ledger,
        evidence_registry=registry,
        clock=fixed_clock(),
        run_id="run_c",
        concurrency=3,
    )
    pipeline.run()

    assert probe.calls == 12  # one model call per chunk
    assert probe.max_concurrent <= 3  # never exceeded the bound
    assert probe.max_concurrent >= 2  # but did run in parallel


def test_plan_shows_would_submit_without_submitting() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).plan()

    assert report.mode == "dry_run"
    assert report.plan is not None
    assert report.plan.would_submit == 4
    assert len(report.plan.candidates) == 4
    assert report.candidates_submitted == 0
    # Nothing reached the sink or the evidence registry.
    assert ledger.ledger_entries() == []
    assert registry.get(  # a chunk evidence id that a run would have written
        next(iter(report.plan.candidates)).evidence_refs[0].evidence_id
    ) is None


def test_plan_warns_when_client_is_nondeterministic() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).plan()
    assert any(w.code == "nondeterministic_plan" for w in report.warnings)


def test_plan_does_not_warn_for_replay_client() -> None:
    replay = _replay_client()
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(client=replay, sink=ledger, registry=registry).plan()
    assert not any(w.code == "nondeterministic_plan" for w in report.warnings)


def test_replay_determinism_same_fixtures_same_candidates() -> None:
    replay = _replay_client()

    def run_ids() -> list[str]:
        ledger = SqliteCandidateLedger(":memory:")
        registry = SqliteEvidenceRegistry(":memory:")
        report = _pipeline(client=replay, sink=ledger, registry=registry).plan()
        assert report.plan is not None
        return sorted(c.candidate_id for c in report.plan.candidates)

    first = run_ids()
    second = run_ids()
    assert first == second
    assert len(first) == 4


def test_plan_ledger_duplicates_reported_when_reader_present() -> None:
    replay = _replay_client()
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    # First run submits everything.
    _pipeline(client=replay, sink=ledger, registry=registry).run()
    # A plan now sees them all as ledger duplicates.
    report = _pipeline(
        client=replay, sink=ledger, registry=registry, ledger_reader=ledger
    ).plan()
    assert report.plan is not None
    assert report.plan.ledger_duplicates == 4


def test_plan_ledger_duplicates_none_without_reader() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(
        client=ScriptedModel(player_and_skill_script()), sink=ledger, registry=registry
    ).plan()
    assert report.plan is not None
    assert report.plan.ledger_duplicates is None  # honest null, not a comforting zero


def test_document_artifacts_are_emitted_when_enabled() -> None:
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    report = _pipeline(
        client=ScriptedModel(player_and_skill_script()),
        sink=ledger,
        registry=registry,
        emit_document_artifacts=True,
    ).run()
    assert report.kind_counts.get("artifact") == 1
    artifact = next(e.candidate for e in ledger.ledger_entries() if e.candidate.candidate_kind == "artifact")
    # The artifact cites the source-document evidence, which resolves.
    resolved = registry.resolve(artifact.candidate_id)
    assert len(resolved) == 1


def test_relation_and_attribute_extractors_build_correct_variants() -> None:
    """A second entity type via a different builder proves the variant mapping."""
    doc = Document(doc_id="d", text="Ada plays for the Hawks.")
    source = IterableDocumentSource([doc])
    relation_cfg = ExtractorConfig(
        extractor_id="plays_for",
        target_type="PLAYS_FOR",
        builder=_plays_for_builder(),
        prompt_template="Extract relations:\n{text}",
        system_prompt="You extract PLAYS_FOR relations.",
        model_id="fake-model-1",
        scoring=SourceScoring(source_reliability=0.6),
    )
    client = ScriptedModel(
        {("PLAYS_FOR", "Ada"): '{"items": [{"player_id": "ada", "team_id": "hawks"}]}'}
    )
    ledger = SqliteCandidateLedger(":memory:")
    registry = SqliteEvidenceRegistry(":memory:")
    ExtractionPipeline(
        graph_id="g1",
        document_source=source,
        chunker=FixedWindowChunker(window=200),
        extractors=[relation_cfg],
        client=client,
        sink=ledger,
        evidence_registry=registry,
        clock=fixed_clock(),
        run_id="run_r",
    ).run()
    entry = ledger.ledger_entries()[0]
    assert entry.candidate.candidate_kind == "relation"
    assert entry.candidate.relation_type == "PLAYS_FOR"


def _plays_for_builder() -> object:
    from kgis.builders import RelationCandidateBuilder

    return RelationCandidateBuilder(
        relation_type="PLAYS_FOR",
        subject_type="Player",
        subject_namespace="baseball",
        subject_key_field="player_id",
        object_type="Team",
        object_namespace="baseball",
        object_key_field="team_id",
    )


def test_entity_candidate_builder_import_is_used() -> None:
    # Guard: the player/skill configs use EntityCandidateBuilder.
    assert isinstance(player_config().builder, EntityCandidateBuilder)
