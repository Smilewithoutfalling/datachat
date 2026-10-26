"""V2d（phase5-frontend.md「V2d：token 观测与单轮预算」）：usage 拆分、单轮预算、finish_reason=length。"""
import pytest
from langchain_core.messages import AIMessage

from app.core.llm import BudgetExceeded, TokenUsage, UsageTracker, token_budget
from app.core.service import ANSWER_TRUNCATED_WARNING, BUDGET_WARNING, analyze
from app.core.testing import ScriptedChatModel, prompt_text
from app.eval.runner import usage_fields
from app.nodes.executor import TRUNCATED_CODE_ERROR


def _msg(usage=None, **meta):
    return type("M", (), {"usage_metadata": usage, "content": "回复", "response_metadata": meta})()


def tc(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": f"c{i}"}])


def cut(text):
    return AIMessage(content=text, response_metadata={"finish_reason": "length"})


# ---------------------------------------------------------------- §1 usage 拆分
def test_details_accumulate_cache_read_and_reasoning():
    t = UsageTracker()
    t.add_message(_msg({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                        "input_token_details": {"cache_read": 64}, "output_token_details": {"reasoning": 8}}))
    t.add_message(_msg({"input_tokens": 50, "output_tokens": 10, "total_tokens": 60,
                        "input_token_details": {"cache_read": 0}, "output_token_details": {"reasoning": 2}}))
    u = t.snapshot()
    assert (u.input_tokens, u.output_tokens, u.total_tokens) == (150, 30, 180)
    assert u.cache_read_tokens == 64 and u.reasoning_tokens == 10       # 0 也是上报了，照加
    assert u.reported is True and u.estimated is False and u.estimated_tokens == 0


def test_details_missing_is_none_not_zero():
    t = UsageTracker()
    t.add_message(_msg({"input_tokens": 3, "output_tokens": 4}))
    u = t.snapshot()
    assert u.cache_read_tokens is None and u.reasoning_tokens is None and u.total_tokens == 7


def test_missing_usage_is_estimated_from_chars_not_mixed_into_real_counts():
    t = UsageTracker()
    t.add_message(_msg(None), input_chars=101)          # 输入 ceil(101/2)=51，输出 "回复" 2 字 → 1
    u = t.snapshot()
    assert u.reported is False and u.estimated is True
    assert u.estimated_tokens == 52 and u.total_tokens == 0 and u.counted == 52


def test_zero_calls_reported_is_none():
    """V2d §1 判定变更：零调用时 reported 从 True 改为 None（原来报告里像"上报了 0"）。"""
    assert UsageTracker().snapshot().reported is None
    r = analyze("data/__no_such__.csv", "x", chat_model=ScriptedChatModel(replies=[], calls=[]))
    assert r.error_kind == "dataset" and r.usage.calls == 0 and r.usage.reported is None
    f = usage_fields(r.usage)
    assert f["tokens_reported"] is None and f["tokens_in"] is None and f["tokens_out"] is None


def test_usage_fields_for_report():
    u = TokenUsage(calls=2, input_tokens=20, output_tokens=10, total_tokens=30, reported=True, cache_read_tokens=8)
    assert usage_fields(u) == {"tokens_in": 20, "tokens_out": 10, "tokens_cache_read": 8, "tokens_reasoning": None,
                               "tokens_reported": True, "tokens_estimated": False}


def test_runner_rows_carry_split_and_keep_total(sample_path):
    from app.eval.runner import EvalRunner
    from app.eval.cases import ALL_CASES
    from app.core.testing import oracle_model
    case = ALL_CASES[0]
    runner = EvalRunner(sample_path, agent="workflow", model_factory=lambda c: oracle_model(c.ground_truth))
    out = runner.run_single(case)
    assert out["tokens"] == out["tokens_in"] + out["tokens_out"] and out["tokens_reported"] is True
    assert out["tokens_cache_read"] is None and out["tokens_estimated"] is False


# ---------------------------------------------------------------- §2 单轮预算
def test_budget_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_TOKEN_BUDGET", raising=False)
    assert token_budget() == 130_000
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "0")
    assert token_budget() == 0
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "abc")
    assert token_budget() == 130_000


def test_over_budget_reserves_last_input():
    """调用前判定：已用 + 最近一次输入 ≥ 预算 → 停（留出收尾那次调用）。"""
    t = UsageTracker(budget=40)
    t.add_message(_msg({"input_tokens": 10, "output_tokens": 5}))
    assert not t.over_budget()                     # 15 + 10 < 40
    t.add_message(_msg({"input_tokens": 10, "output_tokens": 5}))
    assert t.over_budget()                         # 30 + 10 = 40
    with pytest.raises(BudgetExceeded):
        t.check_budget()
    assert t.snapshot().budget_hit
    assert not UsageTracker(budget=0).over_budget()


def test_react_over_budget_forced_answer(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "40")
    m = ScriptedChatModel(replies=[tc("result = 1", 1), tc("result = 2", 2), "收尾结论"], calls=[])
    r = analyze(sample_path, "总数", agent="react", chat_model=m, use_dictionary=False)
    assert len(m.calls) == 3 and "工具调用次数已经用完" in prompt_text(m.calls[-1])   # 第三次是强制收尾
    assert r.ok and r.answer == "收尾结论" and r.result == 2
    assert BUDGET_WARNING.format(budget=40) in r.warnings and r.usage.budget_hit
    assert [s.name for s in r.steps][-1] == "forced_answer"


def test_react_over_budget_finalize_fails_is_agent_error(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "40")
    m = ScriptedChatModel(replies=[tc("result = 1", 1), tc("result = 2", 2), ""], calls=[])
    r = analyze(sample_path, "总数", agent="react", chat_model=m, use_dictionary=False)
    assert r.error_kind == "agent" and "本轮 token 用量达到上限（40）仍未给出结论" in r.error


def test_react_budget_zero_is_off(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "0")
    m = ScriptedChatModel(replies=[tc("result = 1", 1), tc("result = 2", 2), "结论"], calls=[])
    r = analyze(sample_path, "总数", agent="react", chat_model=m, use_dictionary=False)
    assert r.ok and r.answer == "结论" and not r.usage.budget_hit and r.warnings == []


def test_react_missing_usage_estimate_triggers_budget(sample_path, monkeypatch):
    """服务商不回 usage：按字数估算也能触发预算（V2d §2a）。"""
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "300")
    n = iter(range(1, 100))
    m = ScriptedChatModel(responder=lambda msgs: "收尾结论" if "工具调用次数已经用完" in prompt_text(msgs)
                          else tc("result = 1", next(n)), calls=[], tokens_per_call=None)
    r = analyze(sample_path, "总数", agent="react", chat_model=m, use_dictionary=False)
    assert r.usage.reported is False and r.usage.estimated and r.usage.budget_hit
    assert r.answer == "收尾结论" and len(m.calls) < 12      # 不靠预算会一直调到步数上限（约 12 次）


def test_workflow_over_budget_skips_reviewer(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "40")
    m = ScriptedChatModel(replies=["计划", "raise ValueError('x')", "没算出来"], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    texts = [prompt_text(c) for c in m.calls]
    assert len(texts) == 3 and not any("之前生成的 pandas 代码执行出错了" in t for t in texts)
    assert "分析未能成功完成" in texts[-1] and r.answer == "没算出来"
    assert r.error_kind == "execution" and BUDGET_WARNING.format(budget=40) in r.warnings


def test_workflow_under_budget_still_retries(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "1000")
    m = ScriptedChatModel(replies=["计划", "raise ValueError('x')", "result = 1", "结论"], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    assert r.ok and r.attempts == 1 and r.warnings == []


# ---------------------------------------------------------------- §3 finish_reason=length
def test_truncated_codegen_not_executed_then_retried(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "0")
    m = ScriptedChatModel(replies=["计划", cut("result = (1 +"), "result = 1", "结论"], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    assert r.initial_error == TRUNCATED_CODE_ERROR and r.attempts == 1
    assert TRUNCATED_CODE_ERROR in prompt_text(m.calls[2])         # reviewer 看到的是截断原因，不是语法错误
    assert r.ok and r.result == 1


def test_truncated_reviewer_also_not_executed(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_TOKEN_BUDGET", "0")
    m = ScriptedChatModel(replies=["计划", "raise ValueError('x')", cut("result = ("), "result = 2", "结论"], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    assert r.attempts == 2 and r.ok and r.result == 2
    assert [s.error for s in r.steps if s.name == "executor"][1] == TRUNCATED_CODE_ERROR


def test_truncated_summary_keeps_text_with_warning(sample_path):
    m = ScriptedChatModel(replies=["计划", "result = 1", cut("结论写到一半")], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    assert r.ok and r.answer == "结论写到一半" and ANSWER_TRUNCATED_WARNING in r.warnings


def test_react_truncated_answer_warning(sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), cut("结论写到一半")], calls=[])
    r = analyze(sample_path, "总数", agent="react", chat_model=m, use_dictionary=False)
    assert r.ok and r.answer == "结论写到一半" and ANSWER_TRUNCATED_WARNING in r.warnings


def test_not_truncated_no_warning(sample_path):
    m = ScriptedChatModel(replies=["计划", "result = 1", "结论"], calls=[])
    r = analyze(sample_path, "总数", agent="workflow", chat_model=m, use_dictionary=False)
    assert r.warnings == []


# ---------------------------------------------------------------- fake_llm：tokens-<N> 与强制收尾识别
def test_fake_llm_tokens_scenario_and_finalize():
    from tests.fake_llm import FakeError, handle, parse_model
    from app.core.service import FINALIZE_PROMPT
    assert parse_model("tokens-70000").kind == "tokens"
    for bad in ("tokens-5s", "tokens-10@act", "tokens"):
        with pytest.raises(FakeError):
            parse_model(bad)
    code, body = handle({"model": "tokens-70000", "messages": [
        {"role": "system", "content": FINALIZE_PROMPT}, {"role": "user", "content": "问题：x"}]})
    assert code == 200 and body["usage"]["prompt_tokens"] == 70000 and body["usage"]["total_tokens"] == 70005
    assert not body["choices"][0]["message"].get("tool_calls")           # 收尾认作 final：直接给结论
