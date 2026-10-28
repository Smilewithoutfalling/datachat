"""阶段 6.5 §2a / §2c / §6 第 1 条：4 种协议在假传输下都能构建并调通；4 个怪癖开关各有单测；
classify_error 认 anthropic 的异常；UsageTracker 吃 Anthropic / Responses 的 usage_metadata；探测两种响应都判对；
获取模型列表成功 / 失败 / 超时。

假传输 = tests/fake_llm.py 的真 HTTP 服务（四种协议的收发格式，同一套无状态场景）。
"""
import threading
import time

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core import analyze
from app.core import llm as llm_mod
from app.core.llm import (LLMClient, LLMConfig, LLMError, UsageTracker, build_chat_model, classify_error,
                          is_truncated, list_models, message_text, ping, probe_tools)
from tests.fake_llm import MARK_PROBE_TOOL, MODEL_LIST, make_server

PROTOS = ("openai_chat", "openai_responses", "azure", "anthropic")


@pytest.fixture(scope="module")
def root():
    srv = make_server()
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)


def cfg(root, proto, model="ok", **kw):
    url = {"openai_chat": root + "/v1", "openai_responses": root + "/v1"}.get(proto, root)
    extra = {"deployment": model} if proto == "azure" else {}
    extra.update(kw.pop("extra", {}))
    return LLMConfig(model=model, api_key="fake-key", base_url=url, protocol=proto, extra=extra, max_retries=0,
                     timeout=20, **kw)


def test_ping_message_and_probe_tool_match_fake():
    assert llm_mod.PROBE_TOOL == MARK_PROBE_TOOL


@pytest.mark.parametrize("proto", PROTOS)
def test_build_and_invoke_once(root, proto):
    """每种协议构建出对应的 LangChain 模型类，调一次拿到文字和 usage（UsageTracker 真数，不是估算）。"""
    m = build_chat_model(cfg(root, proto))
    expect = {"openai_chat": "ChatOpenAI", "openai_responses": "ChatOpenAI", "azure": "ChatOpenAI",
              "anthropic": "ChatAnthropic"}[proto]
    assert type(m).__name__ == expect
    if proto == "openai_responses":
        assert m.use_responses_api is True
    tr = UsageTracker()
    c = LLMClient(cfg(root, proto), tracker=tr)
    assert c.invoke("你是数据分析规划助手\n用户问题：多少行") == "（fake）统计行数。"
    u = tr.snapshot()
    assert (u.calls, u.input_tokens, u.output_tokens, u.total_tokens, u.reported, u.estimated) == (1, 10, 5, 15, True, False)


@pytest.mark.parametrize("proto", PROTOS)
@pytest.mark.parametrize("agent", ["workflow", "react"])
def test_full_analysis_each_protocol(root, proto, agent, sample_path):
    """完整分析（ReAct 含一轮工具调用 + 回传工具结果）在四种协议上都走通。"""
    r = analyze(sample_path, "有多少行？", agent=agent, llm_config=cfg(root, proto))
    assert r.ok, r.error
    assert r.answer == "（fake）结论：数据共有若干行。"
    assert r.executed and r.usage.reported is True


@pytest.mark.parametrize("proto", PROTOS)
def test_ping_ok_and_auth_failure(root, proto):
    ping(cfg(root, proto))
    with pytest.raises(LLMError) as ei:
        ping(cfg(root, proto, "fail-401"))
    assert ei.value.kind == "auth" and "[fake_llm] 按场景返回 401" in ei.value.upstream


def test_ping_responses_uses_min_16_tokens(root, monkeypatch):
    seen = {}
    real = llm_mod.build_chat_model

    def spy(c, **kw):
        seen.update(kw)
        return real(c, **kw)
    monkeypatch.setattr(llm_mod, "build_chat_model", spy)
    ping(cfg(root, "openai_responses"))
    assert seen["max_tokens"] == 16
    ping(cfg(root, "openai_chat"))
    assert seen["max_tokens"] == 1


@pytest.mark.parametrize("proto", PROTOS)
def test_probe_tools_both_answers(root, proto):
    assert probe_tools(cfg(root, proto, "ok")) is True
    assert probe_tools(cfg(root, proto, "notools")) is False
    with pytest.raises(LLMError) as ei:
        probe_tools(cfg(root, proto, "fail-400"))
    assert ei.value.kind == "bad_request"


@pytest.mark.parametrize("proto", ["openai_chat", "openai_responses", "anthropic"])
def test_list_models_ok(root, proto):
    assert list_models(cfg(root, proto)) == sorted(MODEL_LIST)


def test_list_models_failure_and_timeout(root):
    c = LLMConfig(model="ok", api_key="k", base_url=root + "/fail-500/v1")
    with pytest.raises(LLMError) as ei:
        list_models(c)
    assert ei.value.kind == "server"
    c = LLMConfig(model="ok", api_key="k", base_url=root + "/hang-3s/v1")
    t = time.monotonic()
    with pytest.raises(LLMError) as ei:
        list_models(c, timeout=0.5)
    assert ei.value.kind == "timeout" and time.monotonic() - t < 2.5
    with pytest.raises(LLMError):
        list_models(LLMConfig(model="ok", api_key="k", base_url=root, protocol="azure"))


def test_list_models_default_timeout_is_10s():
    assert llm_mod.MODELS_TIMEOUT == 10.0


def test_unknown_protocol_rejected():
    with pytest.raises(ValueError):
        build_chat_model(LLMConfig(api_key="x", protocol="gemini"))


# ------------------------------------------------------------------ classify_error：anthropic 异常
def _areq():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _astatus(cls, code):
    return cls("err", response=httpx2.Response(code, request=_areq()), body=None)


@pytest.mark.parametrize("make,kind,retry", [
    (lambda a: a.APITimeoutError(request=_areq()), "timeout", True),
    (lambda a: a.APIConnectionError(request=_areq()), "connection", True),
    (lambda a: _astatus(a.RateLimitError, 429), "rate_limit", True),
    (lambda a: _astatus(a.AuthenticationError, 401), "auth", False),
    (lambda a: _astatus(a.PermissionDeniedError, 403), "auth", False),
    (lambda a: _astatus(a.BadRequestError, 400), "bad_request", False),
    (lambda a: _astatus(a.NotFoundError, 404), "bad_request", False),
    (lambda a: _astatus(a.InternalServerError, 500), "server", True),
    (lambda a: _astatus(a.APIStatusError, 529), "server", True),       # Anthropic overloaded
    (lambda a: _astatus(a.APIStatusError, 409), "http_409", False),
])
def test_classify_anthropic_errors(make, kind, retry):
    import anthropic
    assert classify_error(make(anthropic)) == (kind, retry)


def test_anthropic_retry_goes_through_llmclient(root):
    """Anthropic 的 429 由 LLMClient 重试（SDK max_retries=0），记进 usage.retries。"""
    sleeps = []
    c = LLMClient(cfg(root, "anthropic", "fail-429").with_(max_retries=2), sleep=sleeps.append, jitter=False)
    with pytest.raises(LLMError) as ei:
        c.invoke("你是数据分析规划助手")
    assert ei.value.kind == "rate_limit" and ei.value.attempts == 3 and len(sleeps) == 2
    assert c.tracker.snapshot().retries == 2
    assert c.model.max_retries == 0


def test_usage_tracker_eats_anthropic_usage_metadata():
    """Anthropic 的 usage_metadata：input 含缓存读写、input_token_details 带 cache_read / cache_creation。"""
    tr = UsageTracker()
    tr.add_message(AIMessage(content=[{"type": "text", "text": "x"}], usage_metadata={
        "input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
        "input_token_details": {"cache_read": 100, "cache_creation": 0}}))
    u = tr.snapshot()
    assert (u.input_tokens, u.output_tokens, u.total_tokens, u.cache_read_tokens, u.reported) == (120, 30, 150, 100, True)


# ------------------------------------------------------------------ 四个怪癖开关（§2c），每个都有对照组
def q(**quirks):
    return LLMConfig(api_key="x", base_url="https://gw.example/v1", extra={"quirks": quirks})


def payload(model, msgs, **kw):
    return model._get_request_payload(msgs, **kw)


def test_quirk_no_stream_options():
    on, off = build_chat_model(q(no_stream_options=True)), build_chat_model(q())
    assert on.stream_usage is False
    p = payload(on, [HumanMessage("x")], stream=True, stream_options={"include_usage": True})
    assert "stream_options" not in p
    assert payload(off, [HumanMessage("x")], stream=True, stream_options={"include_usage": True})["stream_options"]


def test_quirk_no_array_content():
    msgs = [HumanMessage(content=[{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}])]
    assert payload(build_chat_model(q(no_array_content=True)), msgs)["messages"][0]["content"] == "甲乙"
    assert isinstance(payload(build_chat_model(q()), msgs)["messages"][0]["content"], list)


def test_quirk_reasoning_replay():
    """开：回复里的 reasoning_content 存进 additional_kwargs，下一轮带回 assistant 消息；关：既不存也不带。"""
    resp = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "", "reasoning_content": "先想一想",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]}}]}
    on, off = build_chat_model(q(reasoning_replay=True)), build_chat_model(q())
    msg_on = on._create_chat_result(resp).generations[0].message
    msg_off = off._create_chat_result(resp).generations[0].message
    assert msg_on.additional_kwargs["reasoning_content"] == "先想一想"
    assert "reasoning_content" not in msg_off.additional_kwargs
    turn = [HumanMessage("q"), msg_on, ToolMessage(content="1", tool_call_id="c1")]
    assert payload(on, turn)["messages"][1]["reasoning_content"] == "先想一想"
    assert "reasoning_content" not in payload(off, turn)["messages"][1]


@pytest.mark.parametrize("tp,thinking,body", [
    ("enable_thinking", False, {"enable_thinking": False}),
    ("enable_thinking", True, {"enable_thinking": True}),
    ("thinking", False, {"thinking": {"type": "disabled"}}),
    ("thinking", True, {"thinking": {"type": "enabled"}}),
])
def test_quirk_thinking_param(tp, thinking, body):
    c = LLMConfig(api_key="x", base_url="https://gw.example/v1", extra={"quirks": {"thinking_param": tp}, "thinking": thinking})
    assert payload(build_chat_model(c), [HumanMessage("x")])["extra_body"] == body
    assert "extra_body" not in payload(build_chat_model(q()), [HumanMessage("x")])


def test_quirks_apply_to_azure_too():
    c = LLMConfig(api_key="x", base_url="https://r.openai.azure.com", protocol="azure",
                  extra={"deployment": "d1", "quirks": {"no_array_content": True}})
    m = build_chat_model(c)
    # Azure v1：普通 ChatOpenAI 子类，地址补 /openai/v1，model 是部署名
    assert type(m).__name__ == "DatachatChatOpenAI" and m.model_name == "d1"
    assert m.openai_api_base == "https://r.openai.azure.com/openai/v1"
    msgs = [HumanMessage(content=[{"type": "text", "text": "a"}])]
    assert payload(m, msgs)["messages"][0]["content"] == "a"


def test_quirk_reasoning_replay_end_to_end_through_react(sample_path, monkeypatch):
    """ReAct 真循环里第二次调用确实带回第一次的 reasoning_content（经 DeepSeek 预设的 reasoning_replay）。"""
    from app.core.providers import effective_quirks
    sent = []
    resp_tool = {"id": "a", "object": "chat.completion", "created": 0, "model": "m", "usage": {
        "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "", "reasoning_content": "R1",
            "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "run_python_on_data", "arguments": '{"code": "result = int(len(df))"}'}}]}}]}
    resp_final = {"id": "b", "object": "chat.completion", "created": 0, "model": "m", "usage": {
        "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "共 N 行"}}]}

    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            sent.append(body["messages"])
            data = json.dumps(resp_tool if len(sent) == 1 else resp_final).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = LLMConfig(api_key="x", base_url=f"http://127.0.0.1:{srv.server_address[1]}", max_retries=0,
                      extra={"quirks": effective_quirks("deepseek")})
        r = analyze(sample_path, "多少行", agent="react", llm_config=c)
    finally:
        srv.shutdown()
    assert r.ok, r.error
    assert len(sent) == 2
    assistant = [m for m in sent[1] if m.get("role") == "assistant"]
    assert assistant and assistant[0]["reasoning_content"] == "R1"


# ------------------------------------------------------------------ 内容块与截断
def test_message_text_handles_blocks():
    assert message_text(AIMessage(content="a")) == "a"
    assert message_text(AIMessage(content=[{"type": "text", "text": "a"}, {"type": "reasoning", "summary": []},
                                           {"type": "text", "text": "b"}])) == "ab"
    assert message_text(None) == ""


def test_is_truncated_all_protocols():
    assert is_truncated(AIMessage(content="", response_metadata={"finish_reason": "length"}))
    assert is_truncated(AIMessage(content="", response_metadata={"stop_reason": "max_tokens"}))
    assert is_truncated(AIMessage(content="", response_metadata={"incomplete_details": {"reason": "max_output_tokens"}}))
    assert not is_truncated(AIMessage(content="", response_metadata={"stop_reason": "end_turn"}))


def test_azure_v1_url_and_request_path(root):
    """Azure 走 v1：请求打到 {资源}/openai/v1/chat/completions，不带 api-version；已带 /openai/v1 的地址不重复拼。"""
    assert llm_mod.azure_v1_url("https://r.openai.azure.com/") == "https://r.openai.azure.com/openai/v1"
    assert llm_mod.azure_v1_url("https://r.openai.azure.com/openai/v1/") == "https://r.openai.azure.com/openai/v1"
    m = build_chat_model(cfg(root, "azure"))
    assert m.openai_api_base == root + "/openai/v1" and "api_version" not in (m.model_kwargs or {})
    assert LLMClient(cfg(root, "azure")).invoke("你是数据分析规划助手\n用户问题：多少行") == "（fake）统计行数。"
