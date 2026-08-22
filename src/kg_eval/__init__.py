"""kg_eval: the honest-null evaluation harness (ADR-0009, spec §10.1).

The KGIS-owned half of the evaluation package: it grades extraction *arms*
(`ArmOutput`) against an extraction *gold set* (`GoldSet`) into reproducible
metrics, runs ablation comparisons under the honest-null policy, and renders
one result model to both JSON and Markdown.

Design commitments (ADR-0009):

- **Honest null over comfortable zero.** Every metric is a `MetricValue` that
  is `None` + a reason when it cannot be measured, never a fabricated 0.0; an
  ablation reports INSUFFICIENT_EVIDENCE or NO_IMPROVEMENT rather than a false
  win.
- **Determinism.** The only randomness is bootstrap resampling, and it draws
  from a caller-seeded RNG (`BootstrapConfig.seed`) — no wall-clock, no global
  RNG — so intervals and reports are byte-reproducible.
- **KGCS stays an extension point.** Resolution/curation and graph-outcome
  metrics plug in later via `MetricProvider`/`MetricProviderRegistry` without
  `kg_eval` importing `kgcs`.
"""

from kg_eval.ablation import AblationResult, AblationVerdict, compare_arms
from kg_eval.arms import ArmConfig, ArmOutput, CostLatency
from kg_eval.bootstrap import (
    BootstrapConfig,
    ConfidenceInterval,
    bootstrap_ci,
    bootstrap_diff_ci,
)
from kg_eval.goldset import (
    EvidenceSpan,
    GoldAttribute,
    GoldEntity,
    GoldRelation,
    GoldSet,
)
from kg_eval.matching import (
    CategoryMatch,
    canon_ref,
    match_attributes,
    match_entities,
    match_relations,
    norm_value,
)
from kg_eval.metrics import (
    PRF,
    EvidenceValidity,
    ExtractionMetrics,
    MetricValue,
    OntologySpec,
    evaluate_extraction,
)
from kg_eval.providers import (
    ExtractionMetricProvider,
    MetricProvider,
    MetricProviderRegistry,
)
from kg_eval.report import (
    ArmResult,
    EvaluationResult,
    evaluate_arms,
    render_json,
    render_markdown,
)

__all__ = [
    "PRF",
    # ablation
    "AblationResult",
    "AblationVerdict",
    # arms
    "ArmConfig",
    "ArmOutput",
    # report
    "ArmResult",
    # bootstrap
    "BootstrapConfig",
    # matching
    "CategoryMatch",
    "ConfidenceInterval",
    "CostLatency",
    "EvaluationResult",
    # gold set
    "EvidenceSpan",
    # metrics
    "EvidenceValidity",
    # providers
    "ExtractionMetricProvider",
    "ExtractionMetrics",
    "GoldAttribute",
    "GoldEntity",
    "GoldRelation",
    "GoldSet",
    "MetricProvider",
    "MetricProviderRegistry",
    "MetricValue",
    "OntologySpec",
    "bootstrap_ci",
    "bootstrap_diff_ci",
    "canon_ref",
    "compare_arms",
    "evaluate_arms",
    "evaluate_extraction",
    "match_attributes",
    "match_entities",
    "match_relations",
    "norm_value",
    "render_json",
    "render_markdown",
]
