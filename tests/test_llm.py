"""B10：LLM 显式超时、带退避的重试、token 统计。全部离线（假模型 + 构造的 openai 异常）。"""
import httpx2  # openai SDK 的传输层依赖，用来构造异常对象
import openai
import pytest

from app.core.llm import (LLMClient, LLMConfig, LLMError, UsageTracker, build_chat_model,
                          classify_error)
from app.core.testing import ScriptedChatModel

REQ = httpx2.Request("POST", "https://api.deepseek.com/v1/chat/completions")


def _status(cls, code):
    return cls("err", response=httpx2.Response(code, request=REQ), body=None)


def _client(replies, **cfg):
    sleeps = []
    client = LLMClient(LLMConfig(api_key="x", **cfg),
                       model=ScriptedChatModel(replies=list(replies), calls=[]),
                       sleep=sleeps.append, jitter=False)
    return client, sleeps


def test_chat_model_has_explicit_timeout_and_no_sdk_retries():
    m = build_chat_model(LLMConfig(api_key="x", timeout=12.5))
    assert m.request_timeout == 12.5 and m.max_retries == 0
    m2 = build_chat_model(LLMConfig(api_key="x", max_retries=4), sdk_retries=4)
    assert m2.max_retries == 4


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "m1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    monkeypatch.setenv("DATACHAT_LLM_TIMEOUT", "7")
    monkeypatch.setenv("DATACHAT_LLM_MAX_RETRIES", "5")
    cfg = LLMConfig.from_env()
    assert (cfg.model, cfg.timeout, cfg.max_retries) == ("m1", 7.0, 5)
    assert "sk-secret" not in repr(cfg)          # Key 不进 repr / 日志


def test_retry_on_timeout_then_success_with_exponential_backoff():
    client, sleeps = _client([openai.APITimeoutError(request=REQ),
                              _status(openai.RateLimitError, 429), "好"],
                             backoff_base=1.0)
    assert client.invoke("hi") == "好"
    assert sleeps == [1.0, 2.0]                  # 1s、2s：指数退避
    u = client.tracker.snapshot()
    assert u.retries == 2 and u.calls == 1 and u.total_tokens == 15


def test_backoff_capped():
    client, sleeps = _client([openai.APITimeoutError(request=REQ)] * 3 + ["ok"],
                             backoff_base=4.0, backoff_max=5.0)
    client.invoke("hi")
    assert sleeps == [4.0, 5.0, 5.0]


def test_gives_up_after_max_retries():
    client, sleeps = _client([openai.APITimeoutError(request=REQ)] * 10, max_retries=2)
    with pytest.raises(LLMError) as ei:
        client.invoke("hi")
    assert ei.value.kind == "timeout" and ei.value.attempts == 3 and len(sleeps) == 2


def test_auth_error_not_retried():
    client, sleeps = _client([_status(openai.AuthenticationError, 401), "never"])
    with pytest.raises(LLMError) as ei:
        client.invoke("hi")
    assert ei.value.kind == "auth" and ei.value.attempts == 1 and sleeps == []


@pytest.mark.parametrize("exc,kind,retry", [
    (openai.APITimeoutError(request=REQ), "timeout", True),
    (openai.APIConnectionError(request=REQ), "connection", True),
    (_status(openai.RateLimitError, 429), "rate_limit", True),
    (_status(openai.InternalServerError, 503), "server", True),
    (_status(openai.BadRequestError, 400), "bad_request", False),
    (TimeoutError(), "timeout", True),
    (ValueError("x"), "unknown", False),
])
def test_classify_error(exc, kind, retry):
    assert classify_error(exc) == (kind, retry)


def test_usage_tracker_handles_missing_usage():
    t = UsageTracker()

    class M:
        usage_metadata = None
    t.add_message(M())
    t.add_message(type("M2", (), {"usage_metadata": {"input_tokens": 3, "output_tokens": 4}})())
    u = t.snapshot()
    assert u.calls == 2 and u.total_tokens == 7 and u.reported is False
