"""The provider seam: extraction metrics register, and honest-null crosses it.

Also stands in for the later KGCS ER/review providers — a tiny stub provider
registers alongside the extraction one without kg_eval importing anything from
kgcs, proving the extension point works.
"""

from collections.abc import Mapping
from pathlib import Path

from helpers import perfect_arm

from kg_eval import (
    ArmOutput,
    ExtractionMetricProvider,
    GoldSet,
    MetricProvider,
    MetricProviderRegistry,
    MetricValue,
)

FIXTURE = Path(__file__).parent / "fixtures" / "baseball_gold.json"


def gold() -> GoldSet:
    return GoldSet.from_json_file(FIXTURE)


class StubResolutionProvider:
    """Stands in for a future KGCS provider — no kgcs import required."""

    name = "resolution"

    def evaluate(self, output: ArmOutput, gold_set: GoldSet) -> Mapping[str, MetricValue]:
        # a metric it cannot measure yet is honest-null, not a fake zero
        return {"pairwise.f1": MetricValue.insufficient("resolution not implemented in kg_eval")}


def test_extraction_provider_flattens_metrics() -> None:
    provider = ExtractionMetricProvider()
    metrics = provider.evaluate(perfect_arm(), gold())
    assert metrics["entity.recall"].value == 1.0
    assert metrics["attribute.f1"].value == 1.0
    assert "evidence.resolvable_rate" in metrics


def test_extraction_provider_satisfies_protocol() -> None:
    assert isinstance(ExtractionMetricProvider(), MetricProvider)


def test_registry_namespaces_and_composes_providers() -> None:
    registry = MetricProviderRegistry()
    registry.register(ExtractionMetricProvider())
    registry.register(StubResolutionProvider())
    assert registry.names() == ("extraction", "resolution")

    merged = registry.evaluate_all(perfect_arm(), gold())
    assert merged["extraction.entity.recall"].value == 1.0
    # the KGCS-style provider's honest-null value survives the seam intact
    assert merged["resolution.pairwise.f1"].value is None
    assert merged["resolution.pairwise.f1"].sufficient is False


def test_duplicate_registration_is_rejected() -> None:
    registry = MetricProviderRegistry()
    registry.register(ExtractionMetricProvider())
    try:
        registry.register(ExtractionMetricProvider())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("expected duplicate registration to raise")
