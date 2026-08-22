import pytest
from pydantic import ValidationError

from kg_contracts.derivation import Derivation, DerivationInput


def test_derivation_minimal():
    d = Derivation(
        method="stud-count-v3",
        deterministic=True,
        inputs=(DerivationInput(kind="assertion", ref="as_01H"),),
        implementation_version="kgis-takeoff==0.2.0",
    )
    assert d.deterministic and d.reproducible


def test_derivation_requires_method_and_version():
    with pytest.raises(ValidationError):
        Derivation(method="", deterministic=True, inputs=(),
                   implementation_version="v1")
    with pytest.raises(ValidationError):
        Derivation(method="m", deterministic=True, inputs=(),
                   implementation_version="")


def test_derivation_frozen_and_carries_warnings():
    d = Derivation(method="wall-length", deterministic=True,
                   inputs=(), implementation_version="v1",
                   warnings=("scale inferred from title block",), units="mm")
    assert d.warnings[0].startswith("scale")
    with pytest.raises(ValidationError):
        d.method = "other"  # type: ignore[misc]


def test_derivation_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Derivation(method="wall-length", deterministic=True,
                   inputs=(), implementation_version="v1",
                   bogus=1)  # type: ignore[call-arg]


def test_derivation_parameters_frozen_including_omitted_default():
    # parameters omitted entirely -> default_factory=dict; must still be
    # frozen (validate_default=True), not a silently mutable plain dict.
    d = Derivation(method="m", deterministic=True, inputs=(),
                   implementation_version="v1")
    with pytest.raises(TypeError):
        d.parameters["x"] = 1  # type: ignore[index]

    d2 = Derivation(method="m", deterministic=True, inputs=(),
                    implementation_version="v1", parameters={"scale": 1.0})
    with pytest.raises(TypeError):
        d2.parameters["scale"] = 2.0  # type: ignore[index]
