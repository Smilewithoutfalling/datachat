"""EV-C1 方差地板：逐题 flip_rate 与 allowed_fail 的两条纪律。

与 test_stability.py 的分工：那边测 `run_eval._stability` 的口径（pass^k / any_correct /
缓存嫌疑），这边测**闸门侧**——判定来源是比较器而不是人工、逐题明细、以及名单纪律。
公式本身（`stats.flip_rate`）两边都复用，不在这里重写一遍。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "gate")
sys.path.insert(0, GATE)          # `_group_totals` 里 `from questions import QUESTIONS`

sys.path.insert(0, ROOT)
from app.eval import stats        # noqa: E402
import importlib.util             # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(f"gate_{name}", os.path.join(GATE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_gate = _load("run_gate")


# ------------------------------------------------------------------ 1. 公式（规格验收数字）
def test_k3_flip_rate_has_only_two_levels():
    """k=3：passes=1 与 passes=2 同为 0.67（对称），0 与 3 为 0。

    `min(passes, k−passes)/k` 会给 0.33 / 0.67，且上限只有 0.5 —— 0.4 的门槛在 k=3 上
    几乎永不触发，等于把量程砍掉一半。
    """
    assert stats.flip_rate(1, 3) == pytest.approx(2 / 3)
    assert stats.flip_rate(2, 3) == pytest.approx(2 / 3)
    assert stats.flip_rate(0, 3) == 0.0
    assert stats.flip_rate(3, 3) == 0.0


def test_k2_one_flip_is_certain():
    assert stats.flip_rate(1, 2) == 1.0
    assert stats.flip_rate(0, 2) == 0.0 and stats.flip_rate(2, 2) == 0.0


def test_k5_boundary_is_inclusive_below():
    """k=5：passes=1 → 0.4（**不**触发 0.4 门槛），passes=2 → 0.6（触发）。

    钉住比较符是 `>` 不是 `>=`：写反了，5 跑里翻 1 次的题会被判成不稳。
    """
    assert stats.flip_rate(1, 5) == pytest.approx(0.4)
    assert stats.flip_rate(2, 5) == pytest.approx(0.6)


# ------------------------------------------------------------------ 2. 闸门侧的口径
def _row(cid, matches, *, tokens=None, answers=None, executed=True, kinds=None):
    runs = []
    for i, m in enumerate(matches):
        runs.append({"executed": executed, "match": m, "auto_correct": m is not None,
                     "tokens": (tokens or {}).get(i, 100 + i),
                     "answer": (answers or {}).get(i, f"a{i}"),
                     "error_kind": (kinds or {}).get(i)})
    return {"id": cid, "runs": runs, "human_correct": True}


def test_stability_reads_comparator_not_human_labels():
    """人工签字只对第 1 次，第 2..k 次没人判过 —— 所以判定来源必须是比较器。

    这行人工填了 true（第 1 次确实对），但第 2 次比较器判不了。若拿 human_correct 当
    passes，这题会显示成 k 次全对、flip_rate=0，把真实抖动抹平。
    """
    rows = [_row("s01", ["strict", None, "strict"])]
    s = run_gate.gate_stability(rows, 3)
    assert s["basis"].startswith("auto_correct")
    assert s["cases"][0]["passes"] == 2          # strict + strict；None 不算对
    assert s["cases"][0]["flip_rate"] == pytest.approx(2 / 3)
    assert s["flipped"]["ids"] == ["s01"]


def test_unjudged_runs_are_listed_not_hidden_in_flips():
    """executed=True 且 match=None：算数上等同于"错"，但它不是模型翻转，是测量失败。

    不单列的话，一个比较器认不出的答案会被写进"翻题"名单，人去看权重却查不到问题。
    """
    rows = [_row("s01", ["strict", "strict", None])]
    s = run_gate.gate_stability(rows, 3)
    assert s["unjudged"] == [{"id": "s01", "runs": [3]}]
    # 它确实也算进 flip_rate（口径与主报告的 auto_correct 一致），但读者能分辨
    assert s["cases"][0]["passes"] == 2


def test_failed_execution_is_not_unjudged():
    """没跑起来（executed=False）是明确的答错，不是"判不了"。"""
    rows = [{"id": "s01", "human_correct": True, "runs": [
        {"executed": True, "match": "strict", "auto_correct": True, "tokens": 101, "answer": "a1"},
        {"executed": False, "match": None, "auto_correct": False, "tokens": None, "answer": ""},
    ]}]
    s = run_gate.gate_stability(rows, 2)
    assert s["unjudged"] == []
    assert s["cases"][0]["flip_rate"] == 1.0


def test_identical_runs_mark_stability_invalid():
    """k 次 (tokens, answer) 逐字相同 → 网关多半复用了同一份响应，flip_rate 没有信息量。"""
    rows = [_row("s01", ["strict"] * 3, tokens={0: 500, 1: 500, 2: 500},
                 answers={0: "same", 1: "same", 2: "same"}),
            _row("s02", ["strict"] * 3, tokens={0: 500, 1: 500, 2: 500},
                 answers={0: "same", 1: "same", 2: "same"})]
    s = run_gate.gate_stability(rows, 3)
    assert s["identical_cases"] == 2
    assert s["valid"] is False
    assert "复用" in s["invalid_reason"]


def test_missing_tokens_do_not_count_as_identical():
    """tokens=None 是缺数据，不是"两次相同"——把缺数据读成缓存会把报告误判成无效。"""
    rows = [_row("s01", ["strict"] * 3, tokens={0: None, 1: None, 2: None},
                 answers={0: "", 1: "", 2: ""})]
    s = run_gate.gate_stability(rows, 3)
    assert s["identical_cases"] == 0 and s["valid"] is True


def test_single_run_has_no_stability():
    """k<2 谈不了翻转：返回 None，调用方不写这个键（老报告形状不变）。"""
    assert run_gate.gate_stability([_row("s01", ["strict"])], 1) is None


def test_empty_report_is_invalid_not_none():
    """有 repeat 但一行都没有：不是"没跑 repeat"，是"没有可测的题"，得给一个人能读的原因。"""
    s = run_gate.gate_stability([], 3)
    assert s["n_cases"] == 0 and s["valid"] is False
    assert "没有可测的题" in s["invalid_reason"]


def test_rows_without_runs_are_skipped_not_silently_dropped():
    rows = [_row("s01", ["strict", "strict"]), {"id": "s02", "runs": None}]
    s = run_gate.gate_stability(rows, 2)
    assert s["n_cases"] == 1
    assert s["skipped"] == ["s02"]


# ------------------------------------------------------------------ 2b. 没测到 ≠ 很稳
def test_all_infra_failures_are_unmeasured_not_always_wrong():
    """k 跑全因基础设施失败：算进来会得到 flip_rate=0 + always_wrong 里有它 ——
    读起来像"这题一直做错"，实际**一次都没测到**。

    2026-11-04 真撞上过：网关 503，2 题 × 2 跑全 `llm` 失败，报告却写"稳定，flip_rate 0.00%"。
    """
    rows = [{"id": "s01", "human_correct": True, "runs": [
        {"executed": False, "match": None, "auto_correct": False, "tokens": None,
         "answer": "", "error_kind": "llm"}] * 2},
        _row("s02", ["strict", "strict"])]
    s = run_gate.gate_stability(rows, 2)
    assert s["unmeasured"] == [{"id": "s01", "kinds": ["llm"]}]
    assert s["n_cases"] == 1 and s["cases"][0]["id"] == "s02"
    assert "s01" not in s["always_wrong"]
    assert s["flip_rate"] == 0.0


def test_partial_infra_runs_are_flagged():
    """一跑成功一跑 503：翻转里可能夹着基础设施失败，标出来，别直接把账记到模型头上。"""
    rows = [{"id": "s01", "human_correct": True, "runs": [
        {"executed": True, "match": "strict", "auto_correct": True, "tokens": 100,
         "answer": "a", "error_kind": None},
        {"executed": False, "match": None, "auto_correct": False, "tokens": None,
         "answer": "", "error_kind": "llm"}]}]
    s = run_gate.gate_stability(rows, 2)
    assert s["partial_infra"] == [{"id": "s01", "runs": [2]}]
    assert s["cases"][0]["flip_rate"] == 1.0


def test_no_measured_case_gives_null_not_zero():
    """一题都没测到时 flip_rate 必须是 None，不是 0 —— 0 会被当成"测过了，很稳"。"""
    rows = [{"id": "s01", "human_correct": True, "runs": [
        {"executed": False, "match": None, "auto_correct": False, "tokens": None,
         "answer": "", "error_kind": "llm"}] * 2}]
    s = run_gate.gate_stability(rows, 2)
    assert s["flip_rate"] is None
    assert s["valid"] is False
    assert "没有可用的读数" in s["invalid_reason"]


# ------------------------------------------------------------------ 3. allowed_fail 纪律
def _m13r():
    prof, _ = run_gate.load_profile("m13r")
    return prof


def test_flipping_case_in_allowed_fail_warns():
    """不稳的题不许进名单：它是"还没定性"，不是"允许失败"。"""
    rows = [_row("s02", ["strict", "strict", None]),
            _row("m10", ["strict"] * 3)]
    s = run_gate.gate_stability(rows, 3)
    warn = run_gate.allowed_fail_warnings(_m13r(), "react", rows, s)
    assert any("翻转题" in w and "s02" in w for w in warn)


def test_stable_allowed_fail_passes_the_flip_check():
    """s02 三次全错（passes=0，flip_rate=0）：它一直在错，是稳定的失败，允许失败是合理的。"""
    rows = [_row("s02", [None, None, None]), _row("m10", ["strict"] * 3)]
    s = run_gate.gate_stability(rows, 3)
    warn = run_gate.allowed_fail_warnings(_m13r(), "react", rows, s)
    assert not any("翻转题" in w for w in warn)


def test_workflow_single_list_is_over_the_20_percent_quota():
    """真实 profile：workflow/single 是 4/15 = 27%，超线。

    这条检查会真的亮——那是它的用途，不是测试写错了。分母必须是**全量题数**：
    本次报告只跑了 2 题也不能算成 4/2。
    """
    rows = [_row("s02", ["strict"])]
    warn = run_gate.allowed_fail_warnings(_m13r(), "workflow", rows, None)
    assert any("4/15" in w and "27%" in w for w in warn)
    react_warn = run_gate.allowed_fail_warnings(_m13r(), "react", rows, None)
    assert not any("失去分辨力" in w for w in react_warn)


def test_no_repeat_says_the_flip_check_was_skipped():
    """没跑 repeat 时只说核了长度，不能假装核过稳定性。"""
    warn = run_gate.allowed_fail_warnings(_m13r(), "react", [], None)
    assert any("没有 repeat" in w for w in warn)


# ------------------------------------------------------------------ 4. 报告接线
def test_repeat_1_report_has_no_stability(monkeypatch, tmp_path):
    """repeat=1 不写 stability：老报告的形状不变。"""
    from app.core.result import AnalysisResult

    (tmp_path / "docs" / "eval").mkdir(parents=True)
    monkeypatch.setattr(run_gate, "ROOT", str(tmp_path))
    monkeypatch.syspath_prepend(GATE)
    monkeypatch.setattr(run_gate, "_analyze", lambda: (
        lambda *a, **k: AnalysisResult(agent="react", dataset="d", question="q",
                                       answer="a", code="result = 1", executed=True, result=1)))
    monkeypatch.setattr(run_gate, "auto_judge", lambda result, q, ans: "strict")

    path = run_gate.run("react", True, ["s01"])
    assert "stability" not in json.load(open(path, encoding="utf-8"))
