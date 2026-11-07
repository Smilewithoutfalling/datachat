"""题集生命周期（EV-D3）：状态机、校验、提议、报告接线。

这几条测的都是"没人看着的时候会不会悄悄错"：
毕业/退役改的是准确率分母，错了不会有任何一处报错，所以每条判据都要有反向用例。
"""
from __future__ import annotations

import json

import pytest

from app.eval import registry as R
from app.eval.case_model import EvalCase
from app.eval.cases import ALL_CASES
from app.eval.report import EvalReport

IDS = [c.id for c in ALL_CASES]


def _entry(*steps):
    """steps: (state, at, reason) 的序列，构成一条 history。"""
    return {"history": [{"state": s, "at": at, "reason": why} for s, at, why in steps]}


# ---------------------------------------------------------------- 默认值

def test_unlisted_cases_are_active():
    reg = R.Registry({})
    assert reg.state_of("emp_001") == "active"
    assert reg.counts(IDS) == {"candidate": 0, "active": len(IDS), "graduated": 0, "retired": 0}
    assert reg.uniform(IDS) is True


def test_missing_file_means_all_active(tmp_path):
    """新 clone 没带 registry.json 时不能跑不了——但也不能因此把题当已毕业。"""
    reg = R.load_registry(str(tmp_path / "nope.json"))
    assert reg.entries == {}
    assert reg.state_of("ord_001") == "active"


# ---------------------------------------------------------------- 状态机

def test_transition_edges():
    assert R.check_transition("candidate", "active") is None
    assert R.check_transition("active", "graduated") is None
    assert R.check_transition("active", "retired") is None
    assert R.check_transition("retired", "active") is None
    # candidate 直接毕业 = 没读数就毕业
    assert "非法移动" in R.check_transition("candidate", "graduated")
    assert "非法移动" in R.check_transition("graduated", "candidate")
    assert "没有移动" in R.check_transition("active", "active")
    assert "不是合法状态" in R.check_transition("active", "done")


# ---------------------------------------------------------------- 校验

def test_ghost_entry_reported():
    reg = R.Registry({"no_such_case": _entry(
        ("candidate", "2026-11-01", "起草"), ("active", "2026-11-02", "入集"))})
    problems = reg.problems(IDS)
    assert any("幽灵条目" in p for p in problems)


def test_missing_reason_reported():
    reg = R.Registry({"emp_001": _entry(("candidate", "2026-11-01", "起草"),
                                        ("active", "2026-11-02", "   "))})
    problems = reg.problems(IDS)
    assert any("缺 reason" in p for p in problems)


def test_bad_date_format_reported():
    reg = R.Registry({"emp_001": _entry(("candidate", "2026/11/01", "起草"))})
    assert any("YYYY-MM-DD" in p for p in reg.problems(IDS))


def test_backwards_date_reported():
    reg = R.Registry({"emp_001": _entry(("candidate", "2026-11-05", "起草"),
                                        ("active", "2026-11-01", "入集"))})
    assert any("早于上一次" in p for p in reg.problems(IDS))


def test_illegal_history_reported():
    reg = R.Registry({"emp_001": _entry(("candidate", "2026-11-01", "起草"),
                                        ("graduated", "2026-11-02", "直接毕业"))})
    assert any("非法移动 candidate → graduated" in p for p in reg.problems(IDS))


def test_doc_must_mention_non_active_case():
    """规格要求每次移动写 registry.md 的理由；文档里没有 id 就是没写。"""
    reg = R.Registry({"emp_001": _entry(("candidate", "2026-11-01", "起草"),
                                        ("active", "2026-11-02", "入集"),
                                        ("graduated", "2026-11-07", "三连对"))})
    assert any("registry.md 里没写理由" in p for p in reg.problems(IDS, doc_text="（暂无）"))
    assert reg.problems(IDS, doc_text="- emp_001：graduated —— 三连对") == []


# ---------------------------------------------------------------- 分类

def test_split_three_ways():
    reg = R.Registry({
        "emp_001": _entry(("candidate", "2026-11-01", "起草"), ("active", "2026-11-02", "入集"),
                          ("graduated", "2026-11-07", "三连对")),
        "ord_001": _entry(("candidate", "2026-11-01", "起草"), ("retired", "2026-11-07", "数据源废了")),
    })
    split = reg.split(["emp_001", "ord_001", "agg_001"])
    assert split["capability"] == ["agg_001"]
    assert split["regression"] == ["emp_001"]
    assert split["retired"] == ["ord_001"]
    assert reg.uniform(["emp_001", "agg_001"]) is False
    assert reg.uniform(["agg_001"]) is True


# ---------------------------------------------------------------- 提议

def _propose(seq, reg=None, n=3):
    reg = reg or R.Registry({})
    return R.propose_transitions(seq, reg.state_of, n)


def test_propose_graduates_after_three_passes():
    grad, retire = _propose({"emp_001": [True, True, True]})
    assert [p.case_id for p in grad] == ["emp_001"]
    assert grad[0].target == "graduated"
    assert retire == []


def test_propose_needs_three_consecutive():
    grad, _ = _propose({"emp_001": [True, False, True, True]})
    assert grad == []


def test_none_is_not_a_pass():
    """没判定 ≠ 判对。窗口里有一个 None 就不算连续全对。"""
    grad, _ = _propose({"emp_001": [True, True, None]})
    assert grad == []


def test_propose_retires_after_two_fails():
    _, retire = _propose({"ord_001": [True, False, False]})
    assert [p.case_id for p in retire] == ["ord_001"]
    assert retire[0].target == "retired"


def test_retire_beats_graduate():
    """[T,T,T,F,F]：先对后错是回归，不是该毕业的题。"""
    grad, retire = _propose({"emp_001": [True, True, True, False, False]})
    assert grad == [] and [p.case_id for p in retire] == ["emp_001"]


def test_propose_skips_cases_already_moved():
    reg = R.Registry({"emp_001": _entry(("candidate", "2026-11-01", "起草"),
                                        ("active", "2026-11-02", "入集"),
                                        ("graduated", "2026-11-03", "三连对"))})
    grad, _ = _propose({"emp_001": [True, True, True]}, reg=reg)
    assert grad == []


# ---------------------------------------------------------------- release 折叠

def test_same_config_runs_collapse_into_one_release():
    """同配置重复跑 3 次 = 1 个 release，不是 3 个——否则当天就能"三连对"毕业。"""
    seq, sizes = R.group_releases({"emp_001": [True, True, True]}, ["cfg"] * 3)
    assert seq["emp_001"] == [True]
    assert sizes == [3]


def test_distinct_configs_stay_separate():
    seq, sizes = R.group_releases({"emp_001": [True, False, True]}, ["c1", "c2", "c3"])
    assert seq["emp_001"] == [True, False, True]
    assert sizes == [1, 1, 1]


def test_release_requires_all_runs_correct():
    """一个 release 里跑两次、错一次 → 这轮就是错的（"release 全对"的字面意思）。"""
    seq, _ = R.group_releases({"emp_001": [True, False, True, True]}, ["a", "a", "b", "b"])
    assert seq["emp_001"] == [False, True]


def test_release_with_unjudged_run_is_no_reading():
    seq, _ = R.group_releases({"emp_001": [True, None]}, ["a", "a"])
    assert seq["emp_001"] == [None]


def test_same_config_again_later_is_a_new_release():
    """配置回滚（a→b→a）是三个 release：中间那版代码是真实发生过的一段。"""
    seq, sizes = R.group_releases({"emp_001": [True, False, True]}, ["a", "b", "a"])
    assert seq["emp_001"] == [True, False, True]
    assert sizes == [1, 1, 1]


def test_collapsed_repeats_do_not_graduate():
    """回归防线：三份同配置报告折成一个 release 后，不该出任何毕业提议。"""
    seq, sizes = R.group_releases({"emp_001": [True, True, True]}, ["cfg"] * 3)
    grad, _ = _propose(seq, n=len(sizes))
    assert grad == []


# ---------------------------------------------------------------- 稳定性（flip）

def test_flip_candidates_symmetric():
    """k=3、passes=1 与 passes=2 的 flip_rate 必须同为 0.67（stats.flip_rate 的对称性）。"""
    rows = dict((cid, (fr, p)) for fr, cid, p in R.flip_candidates(
        {"a": [True, False, False], "b": [True, True, False], "c": [True, True, True]}, 3,
        lambda _c: "active"))
    assert rows["a"][0] == pytest.approx(2 / 3)
    assert rows["b"][0] == pytest.approx(2 / 3)
    assert rows["c"][0] == 0.0


def test_flip_skips_retired_and_mismatched_k():
    seq = {"a": [True, False, False], "b": [True, True], "c": [True]}
    rows = R.flip_candidates(seq, 3, lambda c: "retired" if c == "a" else "active")
    assert rows == []          # a 退役跳过，b/c 的 k 对不齐


# ---------------------------------------------------------------- 报告接线

def _row(cid, correct=True, executed=True):
    return {"case": EvalCase(id=cid, category="aggregation", question="q", ground_truth="result = 1"),
            "correct": correct, "executed": executed}


def test_lifecycle_block_splits_and_keeps_overall():
    reg = R.Registry({
        "emp_001": _entry(("candidate", "2026-11-01", "起草"), ("active", "2026-11-02", "入集"),
                          ("graduated", "2026-11-07", "三连对")),
        "ord_001": _entry(("candidate", "2026-11-01", "起草"), ("retired", "2026-11-07", "废题")),
    })
    rep = EvalReport([_row("emp_001"), _row("agg_001", correct=False), _row("ord_001")],
                     registry=reg)
    lc = rep.lifecycle_block()
    assert lc["counts"] == {"candidate": 0, "active": 1, "graduated": 1, "retired": 1}
    assert lc["uniform"] is False
    assert lc["capability"] == {"n": 1, "correct": 0, "correctness_rate": 0.0,
                                "execution_success_rate": 100.0}
    assert lc["regression"]["n"] == 1 and lc["regression"]["correctness_rate"] == 100.0
    assert lc["retired"]["n"] == 1
    # overall 仍是"跑了的全部题"，不随状态变——老报告的语义不能动
    assert rep.correctness_rate() == pytest.approx(2 / 3 * 100)


def test_summary_and_fingerprint_carry_registry():
    rep = EvalReport([], registry=R.Registry({}))
    s = rep.summary()
    assert s["lifecycle"]["uniform"] is True
    fp = s["fingerprints"]
    assert fp["registry_sha12"] == R.Registry({}).sha12
    # 只记录，不进 GATE_KEYS：它不改题面，但改分母，必须可追溯
    from app.eval.fingerprint import GATE_KEYS
    assert "registry_sha12" not in GATE_KEYS


# ---------------------------------------------------------------- CLI

def _cli(argv):
    import importlib.util
    import os
    path = os.path.join(R.ROOT, "scripts", "eval", "registry.py")
    spec = importlib.util.spec_from_file_location("registry_cli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(argv)


def test_cli_check_repo_passes(capsys):
    assert _cli(["--check"]) == 0
    out = capsys.readouterr().out
    assert "状态计数" in out and "uniform=True" in out


def test_cli_check_fails_on_ghost(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": 1, "cases": {"ghost_case": _entry(
        ("candidate", "2026-11-01", "x"), ("active", "2026-11-02", "y"))}}), encoding="utf-8")
    assert _cli(["--check", "--registry", str(p)]) == 1
    assert "幽灵条目" in capsys.readouterr().out


def test_cli_set_writes_history(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": 1, "cases": {}}), encoding="utf-8")
    assert _cli(["--set", "emp_001=graduated", "--reason", "三连对", "--at", "2026-11-07",
                 "--registry", str(p)]) == 0
    data = json.loads(p.read_text(encoding="utf-8"))
    hist = data["cases"]["emp_001"]["history"]
    assert hist == [{"state": "graduated", "at": "2026-11-07", "reason": "三连对"}]
    # 再设一次同一状态 = 没有移动可记
    assert _cli(["--set", "emp_001=graduated", "--reason", "重复", "--registry", str(p)]) == 1


def test_cli_set_rejects_bad_input(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": 1, "cases": {}}), encoding="utf-8")
    assert _cli(["--set", "emp_001=graduated", "--registry", str(p)]) == 1          # 没理由
    assert _cli(["--set", "ghost=active", "--reason", "x", "--registry", str(p)]) == 1  # 幽灵
    assert _cli(["--set", "emp_001=done", "--reason", "x", "--registry", str(p)]) == 1  # 非法状态


def test_cli_set_refuses_candidate_leap(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": 1, "cases": {"emp_001": _entry(
        ("candidate", "2026-11-01", "起草"))}}), encoding="utf-8")
    assert _cli(["--set", "emp_001=graduated", "--reason", "跳级", "--registry", str(p)]) == 1
    assert _cli(["--set", "emp_001=active", "--reason", "入集", "--registry", str(p)]) == 0


def test_cli_propose_never_writes(tmp_path):
    """--propose 只打印。写盘是人工动作，脚本自动毕业过一次就没人敢信它。"""
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": 1, "cases": {}}), encoding="utf-8")
    before = p.read_bytes()
    # 三份报告：用真实报告结构造太重，这里只验证"拿不存在的路径也不写盘"
    _cli(["--propose", "a.json", "b.json", "c.json", "--registry", str(p)])
    assert p.read_bytes() == before
