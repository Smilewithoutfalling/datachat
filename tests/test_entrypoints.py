"""B16：命令行入口都经 analyze()（UI 见 test_ui_smoke.py）。"""
import json
import subprocess
import sys

import pytest

from app.core import AnalysisResult
from conftest import ROOT


@pytest.mark.parametrize("module,agent", [("run", "workflow"), ("run_react", "react")])
def test_cli_routes_through_analyze(monkeypatch, capsys, module, agent):
    mod = __import__(module)
    seen = {}

    def fake(dataset, question, **k):
        seen.update(k, dataset=dataset, question=question)
        return AnalysisResult(agent=k["agent"], dataset=dataset, question=question, answer="假回答")
    monkeypatch.setattr(mod, "analyze", fake)
    monkeypatch.setattr(sys, "argv", [module, "data/sample.csv", "总销量"])
    mod.main()
    assert seen["agent"] == agent and seen["question"] == "总销量" and seen["log"] is True
    assert "假回答" in capsys.readouterr().out


def test_run_eval_oracle_cli(tmp_path):
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, "run_eval.py", "--oracle", "--case", "agg_001", "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "100.0%" in p.stdout and out.exists()


def test_run_eval_repeat_and_rescore_cli(tmp_path):
    """阶段 1.5：--repeat 输出每次报告和汇总；--rescore 用存下的结构化结果离线重新打分。"""
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, "run_eval.py", "--oracle", "--dataset", "sales", "--category", "ts", "--repeat", "2",
                        "--scope", "category",
                        "--out", str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    runs = sorted(tmp_path.glob("r_run*.json"))
    assert len(runs) == 2 and list(tmp_path.glob("*_summary.json"))
    p = subprocess.run([sys.executable, "run_eval.py", "--rescore", str(runs[0])],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "13/13 = 100.0%" in p.stdout
    # #136：--scope 声明落报告顶层 filter（summary() 摊平 meta），台账与闸门据此追溯跑批口径。
    first = json.loads(runs[0].read_text(encoding="utf-8"))
    assert first["filter"]["scope"] == "category"


def test_run_eval_subset_scope_hard_rule(tmp_path):
    """#136 硬规则：子集跑批不声明作用域、或声明全局作用域，都在开跑前拒绝（退出 1，不写报告）。"""
    out = tmp_path / "r.json"
    for extra, needle in [
        ([], "需要显式声明"),
        (["--scope", "global"], "误导性结论"),
        (["--scope", "debug"], "--case"),
    ]:
        cmd = [sys.executable, "run_eval.py", "--oracle", "--category", "agg", *extra, "--out", str(out)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert p.returncode == 1, (extra, p.stdout + p.stderr)
        assert needle in p.stdout, (extra, p.stdout)
        assert not out.exists()   # 拒绝发生在写报告之前


def test_run_eval_case_debug_scope_exemption_and_recording(tmp_path):
    """#136：--case 单题调试豁免硬规则，声明的 --scope 照样进报告 meta.filter。"""
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, "run_eval.py", "--oracle", "--case", "agg_001", "--scope", "debug",
                        "--out", str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["filter"]["scope"] == "debug"


def test_run_eval_both_agents_and_rescore_new_tables(tmp_path):
    """阶段 3：--agent both 两个 Agent 各出一份报告；新表、拒答题的报告也能 --rescore。"""
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, "run_eval.py", "--oracle", "--agent", "both", "--category", "refusal",
                        "--scope", "category",
                        "--out", str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "应拒答" in p.stdout and "workflow" in p.stdout and "react" in p.stdout
    reports = sorted(tmp_path.glob("r_*.json"))
    assert [r.name for r in reports] == ["r_react.json", "r_workflow.json"]
    assert len(list(tmp_path.glob("eval_compare_oracle_*.json"))) == 1   # B42：compare 跟 --out 同目录
    data = json.loads(reports[1].read_text(encoding="utf-8"))
    # 拒答类现在跨四张表：EV-B7 的 neg_010（缺具体对象）落在 biz 上。
    # 题数不写死 —— 语料规模由 test_eval_cases 的 test_case_count_and_ids_unique 管，
    # 这里只验"报告认得出每张表、且 --rescore 能把它们全判对"。
    assert data["datasets"]["orders"]["dictionary_file"]
    assert {c["dataset"] for c in data["cases"]} == {"orders", "employees", "inventory", "biz"}
    n = len(data["cases"])
    p = subprocess.run([sys.executable, "run_eval.py", "--rescore", str(reports[1])],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert f"{n}/{n} = 100.0%" in p.stdout
