import math

import pytest

from app.eval import stats


def test_wilson_23_of_25():
    lo, hi = stats.wilson(23, 25)
    assert abs(lo - 0.750) < 0.001
    assert abs(hi - 0.978) < 0.001


def test_wilson_117_of_130():
    lo, hi = stats.wilson(117, 130)
    assert abs(lo - 0.836) < 0.001
    assert abs(hi - 0.941) < 0.001


def test_wilson_degenerate_cases():
    """Wald 在 k=0 时会给出负数下界；Wilson 不会。"""
    assert stats.wilson(0, 25) == (0.0, pytest.approx(0.1332, abs=1e-4))
    lo, hi = stats.wilson(25, 25)
    assert abs(hi - 1.0) < 1e-12 and abs(lo - 0.8668) < 1e-4
    assert stats.wilson(0, 0) == (0.0, 1.0)


def test_wilson_rejects_out_of_range():
    with pytest.raises(ValueError):
        stats.wilson(26, 25)


def test_mcnemar_6_0():
    assert abs(stats.mcnemar_exact(6, 0) - 0.0312) < 1e-4


def test_mcnemar_5_0_not_significant():
    assert abs(stats.mcnemar_exact(5, 0) - 0.0625) < 1e-9


def test_mcnemar_12_4():
    assert abs(stats.mcnemar_exact(12, 4) - 0.0768) < 1e-4


def test_mcnemar_symmetric_and_trivial():
    assert abs(stats.mcnemar_exact(4, 12) - 0.0768) < 1e-4
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(3, 3) == 1.0


def test_mcnemar_never_exceeds_one():
    """b 与 c 接近时 2×尾部可能超过 1，必须截断——否则 p 值会印出 1.5。"""
    for b in range(0, 8):
        for c in range(0, 8):
            assert stats.mcnemar_exact(b, c) <= 1.0
    assert stats.mcnemar_exact(1, 0) == 1.0


def test_mde_flips_is_six():
    assert stats.mde_flips() == 6
    # 5:0 不显著、6:0 显著，这是 6 这个数字的全部依据
    assert stats.mcnemar_exact(5, 0) >= 0.05 > stats.mcnemar_exact(6, 0)


def test_percentile_nearest_rank():
    assert stats.percentile(list(range(1, 11)), 0.5) == 5
    assert stats.percentile([1, 2, 3, 4], 0.75) == 3
    assert stats.percentile([1, 2, 3, 4], 1.0) == 4
    assert stats.percentile([7], 0.0) == 7


def test_percentile_bounds():
    with pytest.raises(ValueError):
        stats.percentile([], 0.5)
    with pytest.raises(ValueError):
        stats.percentile([1, 2], 1.5)


def test_bootstrap_same_seed_same_result():
    vals = [0.8, 0.9, 0.85, 0.95, 0.7, 0.88, 0.92]
    a = stats.bootstrap_mean_ci(vals, n=500, seed=42)
    b = stats.bootstrap_mean_ci(vals, n=500, seed=42)
    assert a == b
    assert a[0] <= sum(vals) / len(vals) <= a[1]


def test_bootstrap_passes_seed_to_its_own_rng(monkeypatch):
    """不直接断言"不同 seed 结果必不同"：样本值少时 bootstrap 均值只有有限几档，
    最近秩分位会落在同一档上，两个 seed 给同一对边界是正常的（也说明边界只从样本取值）。
    要验的是 seed 真的被用上了。"""
    seen = {}
    real = stats.random.Random

    def spy(seed=None):
        seen["seed"] = seed
        return real(seed)

    monkeypatch.setattr(stats.random, "Random", spy)
    stats.bootstrap_mean_ci([0.1, 0.5, 0.9], n=10, seed=7)
    assert seen["seed"] == 7


def test_bootstrap_does_not_touch_global_random():
    """用全局 random 时，结果会取决于调用顺序——报告就没法复现。"""
    import random as _random
    _random.seed(123)
    before = _random.random()
    _random.seed(123)
    stats.bootstrap_mean_ci([1.0, 2.0, 3.0], n=100, seed=7)
    assert _random.random() == before


def test_bootstrap_constant_sample_collapses():
    lo, hi = stats.bootstrap_mean_ci([0.5] * 5, n=100)
    assert lo == hi == 0.5


def test_pass_metrics_denominator_is_case_count():
    passes = [3, 2, 1, 0]
    assert stats.pass_at_1(passes, 3) == 0.75
    assert stats.pass_pow_k(passes, 3) == 0.25
    assert stats.pass_pow_k([3, 3, 3, 3], 3) == 1.0
    assert stats.pass_at_1([], 3) is None
    assert stats.pass_pow_k([1, 1], 0) is None


def test_flip_rate_symmetric_at_k3():
    """k=3 时 passes=1 与 passes=2 必须同为 0.67：这是 spec 点名的错法。"""
    assert abs(stats.flip_rate(1, 3) - 2 / 3) < 1e-12
    assert abs(stats.flip_rate(2, 3) - 2 / 3) < 1e-12
    assert stats.flip_rate(0, 3) == 0.0
    assert stats.flip_rate(3, 3) == 0.0


def test_flip_rate_k2_one_flip_is_one():
    assert stats.flip_rate(1, 2) == 1.0


def test_flip_rate_rejects_bad_k():
    with pytest.raises(ValueError):
        stats.flip_rate(1, 1)
    with pytest.raises(ValueError):
        stats.flip_rate(4, 3)


def test_flip_rate_upper_bound_is_half():
    """min(passes,k-passes)/k 的上限是 0.5，0.4 门槛几乎永不触发。
    正确的式子在 k 为偶数时能到 0.5，k 为奇数时略高于 0.5。"""
    assert abs(max(stats.flip_rate(p, 4) for p in range(5)) - 4 / 6) < 1e-12
    assert max(stats.flip_rate(p, 5) for p in range(6)) > 0.5
