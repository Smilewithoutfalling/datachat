"""执行器的多轮编排（EV-A2）。

这里不造假模型，直接替换 `runner.analyze`：要验的是"history 有没有逐轮累积"、
"某个 turn 失败会不会中断最后一轮"，这两件事都发生在 analyze 之外。
用假模型还得让模型把 history 反射到回答里，绕远且更容易写错测试本身。
"""
import pytest

from app.core.llm import TokenUsage
from app.core.result import AnalysisResult
from app.eval import runner as runner_mod
from app.eval.case_model import EvalCase
from app.eval.runner import EvalRunner


def _res(question, *, answer=None, code="", executed=True, result="x",
         error_kind=None, total=1.0, tokens=10):
    return AnalysisResult(
        agent="react", dataset="d.csv", question=question,
        answer=answer if answer is not None else f"答{question}",
        code=code, executed=executed, result=result if executed else None,
        error=None if error_kind is None else "boom", error_kind=error_kind,
        timings={"total": total},
        usage=TokenUsage(calls=1, total_tokens=tokens, reported=True),
    )


def _multi(**kw):
    base = dict(id="tmp_001", category="aggregation", question="第二轮",
                ground_truth="result = len(df)",
                turns=["第一轮", "第二轮"], expect_turns=["exec", "exec"])
    base.update(kw)
    return EvalCase(**base)


def test_multiturn_history_is_passed_incrementally(monkeypatch):
    seen = []

    def fake_analyze(path, question, **kw):
        # 必须存快照：history 是同一个列表被逐轮 append 的，存引用会让第 1 次也显示成满的
        seen.append((question, list(kw.get("history") or [])))
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    r = EvalRunner(agent="react").run_single(_multi())

    assert [q for q, _ in seen] == ["第一轮", "第二轮"]
    assert seen[0][1] == []                              # 多轮首轮：有 history 概念，但还没内容
    assert seen[1][1] == [("第一轮", "答第一轮")]          # 第二轮能看到第一轮的问答
    assert r["turn_answers"] == ["答第一轮", "答第二轮"]
    assert r["turn_status"] == ["ok", "ok"]


def test_single_turn_passes_none_not_empty_list(monkeypatch):
    seen = []

    def fake_analyze(path, question, **kw):
        seen.append(kw.get("history"))
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = EvalCase(id="tmp_002", category="aggregation", question="只有一个问题",
                    ground_truth="result = len(df)")
    r = EvalRunner(agent="react").run_single(case)
    assert seen == [None]                                # 不是 []：单轮不该被当成多轮首轮
    assert r["turn_answers"] == [] and r["turn_status"] == []


def test_turn_error_does_not_abort_final_turn(monkeypatch):
    """中间轮 LLM 失败时，最后一轮照跑；失败轮的答案按空串进 history，不塞占位文案。"""
    calls = []

    def fake_analyze(path, question, **kw):
        calls.append((question, list(kw.get("history") or [])))
        if question == "第一轮":
            return _res(question, answer="", executed=False, error_kind="llm")
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = _multi(ground_truth="result = 'x'")   # 假结果就是 'x'，让打分这一层也能走通
    r = EvalRunner(agent="react").run_single(case)

    assert len(calls) == 2
    assert calls[1][1] == [("第一轮", "")]
    assert r["turn_status"] == ["error", "ok"]
    assert r["executed"] is True and r["correct"] is True   # 最后一轮照常打分
    assert r["infra_error"] is False                       # 最终有答案，不算基础设施失败


def test_failed_turn_marks_infra_when_last_turn_fails(monkeypatch):
    monkeypatch.setattr(runner_mod, "analyze",
                        lambda p, q, **kw: _res(q, answer="", executed=False, error_kind="llm"))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["infra_error"] is True and r["executed"] is False


@pytest.mark.parametrize("expect,fields,status", [
    ("exec", dict(executed=True), "ok"),
    ("exec", dict(executed=False), "fail:exec"),
    ("refusal", dict(executed=False, result=None, answer="无法回答：表里没有成本字段"), "ok"),
    ("refusal", dict(executed=False, result=None, answer="我觉得是华东"), "fail:refusal"),
    ("any", dict(executed=False), "ok"),
    ("inherit:region", dict(executed=True, code="df.groupby('region').sum()"), "ok"),
    ("inherit:region", dict(executed=True, code="df.sum()"), "fail:inherit"),
    ("inherit:", dict(executed=True, code="df.sum()"), "ok"),   # 空 regex 匹配一切，但 validate 会挡
])
def test_turn_status_semantics(expect, fields, status):
    fields.setdefault("answer", "答")
    r = _res("q", **fields)
    assert EvalRunner._turn_status(r, expect) == status


def test_infra_error_wins_over_fail(monkeypatch):
    """超时导致没执行代码，记 fail:exec 会把基础设施问题算成能力问题。"""
    r = _res("q", executed=False, error_kind="llm")
    assert EvalRunner._turn_status(r, "exec") == "error"


def test_multiturn_tokens_are_summed(monkeypatch):
    """多轮成本是各轮之和；只记最后一轮会低估，报告里的 tokens 就没人敢用了。"""
    monkeypatch.setattr(runner_mod, "analyze", lambda p, q, **kw: _res(q, total=2.0, tokens=100))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["tokens"] == 200
    assert r["duration_s"] == pytest.approx(4.0)


# ---------------------------------------------------------------- 记忆字段（阶段 6.6）

def test_memory_fields_default_when_module_absent(monkeypatch):
    """批 1 合入前 AnalysisResult 没有 memory_* 字段：报告照跑，值恒为 off / 0 / []。

    这不是"容忍缺失"，是要报告形状稳定——同一条用例不能因为记忆模块合没合入，
    结果里就多一列或少一列，否则拼 CSV 和对比脚本会在某一版突然错位。
    """
    monkeypatch.setattr(runner_mod, "analyze", lambda p, q, **kw: _res(q))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["memory_mode"] == "off"
    assert r["history_tokens"] == 0
    assert r["memory_trimmed"] == []


def test_memory_trimmed_is_union_over_turns(monkeypatch):
    """多轮取全轮并集：消融要看"这条用例被裁过没有"，只看最后一轮会把前几轮的裁剪漏掉。"""
    rounds = {"第一轮": ("state", 1200, ["state"]), "第二轮": ("state", 3000, ["history"])}

    def fake_analyze(path, question, **kw):
        res = _res(question)
        res.memory_mode, res.history_tokens, res.memory_trimmed = rounds[question]
        return res

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["memory_mode"] == "state"
    assert r["history_tokens"] == 3000                   # 最后一轮：多轮里历史最长
    assert r["memory_trimmed"] == ["history", "state"]   # 并集且排序稳定


def test_memory_block_flags_mixed_modes():
    """一批里混了 off 和 state，报告必须标出来：混跑的分数不能当消融结果。"""
    from app.eval.report import EvalReport
    c1 = _multi(id="tmp_mem_1")
    c2 = EvalCase(id="tmp_mem_2", category="aggregation", question="q", ground_truth="result = 1")
    base = {"correct": False, "executed": False, "agent": "react", "duration_s": None,
            "tokens": None, "initial_error": False, "error": None}
    rep = EvalReport([
        dict(base, case=c1, memory_mode="off", history_tokens=0, memory_trimmed=[]),
        dict(base, case=c2, memory_mode="state", history_tokens=900, memory_trimmed=["history"]),
    ])
    mem = rep.memory_block()
    assert mem["modes"] == {"off": 1, "state": 1}
    assert mem["uniform"] is False
    assert mem["trimmed_cases"] == {"history": 1}          # 0 的不出现，报告里不堆零
    assert mem["trimmed_any"] == 1
    assert mem["avg_history_tokens"] == 450.0

