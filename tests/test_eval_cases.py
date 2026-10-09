import json
import os

import pytest

from app.core import LLMConfig
from app.core.testing import oracle_model
from app.eval.cases import ALL_CASES
from app.eval.comparator import results_equal
from app.eval.report import EvalReport
from app.eval.runner import EvalRunner
from conftest import ROOT

EVAL_DATA = os.path.join(ROOT, "data", "sample_eval.csv")


def test_case_count_and_ids_unique():
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == 50 and len(set(ids)) == 50


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_ground_truth_executes(case):
    runner = EvalRunner(EVAL_DATA)
    result, err = runner._run_code(case.ground_truth)
    assert err is None
    assert results_equal(result, result)


def _r(executed, correct):
    return {"case": ALL_CASES[0], "executed": executed, "correct": correct, "initial_error": None}


def test_correctness_rate_uses_all_cases():
    """B11：正确率分母是全部题。"""
    report = EvalReport([_r(True, True), _r(False, False)])
    assert report.correctness_rate() == 50.0
    assert report.conditional_correctness_rate() == 100.0


def test_fix_rate_undefined_without_errors():
    """B11：没有初始报错时修复率无定义。"""
    report = EvalReport([_r(True, True)])
    assert report.reviewer_fix_rate() is None


def test_empty_category_not_fallback_to_all():
    report = EvalReport([_r(True, True)])
    assert report.correctness_rate([]) is None


# ---------------------------------------------------------------- 评测流水线（离线）
def _runner(agent, factory):
    return EvalRunner(EVAL_DATA, agent=agent, model_factory=factory, llm_config=LLMConfig(api_key="t"))


@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_oracle_pipeline_all_correct(agent):
    """模型输出 = 标准答案时，全部 50 题必须判对：验证流水线与打分口径本身。"""
    runner = _runner(agent, lambda c: oracle_model(c.ground_truth, agent))
    results = runner.run_all(ALL_CASES)
    report = EvalReport(results)
    wrong = [r["case"].id for r in results if not r["correct"]]
    assert wrong == [] and report.correctness_rate() == 100.0
    assert report.reviewer_fix_rate() is None and report.infra_error_count() == 0
    assert all(r["tokens"] and r["duration_s"] is not None for r in results)


def test_wrong_answer_scored_wrong():
    case = next(c for c in ALL_CASES if c.id == "agg_001")
    runner = _runner("workflow", lambda c: oracle_model(
        "result = (df['units'] * df['price']).groupby(df['region']).sum().idxmin()"))
    r = runner.run_single(case)
    assert r["executed"] and not r["correct"]


def test_infra_failure_counted_separately():
    case = ALL_CASES[0]
    runner = EvalRunner(EVAL_DATA, llm_config=LLMConfig(api_key=None))
    r = runner.run_single(case)
    report = EvalReport([r])
    assert r["infra_error"] and not r["executed"]
    assert report.infra_error_count() == 1 and report.correctness_rate() == 0.0


def test_no_double_execution(monkeypatch):
    """B07：评测直接用 analyze 的结构化结果，模型代码只执行一次（另一次是 ground truth）。"""
    from app.eval import runner as runner_mod
    from app.nodes import executor
    calls = []
    real = executor.run_code

    def counting(*a, **k):
        calls.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(executor, "run_code", counting)
    monkeypatch.setattr(runner_mod, "run_code", counting)
    case = ALL_CASES[0]
    _runner("workflow", lambda c: oracle_model(c.ground_truth)).run_single(case)
    assert len(calls) == 2


def test_report_json(tmp_path):
    runner = _runner("workflow", lambda c: oracle_model(c.ground_truth))
    report = EvalReport(runner.run_all(ALL_CASES[:3]))
    out = tmp_path / "r.json"
    report.to_json(str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["overall"]["n"] == 3 and data["git_sha"] and len(data["cases"]) == 3
