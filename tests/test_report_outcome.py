"""`outcome` 块（规格 §3.2）—— 严格率的分母与"算不出来"的诚实表达。"""
from __future__ import annotations

import pytest

from app.eval.outcome import TIERS, build, tier_of


def _rows(*specs) -> list[dict]:
    """`(id, correct, match)` → 逐题行。`match=None` 表示老报告没记这一层。"""
    out = []
    for spec in specs:
        if len(spec) == 2:
            cid, ok = spec
            match = "strict" if ok else None
        else:
            cid, ok, match = spec
        out.append({"id": cid, "correct": ok, "match": match})
    return out


def test_strict_rate_denominator_is_correct_answers_not_all():
    """答错 30 题不该把严格率压下去：分母是判对的题。"""
    rows = _rows(
        ("a", True, "strict"), ("b", True, "strict"), ("c", True, "relaxed"),
        ("d", False, None), ("e", False, None), ("f", False, None),
    )
    o = build(rows)
    assert (o["n"], o["correct"]) == (6, 3)
    assert o["accuracy"] == 50.0
    # 2/3 而不是 2/6
    assert o["strict"] == 2
    assert o["strict_rate"] == 66.7


def test_rounded_is_not_strict():
    """`rounded` 是舍入后相等，已经放宽一层 —— 算进 strict 就是自己骗自己。"""
    rows = _rows(("a", True, "rounded"), ("b", True, "strict"))
    o = build(rows)
    assert o["strict"] == 1
    assert o["strict_rate"] == 50.0
    assert o["tier_mix"]["rounded"] == 1
    assert o["needs_audit"] == ["a"]


def test_unknown_tier_makes_strict_rate_unavailable():
    """老报告没记 `match`：算不出来就是算不出来，不当成 strict 也不当成 relaxed。"""
    rows = _rows(("a", True, "strict"), ("b", True, None))  # b 没写 match
    o = build(rows)
    assert o["unknown_tier"] == 1
    assert o["strict_rate"] is None
    assert o["strict"] == 1  # 已知的那个仍照实报
    # 不知道层级的不进 needs_audit（没有"放宽"的证据）
    assert o["needs_audit"] == []


def test_all_wrong_has_no_strict_rate():
    rows = _rows(("a", False), ("b", False))
    o = build(rows)
    assert o["correct"] == 0
    assert o["accuracy"] == 0.0
    assert o["strict_rate"] is None  # 分母为 0


def test_tier_mix_lists_every_tier_even_when_zero():
    """缺层写 0 而不是省略：读的人要能一眼看出"这批没有 relaxed"。"""
    o = build(_rows(("a", True, "strict")))
    assert set(o["tier_mix"]) == set(TIERS)
    assert o["tier_mix"]["refusal"] == 0


def test_wilson_is_percent_and_matches_stats():
    from app.eval.stats import wilson

    o = build(_rows(*[(f"c{i}", True) for i in range(45)] + [(f"x{i}", False) for i in range(15)]))
    lo, hi = wilson(45, 60)
    assert o["wilson95"] == [round(lo * 100, 1), round(hi * 100, 1)]
    assert o["wilson_halfwidth_pp"] == round((hi - lo) / 2 * 100, 1)
    # 百分数量级，不是 0~1 的小数
    assert 60 < o["wilson95"][0] < o["wilson95"][1] <= 100


def test_mde_equiv_pp_is_flips_over_n():
    """6 个单向翻转在 63 题上等价 9.5pp —— 报告里直接给，别让人自己换算。"""
    o = build(_rows(*[(f"c{i}", True) for i in range(63)]))
    assert o["mcnemar_mde_flips"] == 6
    assert o["mde_equiv_pp"] == round(600.0 / 63, 1)


def test_mde_follows_alpha():
    loose = build(_rows(("a", True)), alpha=0.10)
    tight = build(_rows(("a", True)), alpha=0.01)
    assert loose["mcnemar_mde_flips"] < tight["mcnemar_mde_flips"]


def test_alpha_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        build([], alpha=0.0)
    with pytest.raises(ValueError):
        build([], alpha=1.0)


def test_empty_report_does_not_crash():
    o = build([])
    assert o["n"] == 0
    assert o["accuracy"] is None
    assert o["strict_rate"] is None
    assert o["mde_equiv_pp"] is None


def test_by_category_and_dataset_only_count_present_rows():
    rows = [
        {"id": "a", "correct": True, "match": "strict", "category": "agg", "dataset": "air"},
        {"id": "b", "correct": False, "match": None, "category": "agg", "dataset": "air"},
        {"id": "c", "correct": True, "match": "strict", "category": "ts", "dataset": "rental"},
        {"id": "d", "correct": True, "match": "strict"},  # 无分组字段 → 不进任何组
    ]
    o = build(rows)
    assert o["by_category"]["agg"] == {"correct": 1, "n": 2}
    assert o["by_category"]["ts"] == {"correct": 1, "n": 1}
    assert sum(v["n"] for v in o["by_category"].values()) == 3
    assert o["by_dataset"]["air"] == {"correct": 1, "n": 2}


def test_tier_of_only_counts_correct_rows():
    """判错的行不该有层级 —— 它压根没判对。"""
    assert tier_of({"correct": False, "match": "strict"}) is None
    assert tier_of({"correct": True, "match": "relaxed"}) == "relaxed"
    assert tier_of({"correct": True}) is None


def test_accepts_report_rows_with_case_wrapper():
    """`report.py` 的行是 `{"case": <Case>, "correct": ...}`，id/category 挂在 case 上。

    这条不测就会出现最坏情况：`report.py` 里 outcome 全是 None、`compare.py`
    现算的全是对的，两边数字不一样，而单测各自都过。
    """
    from types import SimpleNamespace

    rows = [
        {"case": SimpleNamespace(id="a", category="agg", dataset="air"),
         "correct": True, "match": "strict"},
        {"case": SimpleNamespace(id="b", category="agg", dataset="air"),
         "correct": True, "match": "relaxed"},
        {"case": SimpleNamespace(id="c", category="ts", dataset="rental"),
         "correct": False, "match": None},
    ]
    o = build(rows)
    assert (o["correct"], o["strict"], o["strict_rate"]) == (2, 1, 50.0)
    assert o["needs_audit"] == ["b"]
    assert o["by_category"]["agg"] == {"correct": 2, "n": 2}
    assert o["by_dataset"]["rental"] == {"correct": 0, "n": 1}
