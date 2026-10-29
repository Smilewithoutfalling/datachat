# -*- coding: utf-8 -*-
"""台账生成器的测试。

守两件事：
1. 手写结论区不被重建覆盖 —— 这是台账唯一不可再生的东西。
2. flip 口径与 run_eval._stability 一致 —— 两处算同一个数，必须给同一个答案。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eval_ledger as L  # noqa: E402
from run_eval import _stability  # noqa: E402


# ---------------------------------------------------------------- 结论区

def test_notes_survive_rebuild():
    md = L.HEADER + "\n## 结论\n\n" + L.NOTES_BEGIN + "\n手写的结论\n" + L.NOTES_END + "\n"
    assert L.render_notes(md) == "手写的结论"


def test_notes_not_confused_by_marker_in_header():
    """HEADER 里出现过一次标记字面量 → find 会抓到那一处，把结论截成 ' 与 ' 且不报错。

    这是实际发生过的：第一版 HEADER 写了「放在 `<!-- NOTES:BEGIN -->` 与 ...」，
    结果每份台账的结论区都被压成两个字符。用 rfind 之后才正确。
    """
    poisoned = ("说明：结论放在 " + L.NOTES_BEGIN + " 与 " + L.NOTES_END + " 之间\n"
                + "## 结论\n\n" + L.NOTES_BEGIN + "\n真正的内容\n" + L.NOTES_END + "\n")
    assert L.render_notes(poisoned) == "真正的内容"


def test_notes_missing_markers_returns_placeholder():
    assert "尚未写结论" in L.render_notes("## 结论\n\n没有标记\n")
    assert "尚未写结论" in L.render_notes(None)


def test_notes_empty_block_returns_placeholder():
    md = L.NOTES_BEGIN + "\n\n" + L.NOTES_END
    assert L.render_notes(md) == "（空）"


# ---------------------------------------------------------------- 分类

def _report(n=130, code_sha12=None, cases=None, **kw):
    d = {
        "time": kw.get("time", "2026-10-29T10:00:00"),
        "git_sha": kw.get("git_sha", "abc1234"),
        "agent": kw.get("agent", "react"),
        "overall": {"n": n, "correct": n, "correctness_rate": 100.0},
        "cases": cases if cases is not None else [{"id": "c%d" % i, "correct": True} for i in range(n)],
    }
    if code_sha12:
        d["fingerprints"] = {"code_sha12": code_sha12, "evalset_sha12": "evalset123"}
        if kw.get("memory_mode"):
            d["fingerprints"]["memory_mode"] = kw["memory_mode"]
    return d


def test_kind_classification():
    assert L.normalize("a.json", _report(n=1))["kind"] == "debug"
    assert L.normalize("a.json", _report(n=130))["kind"] == "legacy"
    assert L.normalize("a.json", _report(n=130, code_sha12="deadbeef1234"))["kind"] == "gated"


def test_debug_reports_stay_out_of_batches():
    recs = [L.normalize("a.json", _report(n=1)),
            L.normalize("b.json", _report(n=130, code_sha12="deadbeef1234"))]
    batches = L.build_batches(recs)
    assert len(batches) == 1
    assert batches[0]["n"] == 130


def test_same_code_sha_batches_merge():
    recs = [L.normalize("a.json", _report(code_sha12="deadbeef1234", time="2026-10-29T09:00:00")),
            L.normalize("b.json", _report(code_sha12="deadbeef1234", time="2026-10-29T10:00:00"))]
    batches = L.build_batches(recs)
    assert len(batches) == 1
    assert len(batches[0]["records"]) == 2


def test_different_code_sha_stay_separate():
    recs = [L.normalize("a.json", _report(code_sha12="aaaaaaaaaaaa", time="2026-10-29T09:00:00")),
            L.normalize("b.json", _report(code_sha12="bbbbbbbbbbbb", time="2026-10-29T10:00:00"))]
    assert len(L.build_batches(recs)) == 2


def test_batches_split_by_memory_mode():
    """off 与 state 是两种配置，不能混在同一批里算均值。

    2026-10-29 多轮首测：同一 `code_sha12` 下 off 均值 41.0%、state 均值 82.1%，
    混算出来是 60.3%——那个数既不是 off 也不是 state，谁也代表不了。
    """
    recs = [L.normalize("a.json", _report(code_sha12="deadbeef1234", memory_mode="off",
                                         time="2026-10-29T09:00:00")),
            L.normalize("b.json", _report(code_sha12="deadbeef1234", memory_mode="state",
                                         time="2026-10-29T10:00:00"))]
    batches = L.build_batches(recs)
    assert len(batches) == 2
    assert {b["memory_mode"] for b in batches} == {"off", "state"}


def test_same_mode_still_merges():
    """加了 mode 维度不能把同模式的多跑拆散——否则算不出均值与翻转率。"""
    recs = [L.normalize("a.json", _report(code_sha12="deadbeef1234", memory_mode="state",
                                         time="2026-10-29T09:00:00")),
            L.normalize("b.json", _report(code_sha12="deadbeef1234", memory_mode="state",
                                         time="2026-10-29T10:00:00"))]
    assert len(L.build_batches(recs)) == 1


def test_git_sha_trailing_question_mark_stripped():
    """早先的报告把 dirty 工作区记成 'b710e23?'，台账里要清掉，否则同一个 commit 出现两种写法。"""
    assert L.normalize("a.json", _report(git_sha="b710e23?"))["git_sha"] == "b710e23"


# ---------------------------------------------------------------- flip 口径

def _rec(flags):
    return {"id": "x", "correct": flags}


def test_flip_rate_matches_stability():
    """同一个 per_case 喂给两处实现，flip_rate / pass^k 必须逐位相同。"""
    passes = {
        "a": [True, True, True],
        "b": [False, False, False],
        "c": [True, False, True],
        "d": [True, True, False],
    }
    per_case = {k: {"passes": v, "sig": [(7, "code")] * 3} for k, v in passes.items()}
    s = _stability(per_case, 3)

    recs = []
    for k in range(3):
        recs.append(L.normalize("r%d.json" % k, _report(
            n=4, code_sha12="deadbeef1234",
            cases=[{"id": cid, "correct": v[k]} for cid, v in passes.items()])))
    f = L.flip_stats(recs)

    assert f["flip_rate"] == pytest.approx(s["flip_rate"], abs=1e-9)
    assert f["pass_pow_k"] == pytest.approx(s["pass_pow_k"], abs=1e-9)
    assert f["all_correct"] == round(s["pass_pow_k"] * 4)
    assert sorted(f["flipped"]) == sorted(["c", "d"])


def test_flip_rate_denominator_is_pairs_not_runs():
    """2 题 3 跑：一题全对（0 对不一致），一题 [T,F,F] → 2 对不一致。

    分母是"题 × 成对组合" = 2 × 3 = 6，不是"题 × 跑" = 6 —— 两个 6 在这儿撞了，
    所以再单看一题：[T,F,F] 的 3 对里 (T,F)、(T,F) 不同、(F,F) 相同 → 2/3。
    写这条测试时我先把 [T,F,F] 当成"3 对全不同"算成了 50%，被实现纠正过来。
    """
    recs = [L.normalize("r%d.json" % k, _report(
        n=2, code_sha12="deadbeef1234",
        cases=[{"id": "same", "correct": True},
               {"id": "flip", "correct": v}]))
        for k, v in enumerate([True, False, False])]
    f = L.flip_stats(recs)
    assert f["flip_rate"] == pytest.approx(2 / 6)


def test_single_run_has_no_flip():
    recs = [L.normalize("a.json", _report(n=130, code_sha12="deadbeef1234"))]
    assert L.flip_stats(recs) is None


def test_flip_detects_all_wrong():
    recs = [L.normalize("r%d.json" % k, _report(
        n=2, code_sha12="deadbeef1234",
        cases=[{"id": "always_wrong", "correct": False},
               {"id": "ok", "correct": True}]))
        for k in range(2)]
    f = L.flip_stats(recs)
    assert f["all_wrong"] == ["always_wrong"]
    assert f["flipped"] == []
    assert f["pass_pow_k"] == pytest.approx(0.5)
