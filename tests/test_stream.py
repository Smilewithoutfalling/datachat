"""阶段 4：analyze_stream() 事件流（M09）。全部用脚本化假模型。"""
import json
import pytest

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.core import analyze, analyze_stream
from app.core.events import EVENT_TYPES
from app.core.testing import ScriptedChatModel, prompt_text
from tests.test_core_analyze import FAST, tool_call, wf_model


def _events(*a, **kw):
    evs = list(analyze_stream(*a, **kw))
    assert evs[-1].type == "done" and [e.type for e in evs].count("done") == 1
    assert [e.seq for e in evs] == list(range(len(evs)))
    assert len({e.trace_id for e in evs}) == 1 and evs[0].trace_id
    assert all(e.type in EVENT_TYPES for e in evs)
    for e in evs:
        json.dumps(e.to_dict(), ensure_ascii=False)              # SSE 可直接转发
    return evs


def test_workflow_event_order(sample_path):
    evs = _events(sample_path, "总销量", chat_model=wf_model(["result = int(df['units'].sum())"]),
                  llm_config=FAST, trace_id="msg-1")
    assert [e.type for e in evs] == ["plan", "code", "exec", "answer", "done"]
    assert evs[0].trace_id == "msg-1" and evs[1].data["source"] == "codegen"
    assert evs[2].data["ok"] and "1685" in evs[2].data["result_text"]
    res = evs[-1].result
    assert res.ok and res.result == 1685 and res.trace_id == "msg-1"
    assert evs[-1].to_dict()["data"]["result"]["trace_id"] == "msg-1"


def test_workflow_reviewer_events(sample_path):
    m = wf_model(["result = df['nope']"], fixes=["result = 1"])
    types = [(e.type, e.data.get("source"), e.data.get("ok")) for e in _events(sample_path, "q", chat_model=m, llm_config=FAST)]
    assert types == [("plan", None, None), ("code", "codegen", None), ("exec", None, False),
                     ("code", "reviewer", None), ("exec", None, True), ("answer", None, None), ("done", None, None)]


def test_fatal_error_precedes_done(sample_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    evs = _events(sample_path, "q")                                   # 没有 Key（conftest 的内存钥匙串为空）
    assert [e.type for e in evs] == ["error", "done"]
    assert evs[0].data == {"message": evs[-1].result.error, "kind": "llm", "fatal": True,
                           "llm_kind": "no_key"}   # V2a：没配 Key 是 llm 的子类 no_key，前端据此给「去设置」


def test_dataset_error(tmp_path):
    evs = _events(str(tmp_path / "missing.csv"), "q", chat_model=wf_model([]), llm_config=FAST)
    assert [e.type for e in evs] == ["error", "done"] and evs[0].data["kind"] == "dataset"


def test_react_events_live_and_answer_last(sample_path):
    m = ScriptedChatModel(replies=[AIMessage(content="先看看", tool_calls=[{"name": "run_python_on_data",
                                   "args": {"code": "result = df['nope']"}, "id": "c1"}]),
                                   tool_call("result = int(df['units'].sum())", 2), "总销量 1685 件"], calls=[])
    evs = _events(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert [e.type for e in evs] == ["code", "exec", "code", "exec", "answer", "done"]
    assert evs[0].data["thought"] == "先看看" and evs[0].data["source"] == "tool_call"
    assert not evs[1].data["ok"] and "KeyError" in evs[1].data["error"]
    assert evs[3].data["ok"] and evs[4].data == {"text": "总销量 1685 件", "forced": False}


def test_react_events_arrive_before_run_finishes(sample_path):
    """真流式：第一个 code 事件产出时，模型只被调用过一次（还没跑完整轮）。"""
    m = ScriptedChatModel(replies=[tool_call("result = 1"), "好"], calls=[])
    gen = analyze_stream(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    first = next(gen)
    assert first.type == "code" and len(m.calls) == 1
    gen.close()                                                       # 客户端断开：生成器可安全关闭


def test_react_retry_is_nonfatal_error(sample_path):
    m = ScriptedChatModel(replies=['{"message":"prompt 必须包含字符串内容', "无法回答：没有性别字段"], calls=[])
    evs = _events(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert [e.type for e in evs] == ["error", "answer", "done"]
    assert evs[0].data["fatal"] is False and evs[0].data["message"].startswith("重跑本轮")
    assert evs[-1].result.ok


def test_react_forced_answer_flag(sample_path):
    state = {"n": 0}

    def respond(messages):
        if "工具调用次数已经用完" in prompt_text(messages):
            return "共 1685 件。"
        state["n"] += 1
        return tool_call("result = 1685", state["n"])
    evs = _events(sample_path, "q", agent="react", chat_model=ScriptedChatModel(responder=respond, calls=[]),
                  llm_config=FAST, recursion_limit=5)
    ans = [e for e in evs if e.type == "answer"]
    assert len(ans) == 1 and ans[0].data == {"text": "共 1685 件。", "forced": True}
    assert "Sorry" not in json.dumps([e.to_dict() for e in evs[:-1]], ensure_ascii=False)   # 占位答复不外发


def test_react_memory_second_turn_only_new_events(sample_path):
    mem = MemorySaver()
    m = ScriptedChatModel(replies=[tool_call("result = 1"), "第一轮", "第二轮"], calls=[])
    _events(sample_path, "问一", agent="react", chat_model=m, llm_config=FAST, memory=mem, thread_id="t")
    evs = _events(sample_path, "问二", agent="react", chat_model=m, llm_config=FAST, memory=mem, thread_id="t")
    assert [e.type for e in evs] == ["answer", "done"]               # 上一轮的 code/exec 不重放


def test_analyze_equals_stream_done(sample_path):
    a = analyze(sample_path, "q", chat_model=wf_model(["result = 2"]), llm_config=FAST, trace_id="t1")
    b = list(analyze_stream(sample_path, "q", chat_model=wf_model(["result = 2"]), llm_config=FAST, trace_id="t1"))[-1].result
    ra, rb = a.to_record(), b.to_record()
    for r in (ra, rb):
        r.pop("timings"); [s.pop("duration_s") for s in r["steps"]]
    assert ra == rb


def test_trace_id_in_runs_log(sample_path, tmp_path, monkeypatch):
    from app.tools import persist
    log = tmp_path / "runs.jsonl"
    monkeypatch.setattr(persist, "RUNS_LOG", str(log))
    res = analyze(sample_path, "q", chat_model=wf_model(["result = 1"]), llm_config=FAST, log=True)
    assert len(res.trace_id) == 32 and json.loads(log.read_text(encoding="utf-8"))["trace_id"] == res.trace_id


# ---------------------------------------------------------------- history（阶段 4，B 方案）
def test_history_rebuilds_context_and_steps_are_this_turn_only(sample_path):
    from app.core.service import MAX_HISTORY_TURNS
    m = ScriptedChatModel(replies=[tool_call("result = 2"), "本轮结论"], calls=[])
    hist = [(f"问{i}", f"答{i}") for i in range(MAX_HISTORY_TURNS + 2)]
    res = analyze(sample_path, "现在呢", agent="react", chat_model=m, history=hist)
    sent = str(m.calls[0])
    assert "'问0'" not in sent and "'问1'" not in sent and "'问2'" in sent and "答11" in sent and "现在呢" in sent
    assert res.ok and res.answer == "本轮结论"
    assert [s.name for s in res.steps if s.name == "tool_call"] == ["tool_call"]


def test_history_and_memory_are_exclusive(sample_path):
    from langgraph.checkpoint.memory import MemorySaver
    with pytest.raises(ValueError):
        analyze(sample_path, "q", agent="react", chat_model=ScriptedChatModel(replies=["x"]),
                memory=MemorySaver(), history=[("a", "b")])


def test_history_followup_without_code_is_not_retried(sample_path):
    m = ScriptedChatModel(replies=["上一轮的 1685 是全部订单的件数之和"], calls=[])
    res = analyze(sample_path, "解释一下", agent="react", chat_model=m, history=[("总销量", "1685")])
    assert res.ok and len(m.calls) == 1 and not any(s.name == "retry" for s in res.steps)
