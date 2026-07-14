"""`JsonRecordReader`: records from a JSON array or a JSON-Lines stream.

Both shapes are the same source to the pipeline; only the framing differs,
and `mode="auto"` picks by looking at the first non-space character.

The failure split here is the interesting part, and it follows spec §9
("rejections are data; exceptions are bugs"):

- A **document** that will not parse (`[{"a": 1},`) is an I/O-class fault:
  there are no records to speak of, so `SourceReadError` is raised and the
  run is marked incomplete. Reporting "0 records" for a truncated file would
  be a lie.
- A **record** that is malformed — one bad line in a JSONL stream, or a bare
  scalar sitting in an array of objects — is bad *data*. It is emitted as a
  `SourceRecord` carrying an error issue, so validation rejects exactly that
  record, names it, and the other 9,999 still ingest.
"""

import json
from pathlib import Path
from typing import Iterator, Literal

from kg_contracts.candidates import SourceCoordinates
from kgis.errors import ConfigurationError, SourceReadError
from kgis.records import RecordIssue, SourceRecord

JsonMode = Literal["auto", "array", "lines"]


class JsonRecordReader:
    """A `RecordReader` over a JSON array of objects, or JSON Lines.

    `locator` defaults to the file's name rather than its full path, for the
    same reason as `CsvRecordReader` — see that class.
    """

    def __init__(
        self,
        *,
        path: Path | str | None = None,
        text: str | None = None,
        locator: str | None = None,
        source_type: str = "json",
        mode: JsonMode = "auto",
        encoding: str = "utf-8",
    ) -> None:
        if (path is None) == (text is None):
            raise ConfigurationError("JsonRecordReader requires exactly one of path= or text=")
        self._path = Path(path) if path is not None else None
        self._text = text
        self._source_type = source_type
        self._mode: JsonMode = mode
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

    def _load_text(self) -> str:
        if self._path is not None:
            try:
                return self._path.read_text(encoding=self._encoding)
            except (OSError, UnicodeDecodeError) as exc:
                raise SourceReadError(f"cannot read JSON {self._path}: {exc}") from exc
        return self._text or ""

    def _resolve_mode(self, text: str) -> Literal["array", "lines"]:
        if self._mode != "auto":
            return self._mode
        return "array" if text.lstrip().startswith("[") else "lines"

    def read(self) -> Iterator[SourceRecord]:
        text = self._load_text()
        if self._resolve_mode(text) == "array":
            yield from self._read_array(text)
        else:
            yield from self._read_lines(text)

    def _read_array(self, text: str) -> Iterator[SourceRecord]:
        stripped = text.strip()
        if not stripped:
            return
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SourceReadError(f"cannot parse JSON array {self._locator}: {exc}") from exc
        if not isinstance(document, list):
            raise SourceReadError(
                f"JSON source {self._locator} is a {type(document).__name__}, expected an array "
                "of objects (use mode='lines' for JSON Lines)"
            )
        for index, element in enumerate(document):
            yield self._to_record(index, element, fragment=f"index={index}")

    def _read_lines(self, text: str) -> Iterator[SourceRecord]:
        index = 0
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                element: object = json.loads(line)
            except json.JSONDecodeError as exc:
                # One bad line is one bad record — not a dead run.
                yield SourceRecord(
                    index=index,
                    coordinates=self._coordinates(f"line={line_number}"),
                    data={},
                    issues=(
                        RecordIssue(
                            code="malformed_json",
                            message=f"line {line_number} is not valid JSON: {exc.msg}",
                        ),
                    ),
                )
                index += 1
                continue
            yield self._to_record(index, element, fragment=f"line={line_number}")
            index += 1

    def _coordinates(self, fragment: str) -> SourceCoordinates:
        return SourceCoordinates(
            source_type=self._source_type, locator=self._locator, fragment=fragment
        )

    def _to_record(self, index: int, element: object, *, fragment: str) -> SourceRecord:
        if isinstance(element, dict):
            # JSON object keys are always strings; the cast is safe and keeps
            # `data` honestly typed as dict[str, object].
            data: dict[str, object] = {str(key): value for key, value in element.items()}
            return SourceRecord(
                index=index, coordinates=self._coordinates(fragment), data=data
            )
        return SourceRecord(
            index=index,
            coordinates=self._coordinates(fragment),
            data={},
            issues=(
                RecordIssue(
                    code="not_an_object",
                    message=(
                        f"expected a JSON object, got {type(element).__name__}: "
                        f"{element!r}"
                    ),
                ),
            ),
        )
