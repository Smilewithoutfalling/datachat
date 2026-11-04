import json
import os

import pytest

from app.core import LLMConfig
from app.core.testing import oracle_factory, oracle_model
from app.eval.case_model import EvalCase
from app.eval.cases import ALL_CASES, DATASETS
from app.eval.comparator import is_refusal, results_equal
from app.eval.report import EvalReport
from app.eval.runner import EvalRunner, score
from app.eval.validate import validate_cases
from conftest import ROOT

EVAL_DATA = os.path.join(ROOT, "data", "sample_eval.csv")


def test_case_count_and_ids_unique():
    """题数写死是有意的：加题会让 evalset 指纹变、历史数字失去可比性，
    必须在这一行显式改一次，不能靠"自动适应"悄悄滑过去。"""
    ids = [c.id for c in ALL_CASES]
    assert len(set(ids)) == len(ids)
    single = [c for c in ALL_CASES if not c.turns]
    multi = [c for c in ALL_CASES if c.turns]
    # 2026-11-04：+10 负向（EV-B7）→ 单轮 160；+1 长会话回头引用（EV-B5 mul_034）→ 多轮 34；
    # +1 扰动题（EV-B6 pert_001）→ 单轮 161。
    assert (len(single), len(multi)) == (161, 34), "单轮 161（含 biz 22 + 负向 10 + 扰动 1）+ 多轮 34"
    by = {}
    for c in single:
        # 扰动题（EV-B6）的 dataset 是 fixture 路径，不在 DATASETS 里 —— 按 variant_kind 归 "pert"
        key = "pert" if c.variant_kind else c.dataset
        by[key] = by.get(key, 0) + 1
    assert by == {"sales": 50, "orders": 34, "employees": 27, "inventory": 27, "biz": 22, "pert": 1}


def test_case_flags_consistent():
    for c in ALL_CASES:
        # dataset 三选一：DATASETS 的键 / 存在的绝对路径（EV-B6 扰动题的 fixture）
        assert c.dataset in DATASETS or (os.path.isabs(c.dataset) and os.path.exists(c.dataset)), c.id
        # 原来的写法是一行等价：expect_refusal == (category == "refusal")。那条不变式
        # 立在只有单轮拒答题的时候；mul_029（两轮都该拒答）加进来之后它挡住了合法用例——
        # 多轮必须 category="multi_turn"，而 gold 一旦是「无法回答：…」又必须标 expect_refusal，
        # 否则 test_ground_truth_executes 会把"普通题给出了拒答字符串"当错误。
        # 拆成三条等价且更紧的规则，而不是简单地把那一行删掉。
        if c.category == "refusal":
            assert c.expect_refusal, c.id
        if c.expect_refusal:
            assert c.category in ("refusal", "multi_turn"), c.id
        if c.expect_refusal and c.category == "multi_turn":
            # gold 只判最后一轮，所以"整条题期望拒答"等价于"末轮该拒答"
            assert c.expect_turns and c.expect_turns[-1] == "refusal", c.id
        assert bool(c.alt_ground_truths) <= (c.category == "ambiguity"), c.id
        # ambiguity 类现在有两条腿，判分方式不同：
        #   alt_ground_truths  有多种合理解法，算对任一即过（8 条）
        #   expect_kind=clarify 题目模糊到无法作答，必须反问（6 条，EV-B7）
        # 后者没有 alt 是对的 —— 给它写一个 gold 就等于承认"猜某个口径"及格。
        # 放宽这条时要保证"两种腿至少占一条"，否则 ambiguity 类会混进既无 alt
        # 也无 kind 的普通题，那一类的准确率就没人知道在量什么了。
        if c.category == "ambiguity":
            assert c.alt_ground_truths or c.expect_kind == "clarify", c.id


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
    """歧义题至少有一个其他理解的答案和主答案不同，否则这道题测不出歧义。

    clarify 题不在其中：它们没有主答案，也没有备选答案 —— 正确行为是反问。
    对它们跑这条断言等于要求"一个不存在的 gold 和一个不存在的 alt 不相等"。
    """
    for c in ALL_CASES:
        if c.category != "ambiguity" or c.expect_kind == "clarify":
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
    """模型输出 = 标准答案时，必须全部判对：验证流水线与打分口径本身
    （含拒答题、负向题与 5 张表）。

    用 oracle_factory 而不是自己拼 oracle_model：clarify 题的正确输出是反问、
    不是执行 gold，那个分叉只能在工厂里有一份（两处各写一遍已经漂过一次）。

    workflow 路排除 clarify：它是固定线性图，没有反问分支（见
    `test_workflow_cannot_express_clarify`）。让假模型在它上面"不执行"是做不到的，
    硬做只会得到 SyntaxError —— 那不叫判分链路坏了。
    """
    cases = [c for c in ALL_CASES
             if agent != "workflow" or c.expect_kind != "clarify"]
    runner = _runner(agent, oracle_factory(agent))
    results = runner.run_all(cases)
    report = EvalReport(results)
    wrong = [r["case"].id for r in results if not r["correct"]]
    assert wrong == [] and report.correctness_rate() == 100.0
    assert report.reviewer_fix_rate() is None and report.infra_error_count() == 0
    assert all(r["tokens"] and r["duration_s"] is not None for r in results)


def test_workflow_cannot_express_clarify():
    """workflow agent 在 clarify 题上必然判错 —— 这是结构缺口，不是判分 bug。

    它的图是 planner → codegen → executor → summarizer，codegen 的契约只有
    「算出来」或「数据里没有，拒答」，**没有"问题不清楚，先反问问清"这条路**。
    所以 clarify 的 6 条题在 workflow 上的准确率恒为 0：它只会挑一个口径算下去。

    钉住这条不是为了记住"它不行"，而是让人知道这是已知缺口：
    哪天 workflow 加了澄清分支，这条测试会红，那时应当改成"它也能反问"。
    """
    case = next(c for c in ALL_CASES if c.id == "neg_001")
    r = _runner("workflow", oracle_factory("workflow")).run_single(case)
    assert r["correct"] is False
    assert r["executed"] is True          # 它算了，而不是反问
    assert "没问清口径就猜着算" in (r["negative_why"] or "")


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
    cs = data["chart_smoke"]                                          # [27]：图表冒烟与准确率分开报
    assert set(cs) >= {"出图率", "chart_option", "has_chart", "internal_errors"}
    assert all("chart" in c for c in data["cases"])


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


def test_ord_030_refund_excluded_alt():
    """B47：排除已退款的有效订单口径（73.15%）也算对。"""
    case = next(c for c in ALL_CASES if c.id == "ord_030")
    outs, _ = _RUNNER.expected_all(case)
    assert score(73.15, case, outs) and score(75.46, case, outs)
    assert not score(75.77, case, outs)                 # 没按 order_id 去重


def test_git_sha_note_when_git_missing(monkeypatch):
    """B48：调不到 git 时 sha 带 "?"，并在报告里写明原因。"""
    from app.eval import report
    monkeypatch.setenv("DATACHAT_GIT", os.path.join(ROOT, "no-such-git.exe"))
    sha = report.git_sha()
    assert sha.endswith("?") or sha == "unknown"
    assert "DATACHAT_GIT" in (report.git_sha_note() or "")
    s = EvalReport([], meta={}).summary()
    assert "git_sha_note" in s


# ---------------------------------------------------------------- EV-A1 用例治理

def test_all_cases_valid():
    assert validate_cases(ALL_CASES) == []


def test_duplicate_id_rejected():
    a = EvalCase(id="tmp_001", category="aggregation", question="q1", ground_truth="1")
    b = EvalCase(id="tmp_001", category="aggregation", question="q2", ground_truth="2")
    errs = validate_cases([a, b])
    assert any("重复" in e for e in errs)


def test_turns_last_must_equal_question():
    ok = EvalCase(id="tmp_002", category="aggregation", question="第二个问题", ground_truth="1",
                  turns=["第一个问题", "第二个问题"], expect_turns=["exec", "exec"])
    assert validate_cases([ok]) == []
    bad = EvalCase(id="tmp_003", category="aggregation", question="另一个说法", ground_truth="1",
                   turns=["第一个问题", "第二个问题"], expect_turns=["exec", "exec"])
    errs = validate_cases([bad])
    assert any("turns[-1]" in e for e in errs)


def test_expect_turns_length_must_match():
    c = EvalCase(id="tmp_004", category="aggregation", question="q", ground_truth="1",
                 turns=["a", "q"], expect_turns=["exec"])
    assert any("len(expect_turns)" in e for e in validate_cases([c]))


def test_unknown_variant_of_rejected():
    c = EvalCase(id="tmp_005", category="aggregation", question="q", ground_truth="1",
                 variant_of="agg_999")
    assert any("variant_of" in e for e in validate_cases([c]))


def test_gold_dataset_must_exist():
    c = EvalCase(id="tmp_006", category="aggregation", question="q", ground_truth="1",
                 gold_dataset="no/such.csv")
    assert any("gold_dataset" in e for e in validate_cases([c]))


def test_every_case_module_is_fingerprinted():
    """新增 cases_*.py 必须自动进 evalset 指纹。

    手写白名单漏过一次（comparator.py 不在里面，评分器改了指纹不动），这次用 glob 兜住：
    谁加了 cases_memory.py 却不在覆盖里，这条直接红。
    """
    import glob
    from app.eval.report import EVALSET_FILES
    mods = sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(ROOT, "app", "eval", "cases*.py")))
    assert mods, "一个用例模块都没扫到，glob 写错了"
    missing = [m for m in mods if f"app/eval/{m}" not in EVALSET_FILES]
    assert not missing, f"这些模块没进指纹：{missing}"


def test_no_history_truth_rejected_on_single_turn_case():
    """no_history_truth 写在单轮题上要被挡住。

    这个字段的语义是"把最后一轮当单轮题算出来的答案"，单轮题没有"最后一轮"这回事。
    写错位置不会让任何东西报错，只会静默变成一段没人读的代码——规则 6（枚举写错会
    静默失效）的同类问题，所以在校验层挡掉。
    """
    c = EvalCase(id="tmp_007", category="aggregation", question="q", ground_truth="1",
                 no_history_truth="result = 0")
    assert any("no_history_truth" in e for e in validate_cases([c]))
