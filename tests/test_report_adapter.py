"""report_adapter / report_md 的单测。

这两块最容易出的错是**静默**的：字段取错了，报告上只会出现一个略低的百分比，
没人会去核对。所以这里的断言尽量钉在具体数字和具体字符串上，不用 "in text" 蒙混。
"""
from __future__ import annotations

import json
import os

import pytest

from app.eval import report_adapter as A
from app.eval.report_md import render


def _write(tmp_path, name: str, data: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _eval_report(tmp_path, cases, name="eval.json", **top):
    data = {"time": "2026-01-01T00:00:00", "model": "m", "agent": "react", "cases": cases}
    data.update(top)
    return _write(tmp_path, name, data)


def _gate_report(tmp_path, cases, name="gate.json", **top):
    data = {"time": "2026-01-01T00:00:00", "questions_sha256": "x" * 64,
            "model": "m", "agent": "react", "cases": cases}
    data.update(top)
    return _write(tmp_path, name, data)


# ---------------------------------------------------------------- verdict_of


def test_verdict_priority_is_human_then_auto_then_correct():
    """规格 §EV-D1 明写的顺序。人判 > 比较器 > 报告记录值。"""
    all3 = {"human_correct": True, "auto_correct": False, "correct": False}
    assert A.verdict_of(all3) == (True, "human_correct")

    no_human = {"human_correct": None, "auto_correct": False, "correct": True}
    assert A.verdict_of(no_human) == (False, "auto_correct")

    only_correct = {"correct": True}
    assert A.verdict_of(only_correct) == (True, "correct")


def test_verdict_pending_when_all_three_are_null():
    """闸门报告人工没签字、auto 也缺 —— 这题没判，不能当判错。"""
    assert A.verdict_of({"human_correct": None, "auto_correct": None, "correct": None}) == (None, "pending")
    assert A.verdict_of({}) == (None, "pending")


def test_verdict_false_is_not_treated_as_missing():
    """`False` 是有效判定，别写成 `if case.get(k)` —— 那会把判错当没判。"""
    assert A.verdict_of({"correct": False}) == (False, "correct")
    assert A.verdict_of({"human_correct": False, "auto_correct": True}) == (False, "human_correct")


# ---------------------------------------------------------------- kind_of


@pytest.mark.parametrize("data,kind", [
    ({"cases": [], "questions_sha256": "x"}, A.KIND_GATE),
    ({"cases": [], "auto_correct": 3}, A.KIND_GATE),
    ({"cases": [], "correct": 3}, A.KIND_EVAL),
    ({"runs": []}, A.KIND_SUMMARY),
    ({"_comment": "x", "eval-v0": {}}, A.KIND_NOT_A_REPORT),
    ({}, A.KIND_NOT_A_REPORT),
])
def test_kind_of(data, kind):
    assert A.kind_of(data) == kind


def test_kind_of_prefers_cases_over_runs():
    """两者都有时按逐题报告算 —— summary 永远不会同时有 cases，但别赌。"""
    assert A.kind_of({"cases": [], "runs": []}) == A.KIND_EVAL


# ---------------------------------------------------------------- iter_rows


def test_iter_rows_gate_format_reads_human_verdict(tmp_path):
    p = _gate_report(tmp_path, [
        {"id": "s01", "group": "single", "category": "聚合", "question": "q",
         "executed": True, "human_correct": True, "auto_correct": False, "match": "strict"},
    ])
    rows = list(A.iter_rows(p))
    assert len(rows) == 1
    r = rows[0]
    assert (r.id, r.group, r.correct, r.correct_field) == ("s01", "single", True, "human_correct")


def test_wrong_rows_lose_their_match_tier(tmp_path):
    """判错的行不该带层级：残留的 `match='strict'` 会把 strict_rate 抬高。"""
    p = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "auto_correct": False, "match": "strict"},
    ])
    assert list(A.iter_rows(p))[0].match is None


def test_tokens_none_is_not_zero(tmp_path):
    """`tokens=None` 是"这份没记"，不是"花了 0 个 token"。当 0 会把均值拉低。"""
    p = _eval_report(tmp_path, [
        {"id": "a", "category": "x", "question": "q", "executed": True, "correct": True, "tokens": None},
        {"id": "b", "category": "x", "question": "q", "executed": True, "correct": True, "tokens": 100},
    ])
    rows = list(A.iter_rows(p))
    assert rows[0].tokens is None
    s = A.summarize(rows)
    assert s["avg_tokens"] == 100.0
    assert s["tokens_missing"] == 1


def test_row_without_id_raises(tmp_path):
    p = _eval_report(tmp_path, [{"category": "x", "question": "q", "correct": True}])
    with pytest.raises(A.ReportError, match="没有 id"):
        list(A.iter_rows(p))


def test_not_a_report_raises(tmp_path):
    p = _write(tmp_path, "baselines.json", {"_comment": "x", "eval-v0": {}})
    with pytest.raises(A.ReportError, match="不是逐题报告"):
        list(A.iter_rows(p))


def test_summary_expands_runs_with_suffix(tmp_path):
    run1 = _eval_report(tmp_path, [{"id": "a", "category": "x", "question": "q",
                                   "executed": True, "correct": True}], name="run1.json")
    run2 = _eval_report(tmp_path, [{"id": "a", "category": "x", "question": "q",
                                   "executed": True, "correct": False}], name="run2.json")
    summary = _write(tmp_path, "s_summary.json", {"runs": [
        {"run": 1, "file": run1}, {"run": 2, "file": run2},
    ]})

    rows = list(A.iter_rows(summary))
    assert [r.report for r in rows] == ["s_summary.json#run1", "s_summary.json#run2"]
    assert [r.correct for r in rows] == [True, False]


def test_summary_missing_run_is_skipped_not_raised(tmp_path):
    """`outputs/` 被 gitignore，新克隆的仓库里 run 文件本来就不存在 —— 那是正常状态。"""
    summary = _write(tmp_path, "s_summary.json", {"runs": [
        {"run": 1, "file": "D:\\nowhere\\definitely_missing_run1.json"},
    ]})
    assert list(A.iter_rows(summary)) == []
    info = A.inspect(summary)
    assert info["missing_runs"] == ["definitely_missing_run1.json"]


def test_resolve_run_file_falls_back_to_docs_eval():
    """带盘符的绝对路径在本机可能不存在，但同名文件归档在 docs/eval。"""
    got = A.resolve_run_file(r"D:\some\other\machine\gate_20261014_162428_react.json")
    assert got is not None
    assert got.endswith(os.path.join("docs", "eval", "gate_20261014_162428_react.json"))


def test_resolve_run_file_returns_none_for_garbage():
    assert A.resolve_run_file("") is None
    assert A.resolve_run_file(r"C:\nope\nope_xyz.json") is None


# ---------------------------------------------------------------- inspect


def test_inspect_counts_hard_missing_fields(tmp_path):
    p = _eval_report(tmp_path, [{"id": "a", "category": "", "question": "q", "correct": True}])
    info = A.inspect(p)
    assert info["n"] == 1
    assert info["missing_fields"] == {"category": 1}


def test_inspect_flags_conflicting_verdict_fields(tmp_path):
    """三字段并存且不一致时不能悄悄挑一个 —— 那说明这份报告本身有问题。"""
    p = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "human_correct": False, "auto_correct": True},
    ])
    info = A.inspect(p)
    assert info["conflicts"] == [{"id": "s01", "human_correct": False, "auto_correct": True}]


def test_inspect_no_conflict_when_fields_agree(tmp_path):
    p = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "human_correct": True, "auto_correct": True},
    ])
    assert A.inspect(p)["conflicts"] == []


def test_inspect_pending_is_not_a_failure(tmp_path):
    p = _gate_report(tmp_path, [{"id": "s01", "category": "x", "question": "q", "executed": True}])
    info = A.inspect(p)
    assert info["pending"] == 1
    assert info["missing_fields"] == {}


def test_inspect_no_match_counts_only_correct_rows(tmp_path):
    p = _eval_report(tmp_path, [
        {"id": "a", "category": "x", "question": "q", "correct": True, "match": "strict"},
        {"id": "b", "category": "x", "question": "q", "correct": True},
        {"id": "c", "category": "x", "question": "q", "correct": False},
    ])
    assert A.inspect(p)["no_match_when_correct"] == 1


# ---------------------------------------------------------------- render


def test_render_has_all_five_sections(tmp_path):
    p = _eval_report(tmp_path, [
        {"id": "a", "category": "聚合", "question": "q", "executed": True,
         "correct": True, "match": "strict", "tokens": 10, "duration_s": 1.0},
    ])
    text = render(p)
    for head in ("## 1 结论", "## 2 关键数字", "## 3 分类与数据集",
                 "## 4 异常题", "## 5 环境与指纹"):
        assert head in text, head


def test_render_says_strict_rate_unknown_instead_of_guessing(tmp_path):
    """没有 `match` 时严格率必须是"算不出"，不许把 2/2 写成 100%。"""
    p = _eval_report(tmp_path, [
        {"id": "a", "category": "x", "question": "q", "executed": True, "correct": True},
        {"id": "b", "category": "x", "question": "q", "executed": True, "correct": True},
    ])
    text = render(p)
    assert "算不出" in text
    assert "2 题判对但报告没记" in text


def test_render_gate_verdict_pass_and_fail(tmp_path):
    ok = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "human_correct": True, "auto_correct": True, "match": "strict"},
    ], verdict={"failures": 0, "profile": "p1", "single": "1/1"}, name="g1.json")
    assert "**过**" in render(ok)

    bad = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "human_correct": False, "auto_correct": False},
    ], verdict={"failures": 2, "profile": "p1"}, name="g2.json")
    txt = render(bad)
    assert "**不过**" in txt and "回归 2 题" in txt


def test_render_summary_lists_runs_separately_and_never_sums(tmp_path):
    """3 个 run 跑同一批题，合并分母会让区间假性变窄 —— 必须逐 run 列。"""
    runs = []
    for i, ok in enumerate((True, False, True), start=1):
        runs.append({"run": i, "file": _eval_report(
            tmp_path,
            [{"id": "a", "category": "x", "question": "q", "executed": True, "correct": ok}],
            name=f"r{i}.json")})
    summary = _write(tmp_path, "s_summary.json", {"runs": runs})

    text = render(summary)
    assert "## 2 逐 run" in text
    assert "run1" in text and "run3" in text
    # 逐 run 各 1/1；合起来会写成 2/3。断言它没这么写。
    assert "2/3" not in text
    assert "pass^3" in text


def test_render_summary_without_run_files_says_so(tmp_path):
    summary = _write(tmp_path, "s_summary.json", {
        "runs": [{"run": 1, "file": "D:\\nowhere\\missing_xyz.json"}],
    })
    text = render(summary)
    assert "一个 run 文件都没解析到" in text


def test_render_chart_with_option_but_no_image_is_an_anomaly(tmp_path):
    p = _eval_report(tmp_path, [
        {"id": "a", "category": "x", "question": "q", "executed": True, "correct": True,
         "match": "strict", "chart": {"chart_calls": 1, "options": 1, "drew": False,
                                      "pngs": 0, "chart_errors": [], "chart_internal_errors": []}},
        # 本来就没画（options=0）不算异常
        {"id": "b", "category": "x", "question": "q", "executed": True, "correct": True,
         "match": "strict", "chart": {"chart_calls": 0, "options": 0, "drew": False,
                                      "pngs": 0, "chart_errors": [], "chart_internal_errors": []}},
    ])
    text = render(p)
    assert "图表异常" in text
    section = text.split("## 4 异常题")[1].split("## 5")[0]
    assert "a(有 option 但没出图)" in section
    assert "b(" not in section


def test_render_rejects_non_report(tmp_path):
    p = _write(tmp_path, "baselines.json", {"_comment": "x"})
    with pytest.raises(A.ReportError):
        render(p)


def test_render_pending_rows_are_excluded_from_denominator(tmp_path):
    p = _gate_report(tmp_path, [
        {"id": "s01", "category": "x", "question": "q", "executed": True,
         "human_correct": True, "auto_correct": True, "match": "strict"},
        {"id": "s02", "category": "x", "question": "q", "executed": True},  # 待判
    ])
    text = render(p)
    assert "1/1" in text           # 分母只算判完的那道
    assert "待判" in text
