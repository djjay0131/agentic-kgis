"""Read-only mapping field type for at-rest immutability (Issue #7).

Pydantic `frozen=True` blocks attribute reassignment but not in-place
mutation of dict-typed fields. `FrozenDict` coerces such a field to a
`FrozenMapping` at validation while preserving the plain-dict JSON
round-trip that `CurationPlan` and the ledger depend on.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Annotated, NoReturn, TypeAlias, TypeVar

from pydantic import PlainSerializer, TypeAdapter
from pydantic.functional_validators import PlainValidator

VT = TypeVar("VT")


class FrozenMapping(dict[str, object]):
    """An immutable, dict-backed read-only mapping.

    Subclasses ``dict`` (rather than wrapping one behind ``Mapping``) on
    purpose. Pydantic serializes ``object``/``Any``-typed values by *runtime
    type inference*, which only emits types it recognizes natively: a plain
    ``Mapping`` subclass raises ``Unable to serialize unknown type`` the moment
    a frozen payload is nested as an opaque ``object`` value inside another
    model's ``dict[str, object]`` field (KGCS's executor/compensation seam,
    ADR-0010), whereas a ``dict`` subclass is serialized as a dict *everywhere*.

    Immutability — the reason this type exists (Issue #7) — is preserved by
    making every in-place mutator raise ``TypeError``. Construction goes through
    the C-level ``dict`` constructor, which populates without calling the
    blocked ``__setitem__``, so ``FrozenMapping({...})`` still works. Because the
    data lives in the dict itself, ``model_dump_json`` output is byte-identical
    to the plain dict the value was built from, and the ``CurationPlan`` /
    ``CurationOperation`` JSON round-trip stays exact.
    """

    __slots__ = ()

    def __setitem__(self, key: str, value: object) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def __delitem__(self, key: str) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def __ior__(self, other: object) -> NoReturn:  # type: ignore[misc]
        raise TypeError("FrozenMapping is read-only")

    def clear(self) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def pop(self, *args: object) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def popitem(self) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def setdefault(self, *args: object) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def update(self, *args: object, **kwargs: object) -> NoReturn:
        raise TypeError("FrozenMapping is read-only")

    def __repr__(self) -> str:
        return f"FrozenMapping({dict.__repr__(self)})"

    # copy / pickle must rebuild through the constructor, never the blocked
    # mutators, or a deep-copy of a model holding a FrozenMapping would raise.
    def __copy__(self) -> FrozenMapping:
        return FrozenMapping(self)

    def __deepcopy__(self, memo: dict[int, object]) -> FrozenMapping:
        return FrozenMapping({k: copy.deepcopy(v, memo) for k, v in self.items()})

    def __reduce__(self) -> tuple[type[FrozenMapping], tuple[dict[str, object]]]:
        return (FrozenMapping, (dict(self),))


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
