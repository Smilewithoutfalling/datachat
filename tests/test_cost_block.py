"""`cost` 块（规格 §EV-C5）—— 最近秩分位数，以及三个"不能当 0"的陷阱。"""
from __future__ import annotations

import pytest

from app.eval.cost import build, nearest_rank
from app.eval.report_adapter import Row, iter_rows


def _r(cid, ok, tokens=None, dur=None, est=False):
    return {"id": cid, "correct": ok, "tokens": tokens, "duration_s": dur,
            "tokens_estimated": est}


# ---------------------------------------------------------------- 分位数口径


def test_nearest_rank_is_not_interpolated():
    """规格说的是"排序后取 ceil(p·n)-1"，不是插值。n=4 时 p50 取第 2 个而不是 2.5。"""
    vals = [10, 20, 30, 40]
    assert nearest_rank(vals, 0.50) == 20      # ceil(2)-1 = 1 → 第 2 个
    assert nearest_rank(vals, 0.95) == 40      # ceil(3.8)-1 = 3 → 第 4 个
    assert nearest_rank(vals, 1.0) == 40


def test_nearest_rank_odd_and_single():
    assert nearest_rank([5], 0.5) == 5
    assert nearest_rank([3, 1, 2], 0.5) == 2   # ceil(1.5)-1 = 1 → 排序后第 2 个


def test_nearest_rank_empty_and_bad_p():
    assert nearest_rank([], 0.5) is None
    with pytest.raises(ValueError):
        nearest_rank([1, 2], 0)


# ---------------------------------------------------------------- 手算验收


def test_per_correct_tokens_hand_calculated():
    """规格的验收样例：5 题、2 对 3 错、token 已知 → 手算。

    tokens = 1000 + 2000 + 3000 + 4000 + 5000 = 15000；判对 2 题 → 7500。
    """
    rows = [
        _r("a", True, 1000, 10.0), _r("b", True, 2000, 20.0),
        _r("c", False, 3000, 30.0), _r("d", False, 4000, 40.0),
        _r("e", False, 5000, 50.0),
    ]
    c = build(rows)
    assert c["tokens_total"] == 15000
    assert c["per_correct_tokens"] == 7500.0
    # 排序后 [1000,2000,3000,4000,5000]：p50 → ceil(2.5)-1=2 → 3000；p95 → 5000
    assert (c["tokens_per_case_p50"], c["tokens_per_case_p95"]) == (3000, 5000)
    assert (c["duration_p50_s"], c["duration_p95_s"]) == (30.0, 50.0)
    assert (c["n_tokens"], c["n_duration"]) == (5, 5)


def test_zero_correct_gives_null_not_zero():
    """分母 0 时给 None。给 0 的意思是"每正确回答免费"，那是假的。"""
    c = build([_r("a", False, 100), _r("b", False, 200)])
    assert c["per_correct_tokens"] is None
    assert c["tokens_total"] == 300


# ---------------------------------------------------------------- 三个陷阱


def test_missing_tokens_are_skipped_not_zero():
    """tokens=None 的题不能当 0：当 0 会把 p50 从 300 拉到 100。"""
    c = build([_r("a", True, 100), _r("b", True, None), _r("c", True, 300)])
    assert c["tokens_total"] == 400
    assert c["n_tokens"] == 2
    assert c["tokens_per_case_p50"] == 100      # 2 个样本：[100,300] → 第 1 个
    assert c["per_correct_tokens"] == 133.3     # 400/3，不是 400/3 里再塞个 0


def test_estimated_tokens_are_counted_separately():
    """估算值照旧进分位数（否则样本太少），但必须单列出来给人判断。"""
    c = build([_r("a", True, 100), _r("b", True, 200, est=True), _r("c", True, 300)])
    assert (c["n_reported"], c["n_estimated"], c["n_tokens"]) == (2, 1, 3)


def test_missing_duration_does_not_become_zero():
    c = build([_r("a", True, 100, 5.0), _r("b", True, 100, None)])
    assert c["n_duration"] == 1
    assert c["duration_p50_s"] == 5.0


def test_all_empty_is_all_null():
    c = build([])
    assert c["tokens_total"] == 0
    assert c["tokens_per_case_p50"] is None
    assert c["per_correct_tokens"] is None
    assert c["duration_p95_s"] is None


# ---------------------------------------------------------------- 两种行形状


def test_accepts_adapter_rows():
    """render 传进来的是 adapter.Row，不是 dict —— 两条路必须是同一个答案。"""
    rows = [Row(report="x", id="a", group="", category="c", dataset=None, question="q",
                executed=True, correct=True, match="strict", tokens=1000,
                duration_s=10.0, failure_class=None, chart=None, correct_field="correct")]
    c = build(rows)
    assert c["tokens_total"] == 1000
    assert c["per_correct_tokens"] == 1000.0


def test_adapter_row_carries_estimated_flag():
    """`tokens_estimated` 原来不在 Row 里，成本块就分不出真数和估算。"""
    from app.eval import report_adapter as A

    info = A.inspect("docs/eval/holdout_20261103_145703_react_run1.json")
    assert info["n"] > 0
    rows = list(iter_rows("docs/eval/holdout_20261103_145703_react_run1.json"))
    c = build(rows)
    # 数字从报告本身取，不写死 —— 这份报告被 rescore 回填过，判对数会变。
    assert c["n_tokens"] == len(rows)
    assert c["n_estimated"] == 0
    assert c["per_correct_tokens"] == round(c["tokens_total"] / sum(1 for r in rows if r.correct), 1)
