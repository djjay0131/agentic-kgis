"""The models that flow between pipeline stages: `SourceRecord`,
`NormalizedRecord`, `RecordIssue`.

These are *internal* pipeline models, deliberately not contracts. A record
is not a candidate: it has no scores, no producer, no identity, and it may
be malformed. It exists only between `RecordReader.read()` and
`CandidateBuilder.build()`, and never leaves `kgis`.

Two rules shape them:

- **Normalization is total.** `NormalizedRecord` can hold a record that
  failed to normalize — the bad values are recorded in `issues` rather than
  raised. A stage that raises on bad data cannot report on bad data, and
  rejections are data, not exceptions (spec §9). Validation is the single
  place a record is rejected.
- **Nothing is silently dropped.** Input keys the schema doesn't declare
  land in `extras`, not the bin. Which fields a source carried but the
  mapping ignored is exactly the kind of thing an operator needs to see in a
  dry run.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import SourceCoordinates

IssueSeverity = Literal["error", "warning"]
"""`error` blocks candidate creation; `warning` is reported and proceeds."""


class RecordIssue(BaseModel):
    """One thing that went wrong (or looked odd) while handling a record.

    `severity="error"` means the record cannot become a candidate;
    `severity="warning"` means it can, but an operator should see this.
    `code` is a stable machine-readable slug (e.g. `"coercion_failed"`) so
    reports can be aggregated without string-matching prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: IssueSeverity = "error"
    field: str | None = None

    def render(self) -> str:
        """A one-line human rendering, used in report reason strings."""
        location = f" [{self.field}]" if self.field is not None else ""
        return f"{self.code}{location}: {self.message}"


class SourceRecord(BaseModel):
    """One raw record as read from a source, before any interpretation.

    `data` is whatever the reader produced — CSV gives every value as `str`,
    JSON gives real types. Normalization is what erases that difference;
    this model deliberately preserves it.

    `index` is the record's 0-based position in the source stream, which is
    what makes ordering assertions (and "record 47 failed") possible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    coordinates: SourceCoordinates
    data: dict[str, object]


class NormalizedRecord(BaseModel):
    """A `SourceRecord` mapped onto canonical field names and types.

    Carries its own `issues` rather than raising, so a malformed record is
    still a first-class object that validation can reject *and report on*.
    `has_errors` is the single question validation asks of normalization.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    coordinates: SourceCoordinates
    values: dict[str, object]
    extras: dict[str, object] = Field(default_factory=dict)
    issues: tuple[RecordIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        """True if any issue is severity `error` — i.e. no candidate may be built."""
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> tuple[RecordIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[RecordIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")
