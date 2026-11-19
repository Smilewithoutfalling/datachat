"""阶段 7.5 第 1 步：assess 命令（scripts/assess/assess.py）与 --diff（验收 ④：逐题、逐环列出 ok↔fail，只列不判）。"""
import importlib.util
import json
import os

import pytest

from app.assess import runner
from app.core.service import analyze
from app.core.testing import ScriptedChatModel, prompt_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli():
    spec = importlib.util.spec_from_file_location("assess_cli", os.path.join(ROOT, "scripts", "assess", "assess.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _model(code, answer):
    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            return "1. 按 `region` 分组求 `units` 之和"
        if "写一段 pandas 代码" in t:
            return code
        if "请修正它" in t:
            return code
        return answer
    return ScriptedChatModel(responder=respond, calls=[])


@pytest.fixture
def two_sets(sample_path, tmp_path):
    """before：codegen 引用了不存在的列（三次都错）；after：一次写对。第二题两边一样。"""
    before, after = tmp_path / "before", tmp_path / "after"
    analyze(sample_path, "各地区总销量", chat_model=_model("result = df.groupby('area')['units'].sum()", "失败"),
            snapshot_dir=str(before))
    analyze(sample_path, "各地区总销量", chat_model=_model("result = df.groupby('region')['units'].sum()", "见结果"),
            snapshot_dir=str(after))
    for d in (before, after):
        analyze(sample_path, "总销量", chat_model=_model("result = int(df['units'].sum())", "见结果"),
                snapshot_dir=str(d))
    return str(before), str(after)


def test_assess_dir_json_and_markdown(two_sets, tmp_path, capsys):
    before, _ = two_sets
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    assert _cli().main([before, "--json", str(out_json), "--md", str(out_md)]) == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["summary"]["runs"] == 2
    keys = {r["key"] for r in data["runs"]}
    assert keys == {"sample.csv::各地区总销量", "sample.csv::总销量"}
    bad = [v for r in data["runs"] for v in r["verdicts"] if v["status"] == "fail"]
    assert any(v["contract"] == "codegen.columns" and "area" in v["reason"] for v in bad)
    md = out_md.read_text(encoding="utf-8")
    assert "不是准确率" in md and "codegen.columns" in md


def test_assess_diff_lists_ok_fail_changes_and_exits_zero(two_sets, tmp_path, capsys):
    before, after = two_sets
    out = tmp_path / "d.json"
    assert _cli().main(["--diff", before, after, "--json", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    ch = {(c["case"], c["ring"], c["contract"]): (c["before"], c["after"]) for c in d["changes"]}
    assert ch[("sample.csv::各地区总销量", "codegen#1", "codegen.columns")] == ("fail", "ok")
    assert ch[("sample.csv::各地区总销量", "executor#1", "executor.shape")] == ("fail", "ok")
    assert ch[("sample.csv::各地区总销量", "reviewer#1", "reviewer.scope")][1] == "absent"   # after 没进 reviewer
    assert not any(k[0] == "sample.csv::总销量" for k in ch)                                  # 没变的题不列
    md = capsys.readouterr().out
    assert "只列变化，不判对错" in md and "codegen#1" in md
    # 反过来同样只列、退出码仍为 0
    assert _cli().main(["--diff", after, before]) == 0


def test_diff_same_dir_is_empty(two_sets):
    before, _ = two_sets
    r = runner.assess_dir(before)
    d = runner.diff(r, r)
    assert d["changes"] == [] and d["only_before"] == [] and d["only_after"] == []


def test_assess_dir_lists_broken_file(tmp_path):
    (tmp_path / "x.jsonl").write_text("{}\n", encoding="utf-8")
    r = runner.assess_dir(str(tmp_path))
    assert r["runs"][0]["error"] and r["summary"]["runs"] == 1


# ---------------------------------------------------------------- 三态（ok / warn / fail / not_checked）
def test_assess_summary_counts_not_checked_separately(two_sets, tmp_path):
    """JSON 的 summary 四态都写出（含 0），not_checked 单列；markdown 有 not_checked 列与原因汇总。"""
    before, _ = two_sets
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    _cli().main([before, "--json", str(out_json), "--md", str(out_md)])
    s = json.loads(out_json.read_text(encoding="utf-8"))["summary"]
    assert set(s["verdicts"]) == {"ok", "warn", "fail", "not_checked"}
    assert s["not_checked"] == s["verdicts"]["not_checked"] > 0          # before 里执行出错 → sanity / grounding 未检查
    assert all(set(c) == {"ok", "warn", "fail", "not_checked"} for c in s["by_contract"].values())
    md = out_md.read_text(encoding="utf-8")
    assert "| 契约 | ok | warn | fail | not_checked |" in md
    assert "not_checked 的原因" in md and "执行出错，无结果可判" in md
    assert f"未检查（not_checked）：{s['not_checked']}" in md


def _report(runs: dict) -> dict:
    """{题键: [(环, 契约, 状态)]} → assess_dir 同形的报告。"""
    return {"directory": "x", "runs": [
        {"key": k, "verdicts": [{"ring": r, "contract": c, "status": st, "reason": st} for r, c, st in vs]}
        for k, vs in runs.items()]}


def test_diff_ok_not_checked_is_a_change():
    a = _report({"q1": [("codegen#1", "codegen.columns", "ok"), ("summarizer#1", "summarizer.grounding", "not_checked")]})
    b = _report({"q1": [("codegen#1", "codegen.columns", "not_checked"), ("summarizer#1", "summarizer.grounding", "fail")]})
    d = runner.diff(a, b)
    got = {(c["contract"], c["before"], c["after"], c["direction"]) for c in d["changes"]}
    assert got == {("codegen.columns", "ok", "not_checked", "now_unchecked"),
                   ("summarizer.grounding", "not_checked", "fail", "now_checked")}
    assert d["counts"] == {"now_unchecked": 1, "now_checked": 1}
    md = runner.diff_markdown(d)
    assert "now_unchecked" in md and "now_checked" in md


def test_diff_snapshot_missing_names_side():
    same = [("codegen#1", "codegen.columns", "ok")]
    a = _report({"q1": same, "only_b4": same})
    b = _report({"q1": same, "only_af": same})
    d = runner.diff(a, b)
    assert d["snapshot_missing"] == [{"case": "only_b4", "missing": "after"}, {"case": "only_af", "missing": "before"}]
    assert d["counts"] == {"snapshot_missing": 2}
    miss = {c["case"]: (c["before"], c["after"]) for c in d["changes"] if c["direction"] == "snapshot_missing"}
    assert miss == {"only_b4": ("present", "missing"), "only_af": ("missing", "present")}
    md = runner.diff_markdown(d)
    assert "snapshot_missing" in md and "缺 after：only_b4" in md and "缺 before：only_af" in md


def test_diff_snapshot_missing_real_dirs(two_sets, sample_path, tmp_path):
    """真快照：after 目录里少了一道题 → 报 snapshot_missing（缺 after），不是空差分。"""
    before, _ = two_sets
    partial = tmp_path / "partial"
    analyze(sample_path, "总销量", chat_model=_model("result = int(df['units'].sum())", "见结果"),
            snapshot_dir=str(partial))
    d = runner.diff(runner.assess_dir(before), runner.assess_dir(str(partial)))
    assert d["snapshot_missing"] == [{"case": "sample.csv::各地区总销量", "missing": "after"}]
    assert not any(c["case"] == "sample.csv::总销量" for c in d["changes"])


def test_diff_unreadable_file_listed_not_missing(tmp_path):
    bad = tmp_path / "b"
    bad.mkdir()
    (bad / "x.jsonl").write_text("{}\n", encoding="utf-8")
    d = runner.diff(runner.assess_dir(str(bad)), _report({}))
    assert d["unreadable"] == {"before": ["x.jsonl"], "after": []} and d["snapshot_missing"] == []
