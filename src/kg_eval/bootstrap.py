"""Deterministic bootstrap confidence intervals.

Bootstrap resampling is the harness's one source of randomness, and ADR-0009
turns that into a hard rule: a confidence interval that changes between two
runs of the same data is not evidence, it is noise dressed as evidence. So the
resampling *never* reads wall-clock time or a process-global RNG — it draws
from a `random.Random` seeded by a caller-supplied integer (`BootstrapConfig`).
Given the same seed, the same values, and the same resample count, the interval
is bit-for-bit identical across machines and runs.

The other half of honest-null (ADR-0009) lives here too: a bootstrap over two
data points is not "a tight interval", it is "not enough data". When fewer than
`min_items` observations are available the estimators return `None` rather than
a fabricated interval, and downstream code renders that as "insufficient
evidence" instead of a comfortable-looking bound.

Paired resampling (`bootstrap_diff_ci`) applies the *same* draw of indices to
both arms, so the interval is over the per-item difference — the only correct
way to ask "did the enhanced arm beat the baseline on the same items?" without
letting independent resampling inflate the variance.
"""

from collections.abc import Sequence
from random import Random

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceInterval(BaseModel):
    """A bootstrap point estimate with a percentile confidence interval.

    `lower`/`upper` are the resampled percentile bounds; `point` is the
    statistic on the observed sample. `level` records the nominal coverage
    (e.g. 0.95) so a report never has to guess what the interval means.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    point: float
    lower: float
    upper: float
    level: float = Field(ge=0.0, le=1.0)
    n_resamples: int = Field(ge=1)
    n_items: int = Field(ge=0)

    @property
    def excludes_zero_above(self) -> bool:
        """True when the whole interval sits strictly above 0.

        This is the ablation win condition: a difference whose interval
        excludes 0 from below is an improvement the data actually support,
        not a point estimate that could be a coin flip.
        """
        return self.lower > 0.0

    @property
    def excludes_zero_below(self) -> bool:
        """True when the whole interval sits strictly below 0 (a regression)."""
        return self.upper < 0.0


class BootstrapConfig(BaseModel):
    """All the knobs that make a bootstrap reproducible — and nothing else.

    `seed` is mandatory and the only source of randomness: there is no
    "default to the system RNG" path, because that path is how a CI silently
    becomes irreproducible. `min_items` is the honest-null floor: below it the
    estimators refuse to invent an interval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    n_resamples: int = Field(default=1000, ge=1)
    level: float = Field(default=0.95, gt=0.0, lt=1.0)
    min_items: int = Field(default=8, ge=1)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence.

    `fraction` is in [0, 1]. Kept dependency-free (no numpy) and fully
    deterministic: the same inputs always yield the same output.
    """
    if not sorted_values:
        raise ValueError("percentile of an empty sequence is undefined")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = fraction * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _resample_means(values: Sequence[float], rng: Random, n_resamples: int) -> list[float]:
    """Draw `n_resamples` with-replacement resamples and return their means."""
    n = len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    return means


def bootstrap_ci(values: Sequence[float], config: BootstrapConfig) -> ConfidenceInterval | None:
    """Bootstrap CI for the mean of per-item indicators.

    `values` are per-item scalars (e.g. 1.0 for a recalled gold item, 0.0 for
    a missed one); the statistic is their mean (i.e. the rate). Returns `None`
    — never a zero-width or fabricated interval — when there are fewer than
    `config.min_items` observations, which the caller reports as insufficient
    evidence (ADR-0009).
    """
    if len(values) < config.min_items:
        return None
    rng = Random(config.seed)
    means = sorted(_resample_means(values, rng, config.n_resamples))
    tail = (1.0 - config.level) / 2.0
    point = sum(values) / len(values)
    return ConfidenceInterval(
        point=point,
        lower=_percentile(means, tail),
        upper=_percentile(means, 1.0 - tail),
        level=config.level,
        n_resamples=config.n_resamples,
        n_items=len(values),
    )


def bootstrap_diff_ci(
    baseline: Sequence[float],
    enhanced: Sequence[float],
    config: BootstrapConfig,
) -> ConfidenceInterval | None:
    """Paired bootstrap CI for the mean per-item difference (enhanced - baseline).

    The two sequences must be aligned per item (same gold item at each index).
    Each resample draws one set of indices and applies it to *both* arms, so
    the interval is over the paired difference — the correct test for "did the
    enhanced arm improve on the same items?". Returns `None` when the arms are
    misaligned or there are too few items (honest null, ADR-0009).
    """
    if len(baseline) != len(enhanced):
        return None
    n = len(baseline)
    if n < config.min_items:
        return None
    diffs = [enhanced[i] - baseline[i] for i in range(n)]
    rng = Random(config.seed)
    means = sorted(_resample_means(diffs, rng, config.n_resamples))
    tail = (1.0 - config.level) / 2.0
    point = sum(diffs) / n
    return ConfidenceInterval(
        point=point,
        lower=_percentile(means, tail),
        upper=_percentile(means, 1.0 - tail),
        level=config.level,
        n_resamples=config.n_resamples,
        n_items=n,
    )
