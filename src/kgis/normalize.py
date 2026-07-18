"""Normalization: `SourceRecord` → `NormalizedRecord`. Deterministic and total.

This is the stage that erases the difference between formats. CSV says
`"42"`, JSON says `42`, and a Python dict might say either; after
normalization all three say `42`, which is what makes a CSV file and a list
of dicts produce byte-identical candidates. Nothing downstream needs to know
where a record came from.

Two properties are load-bearing:

- **Total.** `normalize()` never raises. A value that cannot be coerced
  becomes a `RecordIssue` on the returned record. A stage that raises on bad
  data cannot *report* on bad data, and it would drag rejection logic into
  every caller; validation stays the single place a record is rejected
  (spec §9: rejections are data).
- **Deterministic.** Same input, same output, every time — no clock, no
  locale, no randomness, no ambient state. Fields are processed in declared
  order, so even the `issues` tuple is stable.

Coercion is deliberately strict about the things that quietly corrupt a
graph. `True` is not the integer 1, a nested object is not its `repr()`, and
`"42.5"` is not the integer 42 — each of those is an error, not a silent
best-effort. A naive datetime *is* repaired (assumed UTC) but says so with a
warning, following the identity-model discipline from ADR-0008: repair when
the fix is unambiguous, otherwise reject naming the offending value.
"""

from datetime import UTC, datetime
from typing import Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from kgis.records import NormalizedRecord, RecordIssue, SourceRecord

FieldType = Literal["str", "int", "float", "bool", "datetime"]
"""The types normalization can produce. Deliberately small: these are the
types a structured row can honestly carry. Richer shapes belong to a
`CandidateBuilder`, which has the domain knowledge to interpret them."""

_TRUE_STRINGS = frozenset({"true", "t", "yes", "y", "1"})
_FALSE_STRINGS = frozenset({"false", "f", "no", "n", "0"})


class FieldSpec(BaseModel):
    """How one canonical field is read out of a source record.

    `aliases` lets a source's column name differ from the graph's field name
    (`player_id` → `id`) without a bespoke normalizer per source. Matching is
    case-insensitive and whitespace-trimmed, because a stray `" Name"` header
    from a spreadsheet is not a modeling decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    type: FieldType = "str"
    required: bool = False
    aliases: tuple[str, ...] = ()
    default: object = None
    empty_as_null: bool = True
    """Treat `""` as absent. CSV cannot distinguish an empty cell from a
    missing one, so this is on by default; set it False when the empty
    string is a real value in your domain."""

    def source_keys(self) -> tuple[str, ...]:
        """Every key this field answers to, canonical name first."""
        return (self.name, *self.aliases)


@runtime_checkable
class Normalizer(Protocol):
    """Maps a raw record onto canonical names and types (spec §6)."""

    def normalize(self, record: SourceRecord) -> NormalizedRecord:
        """Never raises. Bad values become issues on the returned record."""
        ...


def _match_key(key: str) -> str:
    """The key's comparison form: trimmed and case-folded."""
    return key.strip().casefold()


class PassthroughNormalizer:
    """Carries a record through untouched. For sources already canonical.

    Useful when a JSON source is already written in the graph's own field
    names and types — but note it inherits JSON's types verbatim, so it will
    *not* make a CSV and a JSON source agree. Use `SchemaNormalizer` for that.
    """

    def normalize(self, record: SourceRecord) -> NormalizedRecord:
        return NormalizedRecord(
            index=record.index,
            coordinates=record.coordinates,
            values=dict(record.data),
            issues=record.issues,
        )


class SchemaNormalizer:
    """Normalizes against a declared list of `FieldSpec`s.

    Keys the schema does not declare are preserved in `NormalizedRecord.extras`
    rather than discarded: "which columns did this source carry that my mapping
    ignores?" is exactly the question a dry run needs to answer, and you cannot
    answer it from data you threw away.
    """

    def __init__(self, fields: Sequence[FieldSpec]) -> None:
        self._fields = tuple(fields)
        self._claimed: dict[str, str] = {}
        for spec in self._fields:
            for key in spec.source_keys():
                match = _match_key(key)
                existing = self._claimed.get(match)
                if existing is not None and existing != spec.name:
                    raise ValueError(
                        f"field {spec.name!r} claims source key {key!r}, which field "
                        f"{existing!r} already claims — one column cannot feed two fields"
                    )
                self._claimed[match] = spec.name

    @property
    def fields(self) -> tuple[FieldSpec, ...]:
        return self._fields

    def normalize(self, record: SourceRecord) -> NormalizedRecord:
        lookup = {_match_key(key): value for key, value in record.data.items()}
        values: dict[str, object] = {}
        issues: list[RecordIssue] = list(record.issues)

        for spec in self._fields:
            raw, present = self._lookup(lookup, spec)
            if not present or self._is_absent(raw, spec):
                if spec.required:
                    issues.append(
                        RecordIssue(
                            code="missing_required",
                            message=f"required field {spec.name!r} is missing or empty",
                            field=spec.name,
                        )
                    )
                values[spec.name] = spec.default
                continue

            coerced, issue = _coerce(raw, spec)
            if issue is not None:
                issues.append(issue)
            values[spec.name] = coerced

        extras = {
            key: value
            for key, value in record.data.items()
            if _match_key(key) not in self._claimed
        }

        return NormalizedRecord(
            index=record.index,
            coordinates=record.coordinates,
            values=values,
            extras=extras,
            issues=tuple(issues),
        )

    def _lookup(self, lookup: dict[str, object], spec: FieldSpec) -> tuple[object, bool]:
        for key in spec.source_keys():
            match = _match_key(key)
            if match in lookup:
                return lookup[match], True
        return None, False

    def _is_absent(self, raw: object, spec: FieldSpec) -> bool:
        if raw is None:
            return True
        return spec.empty_as_null and isinstance(raw, str) and not raw.strip()


def _coerce(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    """Coerce `raw` to `spec.type`. Returns `(value, issue)`; never raises."""
    if spec.type == "str":
        return _coerce_str(raw, spec)
    if spec.type == "int":
        return _coerce_int(raw, spec)
    if spec.type == "float":
        return _coerce_float(raw, spec)
    if spec.type == "bool":
        return _coerce_bool(raw, spec)
    return _coerce_datetime(raw, spec)


def _failed(raw: object, spec: FieldSpec, why: str) -> tuple[object, RecordIssue]:
    """Reject naming the offending value (ADR-0008 discipline)."""
    return None, RecordIssue(
        code="coercion_failed",
        message=f"cannot read {raw!r} as {spec.type}: {why}",
        field=spec.name,
    )


def _coerce_str(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    if isinstance(raw, str):
        return raw.strip(), None
    if isinstance(raw, bool):
        # str(True) == "True" but JSON/CSV would write "true" — the casing is
        # a coin flip, and a coin flip in an entity key is a corrupt graph.
        return _failed(raw, spec, "a boolean has no unambiguous string form")
    if isinstance(raw, (int, float)):
        # Deliberate: JSON's 1 and CSV's "1" must become the same key, or the
        # two formats would produce different candidates for the same fact.
        return str(raw), None
    return _failed(raw, spec, f"{type(raw).__name__} is not a scalar")


def _coerce_int(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    if isinstance(raw, bool):
        return _failed(raw, spec, "a boolean is not an integer")
    if isinstance(raw, int):
        return raw, None
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw), None
        return _failed(raw, spec, "would lose the fractional part")
    if isinstance(raw, str):
        try:
            return int(raw.strip()), None
        except ValueError:
            return _failed(raw, spec, "not an integer literal")
    return _failed(raw, spec, f"{type(raw).__name__} is not a number")


def _coerce_float(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    if isinstance(raw, bool):
        return _failed(raw, spec, "a boolean is not a number")
    if isinstance(raw, (int, float)):
        return float(raw), None
    if isinstance(raw, str):
        try:
            return float(raw.strip()), None
        except ValueError:
            return _failed(raw, spec, "not a number")
    return _failed(raw, spec, f"{type(raw).__name__} is not a number")


def _coerce_bool(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, int):
        if raw in (0, 1):
            return bool(raw), None
        return _failed(raw, spec, "only 0 and 1 are boolean")
    if isinstance(raw, str):
        text = raw.strip().casefold()
        if text in _TRUE_STRINGS:
            return True, None
        if text in _FALSE_STRINGS:
            return False, None
        return _failed(
            raw, spec, f"expected one of {sorted(_TRUE_STRINGS | _FALSE_STRINGS)}"
        )
    return _failed(raw, spec, f"{type(raw).__name__} is not a boolean")


def _coerce_datetime(raw: object, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    if isinstance(raw, datetime):
        return _ensure_aware(raw, spec)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            return _failed(raw, spec, "not an ISO-8601 datetime")
        return _ensure_aware(parsed, spec)
    return _failed(raw, spec, f"{type(raw).__name__} is not a datetime")


def _ensure_aware(value: datetime, spec: FieldSpec) -> tuple[object, RecordIssue | None]:
    """Repair a naive datetime to UTC, but say so — an assumed timezone is a
    real assumption, and a bitemporal graph (spec §5.4) is exactly where a
    silent one does damage."""
    if value.tzinfo is not None:
        return value, None
    return value.replace(tzinfo=UTC), RecordIssue(
        code="assumed_utc",
        message=f"{value.isoformat()} has no timezone; assuming UTC",
        severity="warning",
        field=spec.name,
    )
