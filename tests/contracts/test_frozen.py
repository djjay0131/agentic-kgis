import json
import pytest
from pydantic import BaseModel, ConfigDict
from kg_contracts._frozen import FrozenMapping, FrozenDictObject


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
