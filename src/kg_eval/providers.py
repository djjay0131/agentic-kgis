"""Pluggable metric providers — the seam for KGCS metrics, kept import-free.

`kg_eval` ships extraction metrics (the KGIS-owned half of ADR-0009). The
resolution/curation and graph-outcome halves are KGCS's, and they land later.
To let them plug in *without* `kg_eval` ever importing `kgcs` (which would
invert the dependency and couple the two repos), every metric family is a
`MetricProvider`: a name plus an `evaluate(output, gold) -> {metric: value}`.
KGCS will register its own providers (pairwise/cluster P/R, false-merge rate,
review yield, ...) against a `MetricProviderRegistry` at *its* call site; here
we only define the contract and register the one provider we own.

The provider surface intentionally speaks in `MetricValue`, so honest-null
crosses the seam intact: a KGCS provider that cannot measure calibration error
returns `MetricValue.insufficient(...)`, exactly as extraction metrics do.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from kg_eval.arms import ArmOutput
from kg_eval.bootstrap import BootstrapConfig
from kg_eval.goldset import GoldSet
from kg_eval.metrics import MetricValue, OntologySpec, evaluate_extraction


@runtime_checkable
class MetricProvider(Protocol):
    """A named source of metrics for one arm output against a gold set.

    Implementations return a flat mapping of metric name to `MetricValue` so
    honest-null survives the boundary. KGCS ER/review providers implement this
    without `kg_eval` importing them.
    """

    @property
    def name(self) -> str: ...

    def evaluate(self, output: ArmOutput, gold: GoldSet) -> Mapping[str, MetricValue]: ...


class ExtractionMetricProvider:
    """The one provider `kg_eval` owns: flattens `ExtractionMetrics` to a map.

    Precision/recall/F1 for each category plus abstention/failure rates are
    surfaced as `MetricValue`s; the integer counts (hallucinations, unsupported
    assertions, ontology violations) are exposed through `evaluate_extraction`
    directly and are not part of this flat metric map.
    """

    name = "extraction"

    def __init__(
        self,
        *,
        ontology: OntologySpec | None = None,
        boot: BootstrapConfig | None = None,
    ) -> None:
        self._ontology = ontology
        self._boot = boot

    def evaluate(self, output: ArmOutput, gold: GoldSet) -> Mapping[str, MetricValue]:
        m = evaluate_extraction(output, gold, ontology=self._ontology, boot=self._boot)
        result: dict[str, MetricValue] = {}
        for category, prf in (("entity", m.entity), ("relation", m.relation), ("attribute", m.attribute)):
            result[f"{category}.precision"] = prf.precision
            result[f"{category}.recall"] = prf.recall
            result[f"{category}.f1"] = prf.f1
        result["evidence.resolvable_rate"] = m.evidence.resolvable_rate
        result["evidence.span_coverage_rate"] = m.evidence.span_coverage_rate
        result["abstention_rate"] = m.abstention_rate
        result["failure_rate"] = m.failure_rate
        return result


class MetricProviderRegistry:
    """A simple name -> provider registry for composing metric families.

    Deterministic: `evaluate_all` visits providers in registration order and
    namespaces each metric as `<provider>.<metric>`, so a KGCS resolution
    provider and the extraction provider never collide.
    """

    def __init__(self) -> None:
        self._providers: dict[str, MetricProvider] = {}

    def register(self, provider: MetricProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"metric provider already registered: {provider.name!r}")
        self._providers[provider.name] = provider

    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def evaluate_all(self, output: ArmOutput, gold: GoldSet) -> dict[str, MetricValue]:
        merged: dict[str, MetricValue] = {}
        for name, provider in self._providers.items():
            for metric, value in provider.evaluate(output, gold).items():
                merged[f"{name}.{metric}"] = value
        return merged
