import pytest
from pydantic import ValidationError

from kg_contracts.versioning import (
    CONTRACT_VERSION,
    CompatibilityClass,
    VersionChange,
    VersionedComponentKind,
)


def test_contract_version_is_semver_2():
    assert CONTRACT_VERSION.startswith("2.")


def test_version_change_valid():
    vc = VersionChange(
        component_kind=VersionedComponentKind.EXTRACTOR,
        component_name="player-extractor",
        from_version="1.2.0",
        to_version="2.0.0",
        compatibility=CompatibilityClass.REQUIRES_RE_EXTRACTION,
    )
    assert vc.compatibility is CompatibilityClass.REQUIRES_RE_EXTRACTION


def test_introduction_must_be_backward_compatible():
    with pytest.raises(ValidationError, match="introduction"):
        VersionChange(
            component_kind=VersionedComponentKind.PROMPT,
            component_name="p", from_version=None, to_version="1.0.0",
            compatibility=CompatibilityClass.REQUIRES_GRAPH_MIGRATION,
        )


def test_all_compatibility_classes_present():
    assert {c.value for c in CompatibilityClass} == {
        "BACKWARD_COMPATIBLE", "REQUIRES_CANDIDATE_REVALIDATION",
        "REQUIRES_RE_EXTRACTION", "REQUIRES_GRAPH_MIGRATION",
        "REQUIRES_DERIVED_INDEX_REBUILD",
    }
