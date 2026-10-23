"""设置页「测试连接」POST /settings/test（phase5「阶段 5 收尾」C）：每种结果一条，走真 HTTP 的假模型服务（tests/fake_llm.py）。

用**已保存**的设置（PUT /settings 存进库的 model / base_url / timeout）+ resolve_api_key 的 Key；不重试；没 Key 不发请求；
message 经 T11 user_error（带编号、Key 打码）；同一时间只许一个，第二个 409；返回里任何地方都没有 Key 串。
"""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core import llm as llm_mod
from app.server.app import create_app
from tests.fake_llm import MARK_PING, make_server
from tests.test_server import H, TOKEN

KEY = "sk-testconnsecret0123456789"


@pytest.fixture(scope="module")
def fake_url():
    srv = make_server()
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


@pytest.fixture
def c(tmp_path, monkeypatch, fake_url):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    client = TestClient(create_app(str(tmp_path / "home"), TOKEN))
    client.fake_url = fake_url
    return client


def use(c, model, timeout=20):
    r = c.put("/settings", headers=H, json={"model": model, "base_url": c.fake_url, "timeout": timeout})
    assert r.status_code == 200


def run(c):
    r = c.post("/settings/test", headers=H)
    assert r.status_code == 200, r.text
    assert KEY not in r.text            # 返回里任何地方都没有 Key 串
    return r.json()


def test_ping_message_matches_fake_marker():
    assert llm_mod.PING_MESSAGE == MARK_PING


def test_requires_bearer(c):
    assert c.post("/settings/test").status_code == 401


def test_ok_uses_saved_settings(c):
    use(c, "ok")
    d = run(c)
    assert d["ok"] is True and d["model"] == "ok"
    assert isinstance(d["latency_ms"], int) and d["latency_ms"] >= 0
    assert set(d) == {"ok", "latency_ms", "model"}


def test_no_key_sends_nothing(c, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    use(c, "hang-30s")                  # 要是真发了请求，这里会卡 15 秒以上
    t = time.monotonic()
    d = run(c)
    assert time.monotonic() - t < 3
    assert d["ok"] is False and d["llm_kind"] == "no_key" and d["latency_ms"] == 0
    assert d["message"].startswith("未配置 API Key") and "（编号 " in d["message"]


@pytest.mark.parametrize("model,kind,text", [
    ("fail-401", "auth", "鉴权失败，请检查 API Key"),
    ("fail-429", "rate_limit", "请求太频繁，被限流"),
    ("fail-500", "server", "模型服务出错"),
])
def test_failures_classified(c, model, kind, text):
    use(c, model)
    t = time.monotonic()
    d = run(c)
    assert d["ok"] is False and d["llm_kind"] == kind
    assert time.monotonic() - t < 5     # 不重试：429 / 500 都是可重试错误，产品的 LLMClient 会退避重试三次
    msg = d["message"]
    assert msg.startswith(text) and "[fake_llm] 按场景返回" in msg   # 上游 message 原文照常透出（T11 第 4 条）
    assert "APIStatusError" not in msg and "Error:" not in msg and msg.endswith("）") and "（编号 " in msg
    assert set(d) == {"ok", "llm_kind", "message", "latency_ms"}


def test_timeout_capped(c, monkeypatch):
    monkeypatch.setattr(llm_mod, "PING_TIMEOUT_MAX", 1.0)   # 产品里是 15 秒；这里压到 1 秒，验证取 min(timeout, 上限)
    use(c, "hang-4s", timeout=60)
    t = time.monotonic()
    d = run(c)
    assert time.monotonic() - t < 3.5
    assert d["ok"] is False and d["llm_kind"] == "timeout" and d["message"].startswith("请求超时")


def test_concurrent_second_is_409(c):
    use(c, "hang-2s")
    first = {}
    th = threading.Thread(target=lambda: first.setdefault("r", c.post("/settings/test", headers=H)))
    th.start()
    time.sleep(0.5)
    second = c.post("/settings/test", headers=H)
    th.join()
    assert second.status_code == 409
    assert first["r"].status_code == 200 and first["r"].json()["ok"] is True
    assert c.post("/settings/test", headers=H).status_code == 200   # 锁释放了


def test_key_never_in_response_even_if_upstream_echoes(c, monkeypatch):
    """上游 message 里出现 Key（有的网关会回显 Authorization）：经 user_error 打码成 sk-***。"""
    def boom(cfg):
        raise llm_mod.LLMError("x", kind="auth", attempts=1, upstream=f"invalid api key {cfg.api_key}")
    monkeypatch.setattr(llm_mod, "ping", boom)
    use(c, "ok")
    d = run(c)
    assert d["llm_kind"] == "auth" and "sk-***" in d["message"]
    assert KEY not in json.dumps(d)


def test_nothing_persisted(c):
    use(c, "fail-401")
    before = c.get("/sessions", headers=H).json()
    run(c)
    assert c.get("/sessions", headers=H).json() == before
