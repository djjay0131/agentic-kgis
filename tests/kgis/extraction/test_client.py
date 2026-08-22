"""Completion clients: replay determinism, recording, honest misses."""

from __future__ import annotations

import pytest

from kg_contracts.ingestion import CompletionClient
from kgis.extraction.client import (
    RecordingCompletionClient,
    ReplayCompletionClient,
    ReplayMiss,
    StaticCompletionClient,
    is_deterministic,
    request_key,
)
from kgis.testing.extraction import CompletionClientContract


class TestStaticClientContract(CompletionClientContract):
    def make_client(self) -> CompletionClient:
        return StaticCompletionClient('{"items": []}')


class TestReplayClientContract(CompletionClientContract):
    def make_client(self) -> CompletionClient:
        responses = {request_key("hello", None): "hi", request_key("hello", "you are a test"): "hi"}
        return ReplayCompletionClient(responses)


def test_request_key_is_stable_and_separates_system_from_prompt() -> None:
    assert request_key("a", "b") == request_key("a", "b")
    # ("ab", "c") and ("a", "bc") must not collide.
    assert request_key("ab", "c") != request_key("a", "bc")


def test_static_client_is_deterministic() -> None:
    assert is_deterministic(StaticCompletionClient("x")) is True


def test_replay_hits_recorded_and_misses_raise() -> None:
    replay = ReplayCompletionClient({request_key("known", None): "answer"})
    assert replay.complete("known") == "answer"
    with pytest.raises(ReplayMiss):
        replay.complete("unknown")


def test_recording_then_replay_round_trips() -> None:
    inner = StaticCompletionClient("recorded-response")
    recording = RecordingCompletionClient(inner)
    got = recording.complete("prompt-1", system="sys")
    assert got == "recorded-response"

    replay = ReplayCompletionClient.from_recording(recording)
    assert replay.complete("prompt-1", system="sys") == "recorded-response"


def test_recording_deterministic_mirrors_inner() -> None:
    # Wrapping a deterministic client is deterministic; the replay built from it
    # certainly is.
    recording = RecordingCompletionClient(StaticCompletionClient("x"))
    assert recording.deterministic is True


def test_recording_serializes_to_replayable_json() -> None:
    recording = RecordingCompletionClient(StaticCompletionClient("resp"))
    recording.complete("p", system=None)
    payload = recording.to_json()
    replay = ReplayCompletionClient.from_json(payload)
    assert replay.complete("p") == "resp"


def test_unknown_client_assumed_nondeterministic() -> None:
    class _Bare:
        def complete(self, prompt: str, *, system: str | None = None) -> str:
            return "x"

    assert is_deterministic(_Bare()) is False
