"""EV-C4：档位校验器。

这里测的是"这一档该不该红"，不是 `report_adapter` 能不能读（那是 test_report_adapter.py）。
两条判据都是档位特有的：
  - `--expect-n`：题数少了 = 没跑完，比"准确率低了"严重得多；
  - `--require-all`：只有 oracle 用，假模型的输出就是标准答案，判错只能是判分链路坏了。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "eval"))

import tier_check  # noqa: E402


def _case(cid="agg_001", *, correct=True, executed=True, category="aggregation",
          question="q"):
    return {"id": cid, "category": category, "dataset": "sales", "question": question,
            "correct": correct, "match": "strict" if correct else None,
            "executed": executed}


def _report(tmp_path, cases, name="eval_react_test.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"cases": cases, "overall": {"n": len(cases)}}), encoding="utf-8")
    return str(p)


def test_clean_report_passes(tmp_path):
    p = _report(tmp_path, [_case(f"c{i}") for i in range(8)])
    info, problems = tier_check.evaluate(p, expect_n=8, require_all=True)
    assert problems == []
    assert info["n"] == 8


def test_short_report_fails_the_count_check(tmp_path):
    """题数少了 = 没跑完。这比"准确率低"严重：少跑 3 题的报告不能当全量结论用。"""
    p = _report(tmp_path, [_case(f"c{i}") for i in range(5)])
    _, problems = tier_check.evaluate(p, expect_n=8)
    assert problems == ["题数 5 ≠ 期望 8"]


def test_no_expect_n_means_no_count_check(tmp_path):
    p = _report(tmp_path, [_case(f"c{i}") for i in range(5)])
    _, problems = tier_check.evaluate(p)
    assert problems == []


def test_wrong_answer_only_matters_with_require_all(tmp_path):
    """默认不判准确率：8 题里翻 1 题是 12.5pp，任何门槛拦的都是噪声。

    只有 `--require-all`（oracle 专用）才把"答错"当红灯。
    """
    p = _report(tmp_path, [_case("a"), _case("b", correct=False)])
    assert tier_check.evaluate(p, expect_n=2)[1] == []
    _, problems = tier_check.evaluate(p, expect_n=2, require_all=True)
    assert any("判错 1 题" in x and "b" in x for x in problems)


def test_unexecuted_counts_as_red_under_require_all(tmp_path):
    """oracle 下执行失败说明沙箱或数据坏了 —— 不是模型不会，是流水线坏了。"""
    p = _report(tmp_path, [_case("a"), _case("b", correct=False, executed=False)])
    _, problems = tier_check.evaluate(p, expect_n=2, require_all=True)
    assert any("没有执行成功 1 题" in x and "b" in x for x in problems)


def test_missing_hard_fields_are_reported(tmp_path):
    """id/category/question 是适配器的硬字段 —— 缺了渲染与统计都不成立。"""
    bad = _case("a")
    bad["question"] = ""
    p = _report(tmp_path, [bad])
    _, problems = tier_check.evaluate(p, expect_n=1)
    assert any("缺字段" in x and "question" in x for x in problems)


def test_not_a_report_is_one_problem_not_a_crash(tmp_path):
    p = tmp_path / "baselines.json"
    p.write_text(json.dumps({"eval-v0": {}, "eval-v1": {}}), encoding="utf-8")
    info, problems = tier_check.evaluate(str(p), expect_n=8)
    assert info["kind"] == "not_a_report"
    assert len(problems) == 1 and "不是 eval 报告" in problems[0]


def test_gate_kind_is_rejected_by_default(tmp_path):
    """闸门报告与评测报告的字段不同（human_correct vs correct）—— 不能混着当同一种证据。"""
    p = tmp_path / "gate.json"
    p.write_text(json.dumps({"cases": [_case()], "auto_correct": 0}), encoding="utf-8")
    _, problems = tier_check.evaluate(str(p), expect_n=1)
    assert any("不是 eval 报告" in x and "gate" in x for x in problems)
    assert tier_check.evaluate(str(p), expect_n=1, kind="gate")[1] == []


def test_cli_exit_codes(tmp_path, capsys):
    ok = _report(tmp_path, [_case()], name="ok.json")
    bad = _report(tmp_path, [_case("x", correct=False)], name="bad.json")
    assert tier_check.main([ok, "--expect-n", "1", "--require-all"]) == 0
    assert tier_check.main([bad, "--expect-n", "1", "--require-all"]) == 1
    assert "❌" in capsys.readouterr().out


def test_cli_missing_file_exits_1(tmp_path):
    """文件不存在也是"这一份不通过"，不是崩栈 —— CI 要能读完所有报告再给结论。"""
    assert tier_check.main([str(tmp_path / "nope.json")]) == 1


# ------------------------------------------------------------------ 文档与 workflow 不能漂
def test_nightly_workflow_matches_v7_baseline():
    """nightly 跑的对象必须与基线文件写的一致。

    这两处任何一处被改（换了 agent、换了记忆档、忘了带门禁），读数就不再对得上基线，
    而读日志的人只看得到"绿"或"红"，看不出比的是不是同一件事。
    """
    import yaml

    base = json.load(open(os.path.join(ROOT, "docs", "eval", "baseline_v7.json"),
                          encoding="utf-8"))
    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "eval.yml"),
                             encoding="utf-8"))
    nightly = wf["jobs"]["nightly"]
    steps = nightly["steps"]
    runs = [str(s.get("run") or "") for s in steps]

    evals = [(s, str(s.get("run") or "")) for s in steps if "run_eval.py" in str(s.get("run") or "")]
    assert len(evals) == 1, f"nightly 应当只有一次全量跑，实际 {len(evals)} 次"
    step, cmd = evals[0]
    assert f"--agent {base['agent']}" in cmd, cmd
    assert f"--memory {base['memory_mode']}" in cmd, cmd
    assert "--case" not in cmd, "nightly 是全量，不许挑题"
    # 模型是仪器的一部分：写死成基线那个，不从 vars 读（vars 指向 GLM，v7 是 Qwen）。
    assert (step.get("env") or {}).get("DEEPSEEK_MODEL") == base["model"], step.get("env")
    assert any("nightly_gate.py" in r for r in runs), "nightly 没接门禁"


def test_pr_tier_does_not_call_the_model():
    """PR 档的定位是「不调 LLM」。谁把真模型塞回去，每次提交都要花钱，而且不判红。"""
    import yaml

    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "eval.yml"),
                             encoding="utf-8"))
    pr = wf["jobs"]["pr"]
    blob = yaml.safe_dump(pr, allow_unicode=True)
    assert "DEEPSEEK_API_KEY" not in blob
    assert "DATACHAT_LLM_KEY" not in blob


def _triggers(name):
    """YAML 1.1 会把裸 `on` 解析成布尔 True，两种键都得认。"""
    import yaml

    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", name),
                             encoding="utf-8"))
    return set(wf.get("on") or wf.get(True) or {})


def test_llm_workflows_have_no_automatic_triggers():
    """2026-11-18：CI 不再自动跑 LLM 评测。

    公网 runner 到不了内网网关（`grg-aikits-test` 是 10.62.27.32，公网 DNS NXDOMAIN），
    自动触发只会得到「202 题全是 infra_error」。谁把 push / schedule / pull_request
    加回来，这条会拦下来 —— 真模型评测在内网机器上手工跑，命令见 docs/eval/README.md。
    """
    for name in ("eval.yml", "drift.yml"):
        assert _triggers(name) == {"workflow_dispatch"}, (name, _triggers(name))


def test_tests_workflow_still_runs_on_every_commit():
    """tests 层不受影响：每次推 master 与每个 PR 都要跑，它不调模型。"""
    t = _triggers("tests.yml")
    assert "push" in t and "pull_request" in t
