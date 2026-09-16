import json
import pytest
from pydantic import BaseModel, ConfigDict
from kg_contracts._frozen import FrozenMapping, FrozenDictObject
from kg_contracts.curation import CurationOperation, CurationOperationType


def test_frozen_mapping_rejects_mutation():
    m = FrozenMapping({"a": 1})
    assert m["a"] == 1
    assert dict(m) == {"a": 1}
    with pytest.raises(TypeError):
        m["a"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        del m["a"]  # type: ignore[attr-defined]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    payload: FrozenDictObject


def test_frozen_dict_field_is_immutable_and_round_trips():
    m = _Model(payload={"x": 1, "y": "z"})
    assert m.payload["x"] == 1
    with pytest.raises(TypeError):
        m.payload["x"] = 999  # type: ignore[index]
    dumped = m.model_dump_json()
    assert json.loads(dumped) == {"payload": {"x": 1, "y": "z"}}
    assert _Model.model_validate_json(dumped) == m


def test_frozen_mapping_serializes_natively_as_dict_under_object():
    # Regression: a FrozenMapping nested as an opaque ``object`` value must
    # serialize byte-identically to the plain dict it wraps. Pydantic serializes
    # ``object``-typed values by runtime type inference, which handles dict
    # subclasses but not a bare Mapping (that raised "Unable to serialize
    # unknown type").
    class Holder(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        box: dict[str, object]

    val = {"a": 1, "b": [1, 2], "c": {"nested": True}}
    frozen = Holder(box={"payload": FrozenMapping(val)})
    plain = Holder(box={"payload": dict(val)})
    assert frozen.model_dump_json() == plain.model_dump_json()
    assert json.loads(frozen.model_dump_json()) == {"box": {"payload": val}}
    assert Holder.model_validate_json(frozen.model_dump_json()) == frozen


def test_curation_operation_nested_frozen_payload_round_trips():
    # The load-bearing case (ADR-0010, KGCS executor/compensation seam): one
    # operation's frozen ``payload`` nested under another's ``reversal_data``.
    op = CurationOperation(
        type=CurationOperationType.ATTACH_ASSERTION, payload={"a": 1}, reversal_data={}
    )
    assert isinstance(op.payload, FrozenMapping)
    nested = CurationOperation(
        type=CurationOperationType.RETRACT_ASSERTION,
        payload={},
        reversal_data={"original_payload": op.payload},
    )
    dumped = nested.model_dump_json()  # PydanticSerializationError before the fix
    assert json.loads(dumped)["reversal_data"] == {"original_payload": {"a": 1}}
    assert CurationOperation.model_validate_json(dumped) == nested
