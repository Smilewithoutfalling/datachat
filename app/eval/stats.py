"""评测用的统计函数：区间、精确检验、稳定性。

存在的理由是"只有一个实现"。在这之前，Wilson 区间在临时脚本里手算过好几遍，
McNemar 的 p 值也手推过——同一个数字两次算不一样，报告就没人信。

不引 scipy / statsmodels：本文件只用到二项分布的精确尾概率，
`math.comb` 加上一次求和就是全部，没必要为 20 行逻辑加一个新依赖（EV-C2）。
"""
from __future__ import annotations

import math
import random


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 得分区间。

    为什么不用 Wald（p̂ ± z·√(p̂(1-p̂)/n)）：n 小或 p̂ 接近 0/1 时它会给出负数
    或超过 1 的上界。25 题的闸门、9 条拒答题的分母都落在这个区间里。
    k=0 与 k=n 时 Wilson 仍给出有意义的单侧边界，Wald 直接退化成一个点。
    """
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= k <= n:
        raise ValueError(f"k={k} 超出 [0, {n}]")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    """配对比较的双侧精确 McNemar p 值。

    b / c 是两张"不一致"的题数：b = A 错 B 对，c = A 对 B 错。一致题不参与——
    把它们算进分母是最常见的错法（spec 里专门点名过）。

    在 H0（两种配置等价）下 b ~ Binomial(b+c, 0.5)，双侧就是把
    P(X ≤ min(b,c)) 乘 2 再截断到 1。b=c 时 p=1，不会出现 p=2×0.5=1 以外的怪值。
    """
    if b < 0 or c < 0:
        raise ValueError(f"b={b}, c={c} 不能为负")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def mde_flips(alpha: float = 0.05) -> int:
    """双侧精确 McNemar 达到 p < alpha 所需的最小单向翻转数（另一侧为 0）。

    alpha=0.05 时是 6：5:0 → p=0.0625 不显著，6:0 → p=0.0312 显著。
    这个数字是"25 题门禁最多能证明什么"的上限，写进报告是为了让读的人知道
    "3 题变好"根本不构成证据，而不是留给他自己去查表。
    """
    if not 0 < alpha < 1:
        raise ValueError(f"alpha={alpha} 超出 (0, 1)")
    k = 1
    while 2 * (0.5 ** k) >= alpha:
        k += 1
        if k > 10_000:  # 兜底：alpha 小到不现实时不至于死循环
            raise ValueError(f"alpha={alpha} 过小")
    return k


def percentile(sorted_values: list[float], p: float) -> float:
    """最近秩分位数：取第 ceil(p·n) 个（1 起算），而不是线性插值。

    用最近秩是因为它只从样本里取值。bootstrap 的 CI 若用插值，会在两个重采样
    均值之间造出一个从未出现过的数，报告里那个边界值就不可复现了。
    `sorted_values` 必须已升序——不在这里再排一次，是为了让调用方清楚这是约定，
    而不是每次调用都付一次排序的代价。
    """
    if not sorted_values:
        raise ValueError("空序列没有分位数")
    if not 0 <= p <= 1:
        raise ValueError(f"p={p} 超出 [0, 1]")
    n = len(sorted_values)
    idx = max(1, math.ceil(p * n))
    return sorted_values[min(idx, n) - 1]


def bootstrap_mean_ci(values: list[float], n: int = 2000, seed: int = 0,
                      alpha: float = 0.05) -> tuple[float, float]:
    """均值的 bootstrap 百分位区间。

    固定 seed 且用独立的 `random.Random(seed)`：报告要能被人拿同一份输入复现出
    同一对边界。用全局 random 会让"复现"取决于调用顺序——之前用脚本手算时踩过。
    """
    if not values:
        raise ValueError("空样本没有区间")
    if n <= 0:
        raise ValueError(f"n={n} 必须为正")
    if not 0 < alpha < 1:
        raise ValueError(f"alpha={alpha} 超出 (0, 1)")
    rng = random.Random(seed)
    size = len(values)
    means = []
    for _ in range(n):
        means.append(sum(values[rng.randrange(size)] for _ in range(size)) / size)
    means.sort()
    return (percentile(means, alpha / 2), percentile(means, 1 - alpha / 2))


# ------------------------------------------------------------------ 稳定性

def pass_at_1(passes: list[int], k: int) -> float | None:
    """k 次里至少对 1 次的题占比。passes: 每题对了几次。"""
    if not passes or k <= 0:
        return None
    return sum(1 for p in passes if p >= 1) / len(passes)


def pass_pow_k(passes: list[int], k: int) -> float | None:
    """k 次全对的题占比。分母是题数，不是运行数（写成 sum/k 是最容易犯的错）。"""
    if not passes or k <= 0:
        return None
    return sum(1 for p in passes if p >= k) / len(passes)


def flip_rate(passes: int, k: int) -> float:
    """任取两次运行、判定不一致的概率 = passes·(k−passes) / C(k,2)。

    不能写成 min(passes, k−passes)/k：k=3 时 passes=1 与 passes=2 应该同为 0.67
    （对称），那个式子给 0.33/0.67；而且它的上限是 0.5，0.4 的门槛几乎永不触发。
    """
    if k < 2:
        raise ValueError(f"k={k} < 2，谈不了翻转")
    if not 0 <= passes <= k:
        raise ValueError(f"passes={passes} 超出 [0, {k}]")
    return passes * (k - passes) / (k * (k - 1) / 2)
