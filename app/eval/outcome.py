"""判对层级与区间估计：报告 v2 的 `outcome` 块（规格 §3.2）。

单独成模块而不塞进 `report.py`，因为 `scripts/eval/compare.py` 要对
`schema_version=1` 的旧报告**现算**同一套数字：两边各写一份，迟早会漂移，
届时"A 的严格率"和"B 的严格率"用的是两套算法，比较本身就是假的。

纯函数：入参是逐题行 `list[dict]`，不出网、不读文件、不 import 被测系统。

## 严格率的分母

分母是**判对的题**，不是全部题。用全部题做分母会把"答错"和"判得松"
混成一个数：一个模型答错 30 题、剩下的全 strict，严格率会被压到 70%，
看起来像"比较器放宽了"，实际是"它答错了"。这是规格点名的陷阱。

## 为什么会有 unknown

`match` 键晚于最早那批评测报告。那些行判对了也无法得知靠哪一层，
把 None 当 strict 会让旧报告的严格率凭空变高，当 relaxed 会让它凭空变低。
两种都是编数。这里显式记 `unknown_tier`，并把 `strict_rate` 置 None ——
"算不出来"是一个诚实的答案，"大概多少"不是。
"""
from __future__ import annotations

from collections import Counter

from app.eval.stats import mde_flips, wilson

# comparator 的五级 + refusal（应拒答题走单独分支判定）。
# 顺序即报告里的书写顺序，`tier_mix` 用同一顺序，方便人眼逐行对照。
TIERS = ("strict", "rounded", "scaled", "extras", "relaxed", "refusal")

# 判对时算"判得严"的层级。rounded 是"舍入后相等"，已经放宽一层，不算 strict。
STRICT_TIER = "strict"


def _norm(row: dict) -> dict:
    """把报告里的结果行摊平成 `{id, correct, match, category, dataset}`。

    `report.py` 的行长得像 `{"case": <Case>, "correct": ...}`，id/category/dataset
    挂在 Case 对象上；`compare.py` 的行是扁平的。两种都要能进来 —— 否则两处各写
    一份字段映射，改一处漏一处，出来的严格率就不是同一个东西了。
    """
    c = row.get("case")
    if c is None:
        return row
    return {
        "id": getattr(c, "id", None),
        "correct": row.get("correct"),
        "match": row.get("match"),
        "category": getattr(c, "category", None),
        "dataset": getattr(c, "dataset", None),
    }


def tier_of(row: dict) -> str | None:
    """判对时靠的是哪一层；判错、或老报告没记 `match` 时返回 None。"""
    row = _norm(row)
    if not row.get("correct"):
        return None
    return row.get("match")


def _group(rows: list[dict], key: str) -> dict:
    """按某字段分组算 correct/n；缺该字段的行不进分组（不编一个 None 组）。"""
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        g = r.get(key)
        if g is None:
            continue
        buckets.setdefault(str(g), []).append(r)
    return {
        g: {"correct": sum(1 for r in items if r.get("correct")), "n": len(items)}
        for g, items in sorted(buckets.items())
    }


def build(rows: list[dict], *, alpha: float = 0.05) -> dict:
    """出一份 `outcome` 块。`rows` 是逐题行，`correct` 键必须已经定好。"""
    if not 0 < alpha < 1:
        raise ValueError(f"alpha={alpha} 超出 (0, 1)")

    rows = [_norm(r) for r in rows]
    n = len(rows)
    correct = sum(1 for r in rows if r.get("correct"))
    tiers = Counter(tier_of(r) for r in rows if r.get("correct"))
    unknown = tiers.pop(None, 0)
    strict = tiers.get(STRICT_TIER, 0)

    # 分母不干净（有一批评对却不知道靠哪层）时不给数，见模块 docstring。
    strict_rate = round(100.0 * strict / correct, 1) if correct and not unknown else None

    lo, hi = wilson(correct, n) if n else (0.0, 1.0)
    k_mde = mde_flips(alpha)

    out = {
        "n": n,
        "correct": correct,
        "accuracy": round(100.0 * correct / n, 1) if n else None,
        "strict": strict,
        "strict_rate": strict_rate,
        "tier_mix": {t: tiers.get(t, 0) for t in TIERS},
        "wilson95": [round(lo * 100, 1), round(hi * 100, 1)],
        "wilson_halfwidth_pp": round((hi - lo) / 2 * 100, 1),
        "mcnemar_mde_flips": k_mde,
        # 在 n 道题上，k 个单向翻转等价于多少个百分点 —— 读报告的人不用自己换算。
        # n < k 时这个数会超过 100（3 题上要 6 个翻转 = 200pp），不是算错：
        # 它的意思是"这批题无论怎么翻也到不了显著"，`mde_reachable` 把这个意思写明。
        "mde_equiv_pp": round(100.0 * k_mde / n, 1) if n else None,
        "mde_reachable": n >= k_mde,
        "by_category": _group(rows, "category"),
        "by_dataset": _group(rows, "dataset"),
    }
    if unknown:
        out["unknown_tier"] = unknown
    # 判对但不是 strict 的题：比较器放行过，应人工抽审。
    out["needs_audit"] = [
        r.get("id") for r in rows
        if r.get("correct") and r.get("match") not in (None, STRICT_TIER)
    ]
    return out
