"""Ingestion-side ports: `Source`, `Extractor`, `CompletionClient`, `IngestJob`,
`IngestReport` (spec §5 module list, §6, §9).

`Source`, `Extractor`, and `CompletionClient` are Protocol *interfaces
only* — `kg_contracts` has no engine/LLM/network/file I/O, so no
implementation of any of them lives here. Concrete implementations (a CSV
`Source`, an LLM-backed `Extractor`, an Anthropic/OpenAI `CompletionClient`)
land in the `kgis` package in a later plan.

v2 change (ADR-0004 as amended): a deterministic `Source` still emits a
**full score set** on every candidate — `extraction_confidence` may
legitimately be `1.0` for an exact database import while `source_reliability`
is scored honestly on its own axis. There is no "confidence 1.0 => auto-ACTIVE"
shortcut anymore; a perfect read of an unreliable source is still just a
perfect read of an unreliable source.

`IngestJob` is SPEC-LEVEL: the spec's module list (§5) names it, but the
pipeline's real shape — batching, registry consultation, resumability — is
fixed by Plan 4, not here. Only the minimal `job_id`/`run()` surface is
committed to now.

`IngestReport` is the one explicitly-allowed mutable accumulator in this
package (spec §9) — every other model in `kg_contracts` is frozen. A failed
extractor must yield a partial report marked `incomplete=True` rather than a
silently truncated one, so `IngestReport.fail()` exists specifically to make
that failure visible instead of swallowed.
"""

from typing import Iterator, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import Candidate
from kg_contracts.evidence import Provenance
from kg_contracts.stores import SubmissionOutcome, SubmissionStatus


@runtime_checkable
class Source(Protocol):
    """A structured-mode candidate source (spec §5, §6).

    `fetch()` yields already-scored `Candidate`s directly — no free-text
    extraction step. Per the v2 amendment (ADR-0004), even a fully
    deterministic source (e.g. an exact database import) must emit a full
    `CandidateScores` set: `extraction_confidence=1.0` is legitimate, but
    `source_reliability` is still scored on its own, honest axis. There is
    no confidence value that auto-promotes a candidate to ACTIVE.
    """

    def fetch(self) -> Iterator[Candidate]: ...


@runtime_checkable
class Extractor(Protocol):
    """A free-text-mode candidate extractor (spec §5, §6).

    `name` identifies the extractor (e.g. for `IngestReport.fail()`
    messages). One entity type per extractor is a configuration choice for
    callers, not something this interface encodes in code.
    """

    @property
    def name(self) -> str: ...

    def extract(self, text: str, provenance: Provenance) -> list[Candidate]: ...


@runtime_checkable
class CompletionClient(Protocol):
    """The LLM provider injection point (spec §5, §6).

    KGIS mandates no provider: any implementation — Anthropic, OpenAI, a
    local model, a test fake — satisfies this interface by structural
    typing alone. `kg_contracts` never imports a provider SDK.
    """

    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


class IngestReport(BaseModel):
    """Mutable accumulator for one ingest run (spec §9).

    The one explicitly-allowed non-frozen model in `kg_contracts` — every
    other model in this package is frozen. `record()` tallies a
    `SubmissionOutcome` by its `SubmissionStatus`; `fail()` marks the report
    `incomplete` and captures a failure message. A failed extractor yields a
    partial report marked incomplete — never a silent gap.
    """

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    received: int = 0
    duplicates: int = 0
    invalid: int = 0
    incomplete: bool = False
    failures: list[str] = Field(default_factory=list)

    def record(self, outcome: SubmissionOutcome) -> None:
        """Tally `outcome` into the matching `SubmissionStatus` counter."""
        if outcome.status is SubmissionStatus.RECEIVED:
            self.received += 1
        elif outcome.status is SubmissionStatus.DUPLICATE:
            self.duplicates += 1
        elif outcome.status is SubmissionStatus.INVALID:
            self.invalid += 1

    def fail(self, message: str) -> None:
        """Mark the report incomplete and capture `message` — never a silent gap."""
        self.incomplete = True
        self.failures.append(message)


@runtime_checkable
class IngestJob(Protocol):
    """SPEC-LEVEL (spec §5 lists it): the ingest pipeline's minimal surface.

    The real shape of an ingest job — batching, registry consultation,
    resumability — is fixed in Plan 4, not here. Only `job_id` (for
    correlating logs/reports) and `run()` (producing an `IngestReport`) are
    committed to at this level.
    """

    @property
    def job_id(self) -> str: ...

    def run(self) -> IngestReport: ...
