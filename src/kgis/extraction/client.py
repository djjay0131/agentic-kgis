"""The LLM injection seam and the clients that make extraction testable.

`kg_contracts.ingestion.CompletionClient` is the whole seam: `complete(prompt,
*, system=None) -> str`. No vendor SDK appears in `kg_contracts` or in this
module — a real Anthropic/OpenAI client satisfies the protocol by structural
typing alone, and the pipeline never imports one. That keeps the core free of
provider dependencies (spec §6, decision 2) and makes every test run against a
fake instead of a network.

**Why LLM extraction is not deterministic, and what to do about it.** A live
model may return different text for the same prompt on two calls, so an
extraction `run()` is not reproducible the way a structured sync is. Two tools
here make it reproducible *when you need it to be*:

- `RecordingCompletionClient` wraps any client and captures every
  `(prompt, system) -> response` it sees, keyed by a stable request hash.
- `ReplayCompletionClient` serves those recorded responses back and **raises
  on an unrecorded prompt** rather than inventing one — an honest miss, never
  a fabricated completion (the same discipline as the evidence registry's
  refusal to silently drop a dangling ref).

A client advertises reproducibility with a `deterministic` attribute; the
pipeline reads it via `is_deterministic()` to decide whether a dry-run may
promise its plan will match a later run. A recording client is deterministic
only if the client it wraps is — recording a nondeterministic model does not
make it repeatable, it only captures one roll of the dice.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping

from kg_contracts.ingestion import CompletionClient

_SEP = b"\x00"


def request_key(prompt: str, system: str | None) -> str:
    """A stable content hash of one completion request.

    Keyed on both `system` and `prompt`, NUL-joined so ("a", "bc") and
    ("ab", "c") cannot collide. blake2b (not a hash-randomized `hash()`) makes
    the key identical across processes, which is what lets a recording made in
    one run replay in another.
    """
    digest = hashlib.blake2b(
        _SEP.join(part.encode("utf-8") for part in ((system or ""), prompt)),
        digest_size=16,
    )
    return digest.hexdigest()


def is_deterministic(client: CompletionClient) -> bool:
    """Whether `client` promises the same response for the same request.

    Read by the pipeline's dry-run: only a deterministic client lets `plan()`
    honestly claim its candidates are what a later `run()` will submit.
    Unknown clients are assumed nondeterministic — the safe default.
    """
    return bool(getattr(client, "deterministic", False))


class ReplayMiss(KeyError):
    """A prompt with no recorded response.

    Raised instead of fabricating a completion: a replay that quietly invented
    output for an unseen prompt would make a "deterministic" test a lie.
    """


class StaticCompletionClient:
    """Returns one fixed response for every prompt. Trivially deterministic.

    Useful for the simplest extractor tests and as a stand-in when the prompt
    does not affect the (canned) output.
    """

    deterministic = True

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        return self._response


class ReplayCompletionClient:
    """Serves recorded responses, keyed by `request_key`; raises on a miss.

    This is how the extraction suite stays deterministic without a network: a
    fixture maps each request hash to the exact model text, and replay returns
    it verbatim. An unrecorded prompt is a `ReplayMiss`, never a guess.
    """

    deterministic = True

    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = dict(responses)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        key = request_key(prompt, system)
        try:
            return self._responses[key]
        except KeyError:
            raise ReplayMiss(
                f"no recorded response for request key {key!r} "
                f"(system={system!r}, prompt[:60]={prompt[:60]!r})"
            ) from None

    @classmethod
    def from_recording(cls, recording: RecordingCompletionClient) -> ReplayCompletionClient:
        """Build a replay client from a recording's captured responses."""
        return cls(recording.responses)

    @classmethod
    def from_json(cls, payload: str) -> ReplayCompletionClient:
        """Load a fixture written by `RecordingCompletionClient.to_json()`."""
        data = json.loads(payload)
        return cls({str(k): str(v) for k, v in data.items()})


class RecordingCompletionClient:
    """Wraps a client, capturing every `(prompt, system) -> response`.

    The bridge from a live (or fake-live) model to a replay fixture: run an
    extraction through this once, then serialize `responses` (or hand it to
    `ReplayCompletionClient.from_recording`) to replay it forever.

    `deterministic` mirrors the wrapped client: recording a nondeterministic
    model captures one sample, it does not make the model repeatable.
    """

    def __init__(self, inner: CompletionClient) -> None:
        self._inner = inner
        self._responses: dict[str, str] = {}
        # A general-purpose wrapper: it may be driven from several threads at
        # once (the extraction runner records under its default concurrency).
        # Distinct-key writes plus CPython's GIL would already make the dict
        # write safe today, but that is an implementation detail a caller
        # should not have to know — the lock makes the guarantee explicit and
        # holds if the wrapper is ever reused with colliding keys.
        self._lock = threading.Lock()

    @property
    def deterministic(self) -> bool:
        return is_deterministic(self._inner)

    @property
    def responses(self) -> dict[str, str]:
        with self._lock:
            return dict(self._responses)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        response = self._inner.complete(prompt, system=system)
        with self._lock:
            self._responses[request_key(prompt, system)] = response
        return response

    def to_json(self) -> str:
        """Serialize captured responses as a replayable JSON fixture."""
        return json.dumps(self._responses, sort_keys=True, indent=2)

    def save(self, path: str | os.PathLike[str]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())
