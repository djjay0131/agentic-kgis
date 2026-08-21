"""Shared fakes and fixtures for the extraction tests.

Not a test module (no `test_` prefix), so pytest imports it without collecting
it. The fakes here stand in for a live LLM: `ScriptedModel` is a deterministic
function of its inputs but does *not* advertise `deterministic`, so it plays a
nondeterministic provider — wrapping it in `RecordingCompletionClient` /
`ReplayCompletionClient` is what makes a run reproducible.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.clock import FixedClock
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import Document, IterableDocumentSource

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def fixed_clock() -> FixedClock:
    return FixedClock(NOW)


class ScriptedModel:
    """A fake model: routes on an extractor marker (in `system`) + a chunk
    marker (in `prompt`) to a canned response, else returns empty items.

    Deterministic as a function, but deliberately does NOT set
    `deterministic = True` — it plays a live provider so tests can exercise the
    record→replay path and the nondeterministic-plan warning.
    """

    def __init__(
        self, script: dict[tuple[str, str], str], *, default: str = '{"items": []}'
    ) -> None:
        self._script = dict(script)
        self._default = default
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        sys_text = system or ""
        for (extractor_marker, chunk_marker), response in self._script.items():
            if extractor_marker in sys_text and chunk_marker in prompt:
                return response
        return self._default


class ConcurrencyProbeModel:
    """Records the maximum number of `complete()` calls running concurrently.

    A tiny sleep forces overlap so the bound is actually exercised; guarded by
    a lock so the max is observed correctly.
    """

    def __init__(self, response: str, *, hold_seconds: float = 0.02) -> None:
        self._response = response
        self._hold = hold_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        with self._lock:
            self._active += 1
            self.calls += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            time.sleep(self._hold)
            return self._response
        finally:
            with self._lock:
                self._active -= 1


def player_config(*, extractor_version: str = "1", model_id: str = "fake-model-1") -> ExtractorConfig:
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
        model_id=model_id,
        model_version="2026-08",
        extractor_version=extractor_version,
        prompt_version="p1",
        scoring=SourceScoring(source_reliability=0.7, extraction_confidence=0.5),
    )


def skill_config() -> ExtractorConfig:
    return ExtractorConfig(
        extractor_id="skill",
        target_type="Skill",
        builder=EntityCandidateBuilder(
            namespace="baseball",
            key_field="skill_id",
            entity_type="Skill",
            display_name_field="name",
        ),
        prompt_template="Extract skills from:\n{text}",
        system_prompt="You extract Skill entities.",
        model_id="fake-model-1",
        model_version="2026-08",
        extractor_version="1",
        prompt_version="p1",
        scoring=SourceScoring(source_reliability=0.6),
    )


def broken_config() -> ExtractorConfig:
    """An extractor whose model returns non-JSON — used for failure isolation."""
    return ExtractorConfig(
        extractor_id="broken",
        target_type="Player",
        builder=EntityCandidateBuilder(
            namespace="baseball",
            key_field="player_id",
            entity_type="Player",
        ),
        prompt_template="Extract broken from:\n{text}",
        system_prompt="You extract Broken entities.",
        model_id="fake-model-1",
        scoring=SourceScoring(source_reliability=0.5),
    )


SAMPLE_DOC = Document(
    doc_id="doc-1",
    text="Ada is a shortstop known for hitting.\n\nGrace coaches fielding.",
    source_type="scouting_report",
    locator="s3://reports/doc-1.txt",
)


def sample_source() -> IterableDocumentSource:
    return IterableDocumentSource([SAMPLE_DOC], source_type="scouting_report", locator="s3://reports")


def player_and_skill_script() -> dict[tuple[str, str], str]:
    """Routes each extractor to canned JSON per chunk (keyed on a name in the chunk)."""
    return {
        ("Player", "Ada"): '{"items": [{"player_id": "ada", "name": "Ada", "confidence": 0.91}]}',
        ("Player", "Grace"): '{"items": [{"player_id": "grace", "name": "Grace"}]}',
        ("Skill", "Ada"): '{"items": [{"skill_id": "hitting", "name": "Hitting"}]}',
        ("Skill", "Grace"): '{"items": [{"skill_id": "fielding", "name": "Fielding"}]}',
    }
