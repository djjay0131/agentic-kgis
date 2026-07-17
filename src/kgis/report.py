"""`IngestionReport`: what actually happened, stage by stage.

This **extends** `kg_contracts.IngestReport` rather than replacing it. The
contract model is the one explicitly-allowed mutable accumulator in
`kg_contracts` (spec §9), and it owns the sink-side tallies —
`received` / `duplicates` / `invalid`, fed by `record(outcome)`, plus
`incomplete` / `failures`, fed by `fail()`. All of that is inherited
unchanged, so an `IngestionReport` *is* an `IngestReport` anywhere one is
expected.

What it adds is the pipeline's own view, which the contract cannot have:
the ledger only ever sees candidates, so the contract can count submissions
but not the 40,000 rows that never became one.

**The counter names are worth reading carefully**, because two pairs look
alike and mean opposite things:

- `records_invalid` — rows *we* rejected before building anything.
  `invalid` (inherited) — candidates the *sink* rejected on submission.
- `candidates_suppressed` — duplicate semantic keys within this one run,
  dropped before submission. `duplicates` (inherited) — candidates the
  *ledger* already had from a previous run.

Collapsing either pair would hide exactly the thing an operator is looking
for: whether the problem is in the file, in the mapping, or in the fact that
someone already ran this yesterday.

Per spec §9, KGIS never claims a successful ingestion merely because
candidates were emitted. The stages this sprint does not own —
identity-resolved, accepted, materialized, indexed — are **absent** from this
report rather than reported as zero. A zero would say "nothing was accepted";
absence says "acceptance is not ours to know", which is the truth. They
arrive when KGCS does.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import Candidate
from kg_contracts.curation import ValidationDecision
from kg_contracts.ingestion import IngestReport
from kgis.ontology import OntologyCoverage
from kgis.validate import RecordValidation

IngestMode = Literal["execute", "dry_run"]


class IngestWarning(BaseModel):
    """Something an operator should see that did not stop the record.

    A repaired timezone, an ignored column, an unknown ontology term in
    permissive mode. Structured rather than a bare string so a report can be
    aggregated by `code` without parsing prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    record_index: int | None = None
    locator: str | None = None


class DryRunPlan(BaseModel):
    """Exactly what an execution would submit (spec §6: `kgis plan`).

    `candidates` holds the real, fully-built candidates — not a summary of
    them. That is what makes "dry-run == execution, except submission" a
    testable claim rather than a slogan: the plan is compared to what a real
    run submits, byte for byte.

    Materializing them is the one place dry-run costs more memory than
    execution, which streams in batches. `truncated` exists so that a cap on
    `candidates` can never be mistaken for a small plan — the *counts* stay
    complete even when the retained list is capped. There is no silent
    truncation anywhere in this report.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    would_submit: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    candidates: tuple[Candidate, ...] = ()
    truncated: bool = False
    ledger_duplicates: int | None = None
    """How many of these the ledger already holds — `None` when no
    `LedgerReader` was injected, because we genuinely do not know. An honest
    null (ADR-0009), not a comfortable zero: "nothing was checked" and
    "nothing is a duplicate" are different answers and an operator would act
    differently on each."""

    @property
    def ledger_checked(self) -> bool:
        return self.ledger_duplicates is not None


class IngestionReport(IngestReport):
    """The full result of one ingest run. Extends the contract's `IngestReport`.

    Inherited from the contract: `graph_id`, `received`, `duplicates`,
    `invalid`, `incomplete`, `failures`, and the `record()` / `fail()`
    accumulators. Everything below is the pipeline's own view.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    producer_run_id: str
    mode: IngestMode

    source_type: str
    source_locator: str

    # --- stage counts (only the stages KGIS actually owns) --------------------

    records_read: int = 0
    records_valid: int = 0
    records_invalid: int = 0
    """Rows *we* rejected. Distinct from the inherited `invalid`, which counts
    candidates the sink rejected."""

    candidates_built: int = 0
    candidates_suppressed: int = 0
    """Duplicate semantic keys within this run, dropped before submission.
    Distinct from the inherited `duplicates`, which counts candidates the
    ledger already had."""

    candidates_rejected: int = 0
    """Built, then failed candidate-tier validation (e.g. an unsupported
    ontology term) and never reached the sink."""

    candidates_submitted: int = 0
    """Actually handed to the `CandidateSink`. Always 0 in a dry run."""

    # --- structured detail ---------------------------------------------------

    validation_failures: list[RecordValidation] = Field(default_factory=list)
    candidate_rejections: list[ValidationDecision] = Field(default_factory=list)
    warnings: list[IngestWarning] = Field(default_factory=list)

    coverage: OntologyCoverage = Field(default_factory=OntologyCoverage)
    kind_counts: dict[str, int] = Field(default_factory=dict)

    plan: DryRunPlan | None = None
    """Present only for `mode="dry_run"`."""

    elapsed_seconds: float = 0.0

    # --- accumulators --------------------------------------------------------

    def note_validation_failure(self, decision: RecordValidation) -> None:
        """Tally a rejected record. Never produces a candidate — that is the point."""
        self.records_invalid += 1
        self.validation_failures.append(decision)

    def note_candidate_rejection(self, decision: ValidationDecision) -> None:
        """Tally a candidate that failed the sink's guard and was never submitted."""
        self.candidates_rejected += 1
        self.candidate_rejections.append(decision)

    def warn(
        self, code: str, message: str, *, record_index: int | None = None, locator: str | None = None
    ) -> None:
        self.warnings.append(
            IngestWarning(
                code=code, message=message, record_index=record_index, locator=locator
            )
        )

    # --- summary -------------------------------------------------------------

    @property
    def succeeded(self) -> bool:
        """True only if the run completed *and* nothing was rejected — by us
        or by the sink.

        Deliberately strict (spec §9): a run that emitted 10,000 candidates of
        which 40 were rejected did not succeed, it partially succeeded, and
        calling that a success is how bad ingests get shipped. The inherited
        `invalid` counts here for the same reason: a candidate the *sink*
        refused is every bit as rejected as one we refused ourselves.
        """
        return (
            not self.incomplete
            and self.records_invalid == 0
            and self.candidates_rejected == 0
            and self.invalid == 0
        )

    def fingerprint(self) -> dict[str, object]:
        """A stable digest of the run, excluding wall-clock time.

        Two replays of identical data produce equal fingerprints; `elapsed_seconds`
        is the one field that legitimately differs between them, so it is the one
        field left out.
        """
        return {
            "graph_id": self.graph_id,
            "mode": self.mode,
            "records_read": self.records_read,
            "records_valid": self.records_valid,
            "records_invalid": self.records_invalid,
            "candidates_built": self.candidates_built,
            "candidates_suppressed": self.candidates_suppressed,
            "candidates_rejected": self.candidates_rejected,
            "candidates_submitted": self.candidates_submitted,
            "received": self.received,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "incomplete": self.incomplete,
            "failures": list(self.failures),
            "kind_counts": dict(self.kind_counts),
        }

    def summary(self) -> str:
        """One-line human summary. Leads with what went wrong, if anything."""
        parts = [
            f"{self.mode}",
            f"read={self.records_read}",
            f"valid={self.records_valid}",
            f"invalid={self.records_invalid}",
            f"built={self.candidates_built}",
        ]
        if self.candidates_suppressed:
            parts.append(f"suppressed={self.candidates_suppressed}")
        if self.candidates_rejected:
            parts.append(f"rejected={self.candidates_rejected}")
        if self.mode == "execute":
            parts.append(f"received={self.received}")
            if self.duplicates:
                parts.append(f"duplicates={self.duplicates}")
            if self.invalid:
                parts.append(f"sink_invalid={self.invalid}")
        elif self.plan is not None:
            parts.append(f"would_submit={self.plan.would_submit}")
        if self.warnings:
            parts.append(f"warnings={len(self.warnings)}")
        if self.incomplete:
            parts.append("INCOMPLETE")
        parts.append(f"{self.elapsed_seconds:.3f}s")
        return " ".join(parts)
