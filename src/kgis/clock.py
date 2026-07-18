"""Injected time: `Clock`, `SystemClock`, `FixedClock`.

Time is a dependency, not an ambient fact. `CandidateEnvelope.created_at`
defaults to `datetime.now(UTC)`, which would make two ingests of identical
source data produce non-identical candidates — so the pipeline never calls
`datetime.now()` directly. It asks an injected `Clock`, and a test (or a
replay) injects `FixedClock` to get byte-identical output.

`now()` (wall time, stamped onto candidates) and `monotonic()` (elapsed
time, reported in `IngestionReport`) are deliberately separate: wall clocks
jump backwards under NTP correction, so a run's duration must never be
computed by subtracting two `now()` readings.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """The pipeline's only source of time (spec §5.8 idempotency)."""

    def now(self) -> datetime:
        """Current wall-clock instant, timezone-aware, for stamping records."""
        ...

    def monotonic(self) -> float:
        """Monotonically non-decreasing seconds, for measuring elapsed time."""
        ...


class SystemClock:
    """The real clock. The production default."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FixedClock:
    """A deterministic clock: `now()` never moves unless you move it.

    `monotonic()` advances by `tick_seconds` on each call (default `0.0`,
    i.e. every run measures as zero elapsed) so a replay test can assert
    byte-identical reports without special-casing timing fields.
    """

    def __init__(self, instant: datetime, *, tick_seconds: float = 0.0) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware instant")
        self._instant = instant
        self._tick_seconds = tick_seconds
        self._elapsed = 0.0

    def now(self) -> datetime:
        return self._instant

    def monotonic(self) -> float:
        current = self._elapsed
        self._elapsed += self._tick_seconds
        return current

    def advance(self, seconds: float) -> None:
        """Move wall time forward — for tests that need two distinct instants."""
        self._instant = self._instant + timedelta(seconds=seconds)
