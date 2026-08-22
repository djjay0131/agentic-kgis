"""Injected identifier minting: `IdStrategy`, deterministic and random.

`CandidateEnvelope.candidate_id` and `trace_id` both default to a random
ULID. Random IDs make "same input → same candidates" untestable and make a
replay indistinguishable from a fresh run, so the pipeline never takes those
defaults: it asks an injected `IdStrategy`.

`DeterministicIdStrategy` (the pipeline default) derives both IDs from a
digest, with a deliberate difference in what each one is keyed on:

- `candidate_id` is keyed on **what the candidate is** — `(graph_id,
  candidate_kind, semantic_key)`. Re-ingesting the same source row therefore
  mints the *same* candidate ID, because it is the same proposed fact. This
  is what makes replay idempotent rather than merely repeatable.
- `trace_id` is keyed on **which run produced it** — the above plus
  `run_id`. Two runs over identical data yield the same candidates but
  distinct traces, so the universal trace ID (spec §5.9) still correlates a
  record to *one* run rather than collapsing every replay into one trace.

Note the asymmetry is load-bearing: a deterministic `trace_id` would make
two separate ingests indistinguishable in the audit stream, and a random
`candidate_id` would make the ledger unable to recognize a replay.

IDs are rendered in Crockford base32 to the same 26-character shape as a
ULID, so a deterministic ID is drop-in wherever a ULID-shaped one is
expected. The encoder is reimplemented here rather than imported from
`kg_contracts._ulid`: that module is private to its package, and reaching
into another package's private module to avoid six lines is the worse
trade. See `docs/adr/candidates/0003-a-public-deterministic-id-helper.md` —
a public ULID helper on `kg_contracts`
would remove this duplication.
"""

import hashlib
import os
import time
from typing import Protocol, runtime_checkable

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LENGTH = 26

# NUL-joined, because naive concatenation collides: ("ab", "c") and
# ("a", "bc") would otherwise digest identically and two different
# candidates would share an ID.
_PART_SEPARATOR = b"\x00"


def _encode_crockford(data: bytes, length: int) -> str:
    """Encode `data` as `length` Crockford-base32 characters, MSB first."""
    value = int.from_bytes(data, byteorder="big")
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def stable_suffix(*parts: str) -> str:
    """Derive a ULID-shaped 26-char ID suffix from `parts`, deterministically.

    Pure: the same parts always give the same suffix, in this process and in
    any other. blake2b (not a hash-randomized `hash()`) is what makes that
    true across interpreter runs.
    """
    digest = hashlib.blake2b(
        _PART_SEPARATOR.join(part.encode("utf-8") for part in parts), digest_size=16
    ).digest()
    return _encode_crockford(digest, _ULID_LENGTH)


def random_suffix() -> str:
    """Mint a random ULID-shaped suffix: 48-bit ms timestamp + 80 random bits."""
    timestamp_ms = int(time.time() * 1000)
    return _encode_crockford(timestamp_ms.to_bytes(6, byteorder="big"), 10) + _encode_crockford(
        os.urandom(10), 16
    )


@runtime_checkable
class IdStrategy(Protocol):
    """Mints the IDs the pipeline stamps onto candidates.

    Injected rather than defaulted so that determinism is a property of the
    configured pipeline, not of the test harness.
    """

    def candidate_id(self, *, graph_id: str, candidate_kind: str, semantic_key: str) -> str:
        """The ID for the candidate identified by these coordinates."""
        ...

    def trace_id(
        self, *, run_id: str, graph_id: str, candidate_kind: str, semantic_key: str
    ) -> str:
        """The universal trace ID (spec §5.9) for this candidate in this run."""
        ...


class DeterministicIdStrategy:
    """Content-addressed IDs. The pipeline default.

    Same fact → same `candidate_id`, forever. Same fact in a different run →
    a different `trace_id`.
    """

    def candidate_id(self, *, graph_id: str, candidate_kind: str, semantic_key: str) -> str:
        return "cand_" + stable_suffix(graph_id, candidate_kind, semantic_key)

    def trace_id(
        self, *, run_id: str, graph_id: str, candidate_kind: str, semantic_key: str
    ) -> str:
        return "trace_" + stable_suffix(run_id, graph_id, candidate_kind, semantic_key)


class RandomIdStrategy:
    """Random ULID IDs, matching the `kg_contracts` field defaults.

    Provided for callers who genuinely want a fresh identity per run (and to
    prove the pipeline's determinism guarantees come from `IdStrategy`, not
    from something hardcoded). Using this forfeits replay idempotency.
    """

    def candidate_id(self, *, graph_id: str, candidate_kind: str, semantic_key: str) -> str:
        return "cand_" + random_suffix()

    def trace_id(
        self, *, run_id: str, graph_id: str, candidate_kind: str, semantic_key: str
    ) -> str:
        return "trace_" + random_suffix()


def new_run_id() -> str:
    """Mint a fresh `producer_run_id` for an ingest run."""
    return "run_" + random_suffix()


def new_job_id() -> str:
    """Mint a fresh `job_id` for an ingest job.

    A job id is minted in its own right, not derived from a run id by string
    surgery: a job may span several runs, so its identity is independent."""
    return "job_" + random_suffix()
