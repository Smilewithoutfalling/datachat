"""B20 / B21：自己搭的 ReAct 循环（替代已弃用的 create_react_agent）。全部离线。"""
import openai
import httpx2
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
REQ = httpx2.Request("POST", "https://x")


def call(name="run_python_on_data", args=None, i=1):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args if args is not None else {"code": "result = 1"},
                                              "id": f"call_{i}"}])


def test_no_deprecated_prebuilt():
    import app.react_agent as ra
    import ast
    tree = ast.parse(open(ra.__file__, encoding="utf-8").read())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "langgraph.prebuilt" not in mods


def test_transient_errors_retried_and_counted(sample_path):
    """B21：超时重试在循环里做，计进 usage.retries。"""
    m = ScriptedChatModel(replies=[openai.APITimeoutError(request=REQ), call(args={"code": "result = 7"}),
                                   openai.RateLimitError("slow", response=httpx2.Response(429, request=REQ), body=None),
                                   "结论 7"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 7 and res.usage.retries == 2


def test_retries_exhausted_is_llm_error(sample_path):
    m = ScriptedChatModel(responder=lambda _: openai.APITimeoutError(request=REQ), calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.error_kind == "llm" and len(m.calls) == 3 and res.usage.retries == 2


def test_auth_error_not_retried(sample_path):
    err = openai.AuthenticationError("bad key", response=httpx2.Response(401, request=REQ), body=None)
    m = ScriptedChatModel(responder=lambda _: err, calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.error_kind == "llm" and len(m.calls) == 1 and res.usage.retries == 0


def test_unknown_tool_and_bad_args_go_back_to_model(sample_path):
    """未知工具名、缺参数：错误作为工具结果回给模型，让它改（原 ToolNode 的行为）。"""
    m = ScriptedChatModel(replies=[call(name="nope"), call(args={}, i=2), call(args={"code": "result = 3"}, i=3),
                                   "结论 3"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 3
    tool_msgs = [x for x in m.calls[-1] if x.type == "tool"]
    assert "没有名为 'nope' 的工具" in tool_msgs[0].content and "错误" in tool_msgs[1].content


def test_parallel_tool_calls_in_order(sample_path):
    two = AIMessage(content="", tool_calls=[
        {"name": "run_python_on_data", "args": {"code": "result = 1"}, "id": "a"},
        {"name": "run_python_on_data", "args": {"code": "result = 2"}, "id": "b"}])
    m = ScriptedChatModel(replies=[two, "结论 2"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.result == 2 and [x.tool_call_id for x in m.calls[-1] if x.type == "tool"] == ["a", "b"]


def test_system_prompt_not_stored_in_memory(sample_path):
    """系统提示每次调用时放在最前，不进状态：多轮记忆里只有一条系统消息。"""
    mem = MemorySaver()
    m = ScriptedChatModel(replies=[call(), "一", call(i=2), "二"], calls=[])
    analyze(sample_path, "q1", agent="react", chat_model=m, llm_config=FAST, memory=mem, thread_id="t")
    analyze(sample_path, "q2", agent="react", chat_model=m, llm_config=FAST, memory=mem, thread_id="t")
    last = m.calls[-1]
    assert sum(1 for x in last if x.type == "system") == 1 and last[0].type == "system"
    assert [x.content for x in last if x.type == "human"] == ["q1", "q2"]
