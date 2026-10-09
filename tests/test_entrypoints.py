"""B16：命令行入口都经 analyze()（UI 见 test_ui_smoke.py）。"""
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
