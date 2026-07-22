"""Read-only mapping field type for at-rest immutability (Issue #7).

Pydantic `frozen=True` blocks attribute reassignment but not in-place
mutation of dict-typed fields. `FrozenDict` coerces such a field to a
`FrozenMapping` at validation while preserving the plain-dict JSON
round-trip that `CurationPlan` and the ledger depend on.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, TypeAlias, TypeVar

from pydantic import PlainSerializer, TypeAdapter
from pydantic.functional_validators import PlainValidator

VT = TypeVar("VT")


class FrozenMapping(Mapping[str, object]):
    """An immutable, hashable-free read-only mapping."""

    __slots__ = ("_data",)
    _data: dict[str, object]

    def __init__(self, data: Mapping[str, object]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self._data) == dict(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"


def _to_frozen(value: object) -> FrozenMapping:
    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(value)
    raise TypeError(f"expected a mapping, got {type(value).__name__}")


def _make_validator(value_type: type[VT]) -> Callable[[object], FrozenMapping]:
    """Build the `PlainValidator` callable for a `Mapping[str, value_type]`.

    Uses `PlainValidator` rather than `BeforeValidator`: with a *before*
    validator, pydantic still runs its own `Mapping[str, VT]` validation
    on the result afterward, which silently rebuilds a plain, mutable
    `dict` and defeats at-rest immutability. `PlainValidator` makes this
    callable the entire validation step, so the `FrozenMapping` it returns
    is what the field actually stores.
    """
    inner = TypeAdapter(dict[str, value_type])  # type: ignore[valid-type]

    def _validate(value: object) -> FrozenMapping:
        return _to_frozen(inner.validate_python(dict(_to_frozen(value))))

    return _validate


def frozen_dict(value_type: type[VT]) -> object:
    """Annotated `Mapping[str, VT]` that validates to a `FrozenMapping`.

    A general-purpose factory for dynamic `value_type`s (e.g. a nested
    model). Note for callers: mypy cannot recognize a function call's
    result as a type, so a field annotated with `frozen_dict(SomeType)`
    directly needs a local `# type: ignore[valid-type]` — unlike
    `FrozenDictObject`/`FrozenDictFloat` below, which are declared as
    literal `Annotated[...]` type aliases for exactly this reason and
    type-check cleanly wherever they're used.
    """
    return Annotated[
        Mapping[str, value_type],  # type: ignore[valid-type]
        PlainValidator(_make_validator(value_type)),
        PlainSerializer(lambda m: dict(m), return_type=dict),
    ]


FrozenDictObject: TypeAlias = Annotated[
    Mapping[str, object],
    PlainValidator(_make_validator(object)),
    PlainSerializer(lambda m: dict(m), return_type=dict),
]
FrozenDictFloat: TypeAlias = Annotated[
    Mapping[str, float],
    PlainValidator(_make_validator(float)),
    PlainSerializer(lambda m: dict(m), return_type=dict),
]
