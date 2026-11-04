"""成本与延迟（规格 §EV-C5）：每正确回答多少 token、p50/p95 落在哪。

## 口径写死在规格里，别改

`p50/p95` 用**最近秩**：排序后取 `ceil(p·n)-1` 号元素。**不用插值** ——
pandas / numpy 的默认插值口径跨版本变过，同一份报告在 3.11 和 3.12 上能算出
两个 p95，那这个数就不能进台账。

## 三个陷阱（规格点名）

1. **`tokens=None` 不能当 0**。当 0 会把 p50 直接拉低一截 —— 缺数和"用了 0 个 token"
   是两件事。
2. **`tokens_estimated=True` 要单列**。估算值混进"真数"的 p95，等于用一个猜的数
   定门槛。`n_reported` / `n_estimated` 分开报，读的人自己判断这批数可信不可信。
3. **`per_correct_tokens` 的分母是判对的题数**，不是总题数。分母 0 → `None`，
   不是 0（0 的意思是"免费"，那是错的）。

## 为什么单独成模块

`report.py` 要给新报告算这块，`render.py` 要给没有这块的旧报告现算。
两处各写一份，p50 的舍入和 `n_estimated` 的口径迟早不同，届时报废两份报告
比的是两个成本。和 `outcome.py` 同一个理由。

## 为什么没有金额

网关单价没进仓库（会变，且不同 provider 不同）。这里只给 token 与秒数，
金额由调用方乘。给一个硬编码价格等于埋一个过期常数。
"""
from __future__ import annotations

from math import ceil

# 这些键在报告里的名字，写死一处；render 与 report 都从这里取。
COST_KEYS = ("tokens_total", "tokens_per_case_p50", "tokens_per_case_p95",
             "per_correct_tokens", "duration_p50_s", "duration_p95_s",
             "n_reported", "n_estimated", "n_tokens", "n_duration")


def nearest_rank(values: list[float], p: float) -> float | None:
    """最近秩分位数：`ceil(p·n)-1` 号元素（0 基）。空列表 → None。"""
    if not values:
        return None
    if not 0 < p <= 1:
        raise ValueError(f"p={p} 超出 (0, 1]")
    s = sorted(values)
    idx = ceil(p * len(s)) - 1
    return s[min(max(idx, 0), len(s) - 1)]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build(rows: list[dict]) -> dict:
    """出一份 `cost` 块。`rows` 是逐题行（`report.py` 的 results 或 adapter 的 Row）。"""
    toks: list[int] = []
    durs: list[float] = []
    n_estimated = 0
    n_correct = 0
    for r in rows:
        get = r.get if isinstance(r, dict) else (lambda k, _r=r: getattr(_r, k, None))
        if get("correct"):
            n_correct += 1
        t = get("tokens")
        if _num(t):
            # 估算了就单列：它照旧进 p50/p95（否则样本太少），但要让人知道有几个是猜的。
            if get("tokens_estimated"):
                n_estimated += 1
            toks.append(int(t))
        d = get("duration_s")
        if _num(d):
            durs.append(float(d))

    total = sum(toks)
    return {
        "tokens_total": total,
        "tokens_per_case_p50": nearest_rank(toks, 0.50),
        "tokens_per_case_p95": nearest_rank(toks, 0.95),
        # 分母是判对的题；0 → None（0 的意思变成"免费"，那是假的）。
        "per_correct_tokens": round(total / n_correct, 1) if n_correct else None,
        "duration_p50_s": round(nearest_rank(durs, 0.50), 2) if durs else None,
        "duration_p95_s": round(nearest_rank(durs, 0.95), 2) if durs else None,
        # 覆盖面：多少题真的进了分母。没有这两列，读者会把 p50 当成"全部题"的。
        "n_reported": len(toks) - n_estimated,
        "n_estimated": n_estimated,
        "n_tokens": len(toks),
        "n_duration": len(durs),
    }
