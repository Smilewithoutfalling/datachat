import json
import os

import pytest

from app.core import LLMConfig
from app.core.testing import oracle_model
from app.eval.cases import ALL_CASES, DATASETS
from app.eval.comparator import is_refusal, results_equal
from app.eval.report import EvalReport
from app.eval.runner import EvalRunner, score
from conftest import ROOT

EVAL_DATA = os.path.join(ROOT, "data", "sample_eval.csv")


def test_case_count_and_ids_unique():
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == 130 and len(set(ids)) == 130
    by = {}
    for c in ALL_CASES:
        by[c.dataset] = by.get(c.dataset, 0) + 1
    assert by == {"sales": 50, "orders": 30, "employees": 25, "inventory": 25}


def test_case_flags_consistent():
    for c in ALL_CASES:
        assert c.dataset in DATASETS, c.id
        assert c.expect_refusal == (c.category == "refusal"), c.id
        assert bool(c.alt_ground_truths) <= (c.category == "ambiguity"), c.id
        if c.category == "ambiguity":
            assert c.alt_ground_truths, c.id


_RUNNER = EvalRunner(EVAL_DATA)


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_ground_truth_executes(case):
    outs, err = _RUNNER.expected_all(case)
    assert err is None and len(outs) == 1 + len(case.alt_ground_truths)
    assert results_equal(outs[0], outs[0])
    if case.expect_refusal:
        assert is_refusal(outs[0])
    else:
        assert not is_refusal(outs[0])


def test_ambiguity_alternatives_differ_from_main():
    """歧义题至少有一个其他理解的答案和主答案不同，否则这道题测不出歧义。"""
    for c in ALL_CASES:
        if c.category != "ambiguity":
            continue
        outs, _ = _RUNNER.expected_all(c)
        assert any(not results_equal(o, outs[0]) for o in outs[1:]), c.id


def test_refusal_scoring():
    case = next(c for c in ALL_CASES if c.id == "ord_024")
    assert score("无法回答：数据中没有成本字段", case, [])
    assert not score("无法回答", case, [])               # 没有原因
    assert not score("无法回答：", case, [])
    assert not score(None, case, [])
    assert not score("数码", case, [])                   # 编了一个答案
    normal = next(c for c in ALL_CASES if c.id == "ord_001")
    assert not score("无法回答：数据不足", normal, [1200])   # 能答的题拒答算错
    assert score(1200, normal, [1200])


def test_alt_ground_truth_accepted():
    case = next(c for c in ALL_CASES if c.id == "emp_024")
    outs, _ = _RUNNER.expected_all(case)
    assert score(240, case, outs) and score(203, case, outs)
    assert not score(17, case, outs)


def test_eval_data_matches_generator():
    """data/eval/*.csv 必须与 scripts/gen_eval_data.py 的输出逐字节一致（改了脚本要重新生成）。"""
    import subprocess
    import sys
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gen_eval_data.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stdout + p.stderr


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
    """模型输出 = 标准答案时，全部 130 题必须判对：验证流水线与打分口径本身（含拒答题与 4 张表）。"""
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
    real_code, real_trusted = executor.run_code, runner_mod.run_trusted

    def counting(real):
        def f(*a, **k):
            calls.append(a[0])
            return real(*a, **k)
        return f
    monkeypatch.setattr(executor, "run_code", counting(real_code))         # 模型代码：子进程沙箱
    monkeypatch.setattr(runner_mod, "run_trusted", counting(real_trusted))  # 标准答案：本进程
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
    assert all("answer" in c and c["actual_obj"] and c["expected_obj"] for c in data["cases"])


def test_report_metadata_records_model_and_data():
    """B27：报告记录模型、温度、接口主机、数据指纹，但不记录 Key。"""
    from app.eval.report import run_metadata
    meta = run_metadata(LLMConfig(model="deepseek-x", api_key="sk-secret"), EVAL_DATA)
    assert meta["model"] == "deepseek-x" and meta["temperature"] == 0.0
    assert meta["base_url_host"] == "api.deepseek.com" and len(meta["data_sha256"]) == 12
    assert "sk-secret" not in json.dumps(meta)


def test_git_sha_without_git_binary(monkeypatch):
    """B27：git 命令不可用（Windows conda 环境常见）时，从 .git 文件读出 SHA，末尾加 ? 表示未检查改动。"""
    from app.eval import report as rep

    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(rep, "_git", boom)
    sha = rep.git_sha()
    assert sha != "unknown" and sha.endswith("?") and len(sha) == 8
