"""nightly 回归门禁：两条红灯 + 三类"不可比"。

这里测的是判定，不是 `run_eval.py` 能不能跑（那是 test_eval_cases / test_runner）。
判据全部写死在 `docs/eval/baseline_v7.json` 里，改数字要连带改文档 —— 所以另有一条
测试盯基线文件自身的一致性。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "eval"))

import nightly_gate as G  # noqa: E402


def _ids(n):
    return [f"c{i:02d}" for i in range(n)]


def _baseline(n=30, pass3=16, correct=24, *, agent="workflow", memory="state",
              model="m1", evalset="set123", judge="judge123", max_drop=6, max_flips=2):
    ids = _ids(n)
    return {
        "agent": agent, "memory_mode": memory, "model": model, "n": n,
        "runs": [correct] * 3, "correct": correct,
        "pass3": pass3, "pass3_ids": ids[:pass3],
        "unstable_ids": ids[pass3:pass3 + 4],
        "failed_ids": ids[pass3 + 4:],
        "fingerprints": {"evalset_sha12": evalset, "judge_sha12": judge},
        "rules": {"max_drop": max_drop, "max_pass3_flips": max_flips},
    }


def _report(wrong_ids=(), *, n=30, agent="workflow", memory="state", model="m1",
            evalset="set123", judge="judge123", infra=(), overall=None):
    wrong = set(wrong_ids) | set(infra)
    cases = [{"id": i, "category": "aggregation", "correct": i not in wrong,
              "question": f"题 {i}", "expected": 1, "actual": 2,
              "infra_error": i in set(infra)}
             for i in _ids(n)]
    correct = sum(1 for c in cases if c["correct"])
    return {
        "agent": agent, "memory_mode": memory, "model": model,
        "overall": {"n": n, "correct": correct if overall is None else overall},
        "fingerprints": {"evalset_sha12": evalset, "judge_sha12": judge},
        "cases": cases,
    }


# ---------------------------------------------------------------- 绿
def test_green_within_jitter():
    """掉 1 题、没翻稳定题：绿。单跑抖动实测就是 2 题，这类差不能报红。"""
    r = G.evaluate(_report([f"c{i:02d}" for i in range(16, 23)]), _baseline())
    assert r["verdict"] == "green", r
    assert r["metrics"]["drop"] == 1


def test_green_at_five_question_drop():
    """掉 5 题仍绿 —— 阈值是 6（含）。边界必须钉住，否则下次有人"顺手"改成 5。"""
    r = G.evaluate(_report([f"c{i:02d}" for i in range(16, 27)]), _baseline())
    assert r["verdict"] == "green", r
    assert r["metrics"]["drop"] == 5


def test_green_with_one_pass3_flip():
    """翻 1 道稳定题：绿 —— 规则 2 已经不拦了。"""
    r = G.evaluate(_report(["c00"]), _baseline())
    assert r["verdict"] == "green", r
    assert r["metrics"]["pass3_flips"] == 1


# ---------------------------------------------------------------- 红
def test_rule1_fires_at_six_question_drop():
    """掉 6 题、稳定题一道没翻（掉的全是本来就不稳的）：规则 1 单独响。"""
    r = G.evaluate(_report([f"c{i:02d}" for i in range(16, 28)]), _baseline())
    assert r["verdict"] == "red", r
    assert r["metrics"]["drop"] == 6 and r["metrics"]["pass3_flips"] == 0
    assert any("规则 1" in x for x in r["reasons"])
    assert not any("规则 2" in x for x in r["reasons"])


def test_two_pass3_flips_no_longer_gate():
    """**2026-11-18 降级**：翻 2 道稳定题只进简报，不影响退出码。

    实测依据（BACKLOG N7）：同一 master 连续两跑 193（翻 2）/195（翻 0），
    结论相反，且判红那跑通过数还高于基线；根因是网关 temp 0 并不确定。
    """
    r = G.evaluate(_report(["c00", "c01"]), _baseline())
    assert r["verdict"] == "green", r
    assert r["flips"] == ["c00", "c01"]
    assert r["metrics"]["pass3_flips"] == 2
    assert any("提示" in x and "不拦" in x for x in r["reasons"]), r["reasons"]


def test_rule1_fires_even_when_flips_are_also_present():
    """规则 1 单独决定红；翻转仍然列在 reasons 里备查。"""
    r = G.evaluate(_report(["c00", "c01"] + [f"c{i:02d}" for i in range(16, 27)]),
                   _baseline())
    assert r["verdict"] == "red"
    assert r["metrics"]["drop"] == 5 + 2
    assert sum("规则 1" in x for x in r["reasons"]) == 1
    assert sum("规则 2" in x for x in r["reasons"]) == 0
    assert any("提示" in x for x in r["reasons"])


# ---------------------------------------------------------------- 不可比
def test_judge_change_is_config_not_drift():
    """判分器/数据表动了 = 尺子变了。这不是回归，是断代没做。"""
    r = G.evaluate(_report(judge="judge999"), _baseline())
    assert r["verdict"] == "config"
    assert any("判分口径" in x and "断代" in x for x in r["reasons"])


def test_evalset_change_is_config():
    r = G.evaluate(_report(evalset="set999"), _baseline())
    assert r["verdict"] == "config"
    assert any("题库" in x for x in r["reasons"])


def test_agent_or_memory_mismatch_is_config():
    assert G.evaluate(_report(agent="react"), _baseline())["verdict"] == "config"
    assert G.evaluate(_report(memory="off"), _baseline())["verdict"] == "config"


def test_model_mismatch_is_config():
    """换模型不是回归：v7 的 pass^3 名单是 Qwen 上量的，GLM 跑出来的差不能算代码退化。"""
    r = G.evaluate(_report(model="other-model"), _baseline())
    assert r["verdict"] == "config"
    assert any("模型不同" in x for x in r["reasons"])


def test_short_report_is_config():
    """少跑题 = 没跑完。不能拿 199 题的读数去比 202 题的基线。"""
    r = G.evaluate(_report(n=19), _baseline())
    assert r["verdict"] == "config"
    assert any("题数 19" in x for x in r["reasons"])


def test_infra_error_is_config_not_drift():
    """网关熔断的题不是能力读数 —— 算成"变错"会让 nightly 在网关打嗝时误报代码退化。"""
    r = G.evaluate(_report(infra=["c10", "c11"]), _baseline())
    assert r["verdict"] == "config"
    assert any("infra_error" in x for x in r["reasons"])


def test_overall_disagreeing_with_cases_is_config():
    r = G.evaluate(_report(overall=99), _baseline())
    assert r["verdict"] == "config"
    assert any("自相矛盾" in x for x in r["reasons"])


# ---------------------------------------------------------------- 简报
def test_brief_lists_flips_and_commits():
    """翻转题照样列进简报 —— 只是不再影响退出码（绿也要看见它们）。"""
    base, rep = _baseline(), _report(["c00", "c01"])
    res = G.evaluate(rep, base)
    assert res["verdict"] == "green"
    brief = G.render_brief(res, base, rep, "outputs/nightly_v7.json",
                           ["abc123 feat: 改 prompt", "def456 fix: 修执行器"])
    assert "🟢 GREEN" in brief
    assert "`c00`" in brief and "`c01`" in brief
    assert "只列不拦" in brief
    assert "abc123" in brief and "def456" in brief
    assert "不自动修" in brief


def test_brief_on_red_still_shows_flips_and_rule1():
    base, rep = _baseline(), _report(["c00", "c01"] + [f"c{i:02d}" for i in range(16, 28)])
    res = G.evaluate(rep, base)
    assert res["verdict"] == "red"
    brief = G.render_brief(res, base, rep, "outputs/nightly_v7.json", [])
    assert "🔴 RED" in brief and "规则 1" in brief
    assert "`c00`" in brief and "`c01`" in brief


def test_cli_exit_codes(tmp_path):
    base = _baseline()
    bp = tmp_path / "baseline.json"
    bp.write_text(json.dumps(base), encoding="utf-8")
    out = tmp_path / "brief.md"

    green = tmp_path / "green.json"
    green.write_text(json.dumps(_report(["c20"])), encoding="utf-8")
    assert G.main(["--report", str(green), "--baseline", str(bp),
                   "--out", str(out), "--quiet"]) == 0

    red = tmp_path / "red.json"
    red.write_text(json.dumps(_report([f"c{i:02d}" for i in range(16, 28)])), encoding="utf-8")
    assert G.main(["--report", str(red), "--baseline", str(bp),
                   "--out", str(out), "--quiet"]) == 1
    assert "规则 1" in out.read_text(encoding="utf-8")

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(judge="other")), encoding="utf-8")
    assert G.main(["--report", str(bad), "--baseline", str(bp),
                   "--out", str(out), "--quiet"]) == 2


def test_missing_report_is_config(tmp_path):
    bp = tmp_path / "baseline.json"
    bp.write_text(json.dumps(_baseline()), encoding="utf-8")
    assert G.main(["--report", str(tmp_path / "nope.json"), "--baseline", str(bp),
                   "--out", str(tmp_path / "b.md"), "--quiet"]) == 2


# ---------------------------------------------------------------- 基线文件自身
def test_repo_baseline_is_self_consistent():
    """仓库里那份基线是 nightly 的锚点，被手改坏就等于门禁失效。"""
    d = json.load(open(os.path.join(ROOT, "docs", "eval", "baseline_v7.json"),
                       encoding="utf-8"))
    assert d["agent"] == "workflow" and d["memory_mode"] == "state"
    assert d["model"], "基线必须记模型名：模型不同读数就不可比"
    assert d["n"] == 202
    assert len(d["runs"]) == 3
    assert d["correct"] == sorted(d["runs"])[1], "单跑基线应是三跑中位数"
    assert d["pass3"] == len(d["pass3_ids"])
    assert len(set(d["pass3_ids"])) == d["pass3"], "pass3_ids 不能有重复"
    assert len(d["pass3_ids"]) + len(d["unstable_ids"]) + len(d["failed_ids"]) == d["n"]
    assert not (set(d["pass3_ids"]) & set(d["unstable_ids"]))
    assert d["rules"] == {"max_drop": 6, "max_pass3_flips": 2}
    assert d["fingerprints"]["evalset_sha12"] and d["fingerprints"]["judge_sha12"]
