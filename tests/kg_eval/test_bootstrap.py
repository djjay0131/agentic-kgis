"""Bootstrap intervals are deterministic given a seed and honest below min_items."""

from kg_eval import BootstrapConfig, bootstrap_ci, bootstrap_diff_ci


def test_same_seed_same_interval() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
    boot = BootstrapConfig(seed=123, n_resamples=500, min_items=8)
    a = bootstrap_ci(values, boot)
    b = bootstrap_ci(values, boot)
    assert a is not None and b is not None
    assert a == b  # bit-for-bit reproducible


def test_different_seed_can_differ_but_brackets_point() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
    a = bootstrap_ci(values, BootstrapConfig(seed=1, n_resamples=500, min_items=8))
    b = bootstrap_ci(values, BootstrapConfig(seed=2, n_resamples=500, min_items=8))
    assert a is not None and b is not None
    assert a.point == b.point  # the point estimate never depends on the seed
    assert a.lower <= a.point <= a.upper
    assert b.lower <= b.point <= b.upper


def test_too_few_items_is_none_not_a_fake_interval() -> None:
    boot = BootstrapConfig(seed=1, n_resamples=100, min_items=8)
    assert bootstrap_ci([1.0, 0.0, 1.0], boot) is None


def test_diff_ci_is_paired_and_deterministic() -> None:
    base = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    enh = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0]
    boot = BootstrapConfig(seed=9, n_resamples=500, min_items=8)
    a = bootstrap_diff_ci(base, enh, boot)
    b = bootstrap_diff_ci(base, enh, boot)
    assert a is not None and a == b
    assert a.excludes_zero_above  # enhanced clearly better


def test_diff_ci_none_on_misaligned_lengths() -> None:
    boot = BootstrapConfig(seed=1, n_resamples=100, min_items=2)
    assert bootstrap_diff_ci([1.0, 0.0], [1.0], boot) is None


def test_tie_straddles_zero() -> None:
    same = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    boot = BootstrapConfig(seed=5, n_resamples=500, min_items=8)
    ci = bootstrap_diff_ci(same, same, boot)
    assert ci is not None
    assert ci.lower == 0.0 and ci.upper == 0.0
    assert not ci.excludes_zero_above
    assert not ci.excludes_zero_below
