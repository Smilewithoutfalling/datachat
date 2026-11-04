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
def test_tiers_doc_ids_match_workflow_case_list():
    """8 题名单在 `tiers.md` 与 `eval.yml` 里各写了一遍。

    两处都改才算改。只改一处的话：CI 跑的题和文档说的不是同一批，而读文档的人不会发现。
    """
    import re

    import yaml

    doc = open(os.path.join(ROOT, "docs", "eval", "tiers.md"), encoding="utf-8").read()
    doc_ids = re.findall(r"^\| [^|]+ \| `([a-z]+_\d+)`", doc, re.M)
    assert len(doc_ids) == 8, doc_ids

    wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "eval.yml"),
                             encoding="utf-8"))
    used = []
    for job in wf["jobs"].values():
        for step in job["steps"]:
            m = re.search(r"--case ([a-z0-9_,]+)", str(step.get("run") or ""))
            if m:
                used.append(sorted(x for x in m.group(1).split(",") if x))
    assert used, "eval.yml 里没找到 --case"
    for ids in used:
        assert ids == sorted(doc_ids), f"workflow 的名单与 tiers.md 不一致：{ids}"
