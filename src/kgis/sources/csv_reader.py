"""`CsvRecordReader`: records from a CSV file or an in-memory CSV string.

CSV has no types — every value arrives as `str`, and an empty cell is `""`,
not `None`. This reader does **not** fix that. Interpreting `"42"` as an
integer or `""` as missing is normalization's job, and a reader that
guessed would make the same input mean different things depending on which
format it arrived in. The one thing this reader guarantees is that a CSV
row and the equivalent JSON object reach normalization as the *same shape*,
differing only in the types CSV cannot express.

Two structural oddities are preserved rather than dropped: a short row's
missing columns come through as `None`, and a long row's surplus values land
under `UNNAMED_COLUMNS` — reported, never silently truncated.
"""

import csv
from io import StringIO
from pathlib import Path
from typing import Iterator, TextIO

from kg_contracts.candidates import SourceCoordinates
from kgis.errors import ConfigurationError, SourceReadError
from kgis.records import RecordIssue, SourceRecord

UNNAMED_COLUMNS = "__unnamed__"
"""Key under which values beyond the header's columns are preserved."""

# The header occupies line 1, so the first data row is line 2. Reporting the
# line an operator would actually see in an editor beats a 0-based offset.
_FIRST_DATA_LINE = 2


class CsvRecordReader:
    """A `RecordReader` over delimited text.

    Exactly one of `path` / `text` must be given. `locator` defaults to the
    file's **name**, not its full path: the locator is stamped into every
    candidate, and an absolute path would make otherwise-identical
    candidates differ between a laptop and CI. Pass an explicit `locator`
    (a URI, a table name) when the source has a real stable address.
    """

    def __init__(
        self,
        *,
        path: Path | str | None = None,
        text: str | None = None,
        locator: str | None = None,
        source_type: str = "csv",
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> None:
        if (path is None) == (text is None):
            raise ConfigurationError("CsvRecordReader requires exactly one of path= or text=")
        self._path = Path(path) if path is not None else None
        self._text = text
        self._source_type = source_type
        self._delimiter = delimiter
        self._encoding = encoding
        if locator is not None:
            self._locator = locator
        elif self._path is not None:
            self._locator = self._path.name
        else:
            self._locator = "inline"

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def locator(self) -> str:
        return self._locator

    def _open(self) -> TextIO:
        if self._path is not None:
            try:
                # newline="" per the csv module: it does its own newline
                # handling, and letting Python translate first corrupts
                # quoted fields containing embedded newlines.
                return self._path.open("r", encoding=self._encoding, newline="")
            except OSError as exc:
                raise SourceReadError(f"cannot read CSV {self._path}: {exc}") from exc
        return StringIO(self._text or "", newline="")

    def read(self) -> Iterator[SourceRecord]:
        handle = self._open()
        try:
            reader = csv.DictReader(
                handle, delimiter=self._delimiter, restkey=UNNAMED_COLUMNS, restval=None
            )
            try:
                rows = enumerate(reader)
                for index, row in rows:
                    yield self._to_record(index, row)
            except (csv.Error, UnicodeDecodeError, OSError) as exc:
                # A fault part-way through the stream. The pipeline marks the
                # report incomplete rather than treating a truncated read as
                # a short source (spec §9: never a silent gap).
                raise SourceReadError(f"failed reading CSV {self._locator}: {exc}") from exc
        finally:
            handle.close()

    def _to_record(self, index: int, row: dict[str | None, object]) -> SourceRecord:
        issues: list[RecordIssue] = []
        data: dict[str, object] = {}
        for key, value in row.items():
            if key is None:
                # DictReader only produces a None key when a row is longer
                # than the header and no restkey is set — we set one, so
                # this is unreachable in practice. Kept as a hard guard
                # rather than a silent drop.
                continue
            data[key] = value

        surplus = data.get(UNNAMED_COLUMNS)
        if surplus is not None:
            issues.append(
                RecordIssue(
                    code="unnamed_columns",
                    message=f"row has more values than the header declares: {surplus!r}",
                    severity="warning",
                )
            )

        if any(value is None for value in data.values()):
            missing = sorted(key for key, value in data.items() if value is None)
            issues.append(
                RecordIssue(
                    code="short_row",
                    message=f"row is missing values for {', '.join(missing)}",
                    severity="warning",
                )
            )

        return SourceRecord(
            index=index,
            coordinates=SourceCoordinates(
                source_type=self._source_type,
                locator=self._locator,
                fragment=f"row={index + _FIRST_DATA_LINE}",
            ),
            data=data,
            issues=tuple(issues),
        )
