import os

import pytest

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


@pytest.mark.xfail(raises=AssertionError, reason="B11: 正确率分母只算执行成功的题，数字虚高")
def test_correctness_rate_uses_all_cases():
    report = EvalReport([_r(True, True), _r(False, False)])
    assert report.correctness_rate() == 50.0


@pytest.mark.xfail(raises=AssertionError, reason="B11: 无初始报错时修复率记 100%")
def test_fix_rate_undefined_without_errors():
    report = EvalReport([_r(True, True)])
    assert report.reviewer_fix_rate() is None
