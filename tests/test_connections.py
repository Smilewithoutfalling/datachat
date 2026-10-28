"""阶段 6.5 §3 / §4 / §6 第 1 条：/providers、/connections* 接口，旧 /settings 作用于生效连接，迁移 4 种情况，
消息 meta。走真 HTTP 的假模型服务（tests/fake_llm.py）。Key 不出现在任何响应里：每个响应都过 assert_no_key。
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core import keystore
from app.core import llm as llm_mod
from app.server import connections as conns
from app.server.app import create_app
from app.server.db import Connection, Setting, make_sessionmaker
from tests.fake_llm import MODEL_LIST, make_server
from tests.test_server import H, TOKEN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "sk-connsecret0123456789"
KEY2 = "AIzaSyNotAnSkKey0123456789"     # 不是 sk- 开头：T11 的 _KEY 正则打不了码，靠连接测试里按原值打码


@pytest.fixture(scope="module")
def fake_root():
    srv = make_server()
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy",
              "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DATACHAT_LLM_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)


class C:
    """TestClient 包一层：每个响应都断言不含任何 Key。"""

    def __init__(self, client, root):
        self.c, self.root = client, root

    def __getattr__(self, name):
        fn = getattr(self.c, name)

        def call(*a, **kw):
            kw.setdefault("headers", H)
            r = fn(*a, **kw)
            assert KEY not in r.text and KEY2 not in r.text, r.text
            return r
        return call


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


@pytest.fixture
def c(home, fake_root):
    return C(TestClient(create_app(home, TOKEN)), fake_root)


def new(c, name="甲", provider="custom", model="ok", **kw):
    body = {"name": name, "provider": provider, "model": model}
    if provider in ("custom", "ollama", "lmstudio", "newapi") and "base_url" not in kw:
        body["base_url"] = c.root + "/v1"
    body.update(kw)
    r = c.post("/connections", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def with_key(c, cid, key=KEY):
    r = c.put(f"/connections/{cid}/api-key", json={"api_key": key})
    assert r.status_code == 200, r.text
    assert r.json() == {"needed": True, "configured": True}


# ------------------------------------------------------------------ 鉴权、预设
def test_all_new_routes_require_bearer(c):
    raw = c.c
    for m, p in [("get", "/providers"), ("get", "/connections"), ("post", "/connections"), ("put", "/connections/x"),
                 ("delete", "/connections/x"), ("put", "/connections/x/api-key"), ("delete", "/connections/x/api-key"),
                 ("post", "/connections/x/activate"), ("post", "/connections/x/test"), ("get", "/connections/x/models")]:
        assert getattr(raw, m)(p).status_code == 401, (m, p)


def test_providers_catalog(c):
    d = c.get("/providers").json()
    ids = [p["id"] for p in d["providers"]]
    assert len(ids) == 20 and ids[0] == "deepseek" and ids[-1] == "custom"
    assert d["protocols"] == ["openai_chat", "openai_responses", "azure", "anthropic"]


# ------------------------------------------------------------------ 没有连接：环境变量虚拟连接
def test_empty_lists_readonly_env_connection(c, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    monkeypatch.setenv("DEEPSEEK_MODEL", "ok")
    d = c.get("/connections").json()
    assert d["active"] == "env" and len(d["items"]) == 1
    env = d["items"][0]
    assert env["readonly"] is True and env["name"] == "环境变量" and env["model"] == "ok"
    assert env["key"] == {"needed": True, "configured": True, "source": "env"}
    for m, p in [("put", "/connections/env"), ("delete", "/connections/env"), ("post", "/connections/env/activate"),
                 ("put", "/connections/env/api-key")]:
        r = getattr(c, m)(p) if m == "delete" else getattr(c, m)(p, json={"name": "x", "api_key": "kkkkkkkk"})
        assert r.status_code == 400 and "只读" in r.json()["detail"], (m, p)


def test_env_connection_test_and_probe_saved(c, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", c.root + "/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "notools")
    r = c.post("/connections/env/test").json()
    assert r["connect"]["ok"] is True and r["tools"]["ok"] is False and r["ok"] is False
    probe = c.get("/connections").json()["items"][0]["probe"]
    assert probe["model"] == "notools" and probe["connect"] is True and probe["tools"] is False


# ------------------------------------------------------------------ CRUD
def test_create_first_becomes_active_and_env_disappears(c):
    a = new(c, "甲")
    assert a["active"] is True and a["key"] == {"needed": True, "configured": False}
    assert a["protocol"] == "openai_chat" and a["probe"] is None and a["readonly"] is False
    b = new(c, "乙")
    assert b["active"] is False
    d = c.get("/connections").json()
    assert d["active"] == a["id"] and [x["name"] for x in d["items"]] == ["甲", "乙"]
    assert c.post("/connections/env/test").status_code == 404     # 有连接后环境变量不再生效


def test_create_validation(c):
    def bad(body, code=400):
        r = c.post("/connections", json=body)
        assert r.status_code == code, (body, r.text)
        return r.json()["detail"]
    assert "未知服务商" in bad({"name": "x", "provider": "nope", "model": "m"})
    assert "需要填 Base URL" in bad({"name": "x", "provider": "custom", "model": "m"})
    assert "http" in bad({"name": "x", "provider": "custom", "model": "m", "base_url": "ftp://a"})
    assert "不能改" in bad({"name": "x", "provider": "deepseek", "model": "m", "protocol": "anthropic"})
    assert "自定义连接的协议" in bad({"name": "x", "provider": "custom", "model": "m", "base_url": "https://a",
                                 "protocol": "azure"})
    assert "模型名不能为空" in bad({"name": "x", "provider": "deepseek", "model": " "})
    assert bad({"name": "", "provider": "deepseek", "model": "m"}, 422)
    new(c, "同名")
    assert "同名" in bad({"name": "同名", "provider": "deepseek", "model": "m"}, 409)


def test_create_defaults_from_preset(c):
    d = new(c, "DS", "deepseek", "deepseek-flash")
    assert d["base_url"] == "https://api.deepseek.com" and d["quirks"]["reasoning_replay"] is True
    a = new(c, "Claude", "anthropic", "claude-sonnet-5-5")
    assert a["protocol"] == "anthropic" and a["base_url"] == "https://api.anthropic.com"
    z = new(c, "Az", "azure", "", base_url="https://r.openai.azure.com",
            extra={"deployment": "gpt-dep", "api_version": "2024-10-21"})
    # Azure 走 v1 路径，不再存 api_version（传了也忽略）
    assert z["model"] == "gpt-dep" and z["extra"] == {"deployment": "gpt-dep"}
    o = new(c, "本地", "ollama", "qwen3:8b", base_url="http://localhost:11434/v1")
    assert o["key"] == {"needed": False, "configured": False}
    x = new(c, "自定义 Claude", "custom", "ok", protocol="anthropic", base_url=c.root)
    assert x["protocol"] == "anthropic"


def test_update_and_quirk_override_and_probe_reset(c):
    a = new(c, "甲")
    with_key(c, a["id"])
    assert c.post(f"/connections/{a['id']}/test").json()["ok"] is True
    assert c.get("/connections").json()["items"][0]["probe"]["tools"] is True
    r = c.put(f"/connections/{a['id']}", json={"name": " 甲改 ", "extra": {"quirks": {"no_array_content": True}}}).json()
    assert r["name"] == "甲改" and r["quirks"]["no_array_content"] is True and r["probe"] is None   # 怪癖变了，旧结果作废
    assert c.post(f"/connections/{a['id']}/test").json()["ok"] is True
    r = c.put(f"/connections/{a['id']}", json={"model": "notools"}).json()
    assert r["probe"] is None                                      # probe 按「连接 + 模型」，换模型就当没测过
    r = c.put(f"/connections/{a['id']}", json={"model": "ok"}).json()
    assert r["probe"]["model"] == "ok"                            # 换回来，之前那次测试仍对得上
    r = c.put(f"/connections/{a['id']}", json={"provider": "deepseek"}).json()
    assert r["provider"] == "deepseek" and r["base_url"] == "https://api.deepseek.com" and r["probe"] is None
    assert c.put("/connections/nope", json={"name": "x"}).status_code == 404
    new(c, "乙")
    assert c.put(f"/connections/{a['id']}", json={"name": "乙"}).status_code == 409


def test_activate_and_delete(c):
    a, b = new(c, "甲"), new(c, "乙")
    with_key(c, a["id"])
    with_key(c, b["id"], KEY2)
    d = c.post(f"/connections/{b['id']}/activate").json()
    assert d["active"] == b["id"]
    d = c.delete(f"/connections/{b['id']}").json()          # 删的是生效连接 → 最早建的那个生效
    assert d["active"] == a["id"] and [x["name"] for x in d["items"]] == ["甲"]
    assert keystore.get_api_key(keystore.conn_account(b["id"])) is None    # Key 一起删了
    assert keystore.get_api_key(keystore.conn_account(a["id"])) == KEY
    d = c.delete(f"/connections/{a['id']}").json()
    assert d["active"] == "env" and d["items"][0]["readonly"] is True
    assert keystore.get_api_key(keystore.conn_account(a["id"])) is None
    assert c.delete("/connections/nope").status_code == 404


def test_key_put_delete(c):
    a = new(c, "甲")
    with_key(c, a["id"])
    assert keystore.get_api_key(f"conn:{a['id']}") == KEY
    assert keystore.get_api_key() is None                      # 不碰旧的 llm_api_key 条目
    r = c.delete(f"/connections/{a['id']}/api-key").json()
    assert r == {"needed": True, "configured": False}
    assert c.put(f"/connections/{a['id']}/api-key", json={"api_key": "has space"}).status_code == 400


# ------------------------------------------------------------------ 测试连接（两步）
def test_test_two_steps(c):
    a = new(c, "甲", model="ok")
    r = c.post(f"/connections/{a['id']}/test").json()             # 没 Key：不发请求
    assert r["connect"]["llm_kind"] == "no_key" and r["tools"] is None and r["ok"] is False
    with_key(c, a["id"])
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["ok"] is True and r["connect"]["ok"] is True and r["tools"]["ok"] is True and r["model"] == "ok"
    assert set(r["probe"]) == {"model", "connect", "tools", "checked_at"}
    c.put(f"/connections/{a['id']}", json={"model": "notools"})
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["connect"]["ok"] is True and r["tools"]["ok"] is False and "不支持工具调用" in r["tools"]["message"]
    c.put(f"/connections/{a['id']}", json={"model": "fail-401"})
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["connect"]["llm_kind"] == "auth" and r["connect"]["message"].startswith("鉴权失败") and r["tools"] is None
    assert "（编号 " in r["connect"]["message"]
    stored = c.get("/connections").json()["items"][0]["probe"]
    assert stored == {**r["probe"]} and stored["connect"] is False and stored["tools"] is None


def test_test_tools_bad_request_counts_as_unsupported(c, monkeypatch):
    a = new(c, "甲", model="ok")
    with_key(c, a["id"])

    def boom(cfg):
        raise llm_mod.LLMError("x", kind="bad_request", attempts=1, upstream="tool_choice is not supported")
    monkeypatch.setattr(conns, "probe_tools", boom)
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["tools"]["ok"] is False and "tool_choice is not supported" in r["tools"]["message"]

    def slow(cfg):
        raise llm_mod.LLMError("x", kind="timeout", attempts=1, upstream="")
    monkeypatch.setattr(conns, "probe_tools", slow)
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["tools"]["ok"] is None and r["ok"] is True          # 超时 = 没测出来，不下结论，不拦


def test_test_needs_no_key_for_local_provider(c):
    a = new(c, "本地", "ollama", "ok", base_url=c.root + "/v1")
    r = c.post(f"/connections/{a['id']}/test").json()
    assert r["ok"] is True


def test_test_shares_lock_with_settings_test(c):
    a = new(c, "甲", model="hang-2s")
    with_key(c, a["id"])
    first = {}
    th = threading.Thread(target=lambda: first.setdefault("r", c.post(f"/connections/{a['id']}/test")))
    th.start()
    time.sleep(0.5)
    assert c.post("/settings/test").status_code == 409
    assert c.post(f"/connections/{a['id']}/test").status_code == 409
    th.join()
    assert first["r"].status_code == 200


def test_test_scrubs_non_sk_key(c, monkeypatch):
    a = new(c, "甲")
    with_key(c, a["id"], KEY2)

    def echo(cfg):
        raise llm_mod.LLMError("x", kind="auth", attempts=1, upstream=f"invalid api key {cfg.api_key}")
    monkeypatch.setattr(conns, "ping", echo)
    r = c.post(f"/connections/{a['id']}/test").json()             # 包装类已断言 KEY2 不在响应里
    assert r["connect"]["llm_kind"] == "auth" and "***" in r["connect"]["message"]


# ------------------------------------------------------------------ 获取模型列表
def test_models_remote(c):
    a = new(c, "甲")
    with_key(c, a["id"])
    assert c.get(f"/connections/{a['id']}/models").json() == {"source": "remote", "models": sorted(MODEL_LIST)}
    b = new(c, "Claude", "custom", "ok", protocol="anthropic", base_url=c.root)
    with_key(c, b["id"])
    assert c.get(f"/connections/{b['id']}/models").json()["models"] == sorted(MODEL_LIST)


def test_models_failure_falls_back_to_preset(c):
    a = new(c, "DS", "deepseek", "deepseek-flash")
    with_key(c, a["id"])
    c.put(f"/connections/{a['id']}", json={"provider": "deepseek"})
    with Session_of(c) as db:      # 预设服务商的地址也能改（指到假服务的失败前缀）
        row = db.get(Connection, a["id"])
        row.base_url = c.root + "/fail-500/v1"
        db.commit()
    r = c.get(f"/connections/{a['id']}/models").json()
    assert r["source"] == "preset" and r["models"] == ["deepseek-flash", "deepseek-v4-pro"]
    assert r["llm_kind"] == "server" and r["reason"].startswith("模型服务出错")


def test_models_timeout(c, monkeypatch):
    monkeypatch.setattr(llm_mod, "MODELS_TIMEOUT", 0.5)      # 产品里 10 秒
    a = new(c, "甲", base_url=c.root + "/hang-3s/v1")
    with_key(c, a["id"])
    t = time.monotonic()
    r = c.get(f"/connections/{a['id']}/models").json()
    assert time.monotonic() - t < 2.5
    assert r["source"] == "preset" and r["models"] == [] and r["llm_kind"] == "timeout"


def test_models_no_key_and_azure(c):
    a = new(c, "DS", "deepseek", "deepseek-flash")
    r = c.get(f"/connections/{a['id']}/models").json()
    assert r["source"] == "preset" and r["reason"].startswith("未配置 API Key")
    z = new(c, "Az", "azure", "d", base_url="https://r.openai.azure.com")
    with_key(c, z["id"])
    assert "部署名" in c.get(f"/connections/{z['id']}/models").json()["reason"]


def Session_of(c):
    return make_sessionmaker(c.c.app.state.home + "/datachat.db")()


# ------------------------------------------------------------------ 旧接口作用于生效连接
def test_legacy_settings_follow_active_connection(c, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    s = c.get("/settings").json()
    assert s["connection"] == {"id": "env", "name": "环境变量"} and s["sources"]["model"] == "default"
    assert c.get("/settings/api-key").json() == {"configured": True, "source": "env"}
    a = new(c, "甲", model="ok")
    s = c.get("/settings").json()
    assert s["connection"] == {"id": a["id"], "name": "甲"} and s["model"] == "ok"
    assert s["sources"]["model"] == s["sources"]["base_url"] == "connection" and s["sources"]["timeout"] == "default"
    assert c.get("/settings/api-key").json() == {"configured": False, "source": None}   # 环境变量的 Key 不再算数
    s = c.put("/settings", json={"model": "notools", "timeout": 30}).json()
    assert s["model"] == "notools" and s["timeout"] == 30
    assert c.get("/connections").json()["items"][0]["model"] == "notools"
    assert c.put("/settings/api-key", json={"api_key": KEY2}).json() == {"configured": True, "source": "keyring"}
    assert keystore.get_api_key(f"conn:{a['id']}") == KEY2
    r = c.post("/settings/test").json()          # 旧的一步测试：测的是生效连接
    assert r == {"ok": True, "latency_ms": r["latency_ms"], "model": "notools"}
    assert c.delete("/settings/api-key").json() == {"configured": False, "source": None}
    assert c.put("/settings", json={"model": " "}).status_code == 400


def test_legacy_key_status_no_key_provider(c):
    new(c, "本地", "ollama", "ok", base_url=c.root + "/v1")
    assert c.get("/settings/api-key").json() == {"configured": True, "source": None}


# ------------------------------------------------------------------ 消息 meta
def test_message_meta_records_connection_and_model(c, home):
    from tests.test_server import sse, upload
    a = new(c, "我的假服务", model="ok")
    with_key(c, a["id"])
    ds = upload(c.c, os.path.join(ROOT, "data", "sample.csv"))["id"]
    sid = c.post("/sessions", json={"dataset_id": ds, "agent": "workflow"}).json()["id"]
    r = c.post(f"/sessions/{sid}/messages", json={"content": "多少行"})
    (done,) = [d for t, d in sse(r.text) if t == "done"]
    assert done["data"]["result"]["meta"] == {"connection_id": a["id"], "connection_name": "我的假服务", "model": "ok"}
    msg = c.get(f"/sessions/{sid}").json()["messages"][1]
    assert msg["status"] == "ok" and msg["result"]["meta"]["connection_name"] == "我的假服务"


# ------------------------------------------------------------------ 迁移（§4）
def seed(home, settings=None, key=None):
    os.makedirs(home, exist_ok=True)
    S = make_sessionmaker(os.path.join(home, "datachat.db"))
    with S() as db:
        for k, v in (settings or {}).items():
            db.add(Setting(key=k, value=v))
        db.commit()
    if key:
        keystore.set_api_key(key)
    return S


def migrated(home):
    c = TestClient(create_app(home, TOKEN))
    return c, c.get("/connections", headers=H).json()


def test_migrate_empty_db(home):
    _, d = migrated(home)
    assert d["active"] == "env" and d["items"][0]["readonly"] is True


def test_migrate_key_only(home):
    seed(home, key=KEY)
    _, d = migrated(home)
    (x,) = d["items"]
    assert (x["name"], x["provider"], x["base_url"], x["model"]) == ("DeepSeek", "deepseek", "https://api.deepseek.com",
                                                                     "deepseek-chat")
    assert d["active"] == x["id"] and x["key"]["configured"] is True
    assert keystore.get_api_key(f"conn:{x['id']}") == KEY and keystore.get_api_key() == KEY   # 旧条目保留


def test_migrate_url_only(home):
    seed(home, {"base_url": "https://llm.grgbanking.example/v1", "model": "qwen3-32b"})
    _, d = migrated(home)
    (x,) = d["items"]
    assert (x["name"], x["provider"], x["protocol"], x["base_url"], x["model"]) == (
        "我的连接", "custom", "openai_chat", "https://llm.grgbanking.example/v1", "qwen3-32b")
    assert x["key"]["configured"] is False and d["active"] == x["id"]


def test_migrate_url_and_key(home):
    seed(home, {"base_url": "https://gw.example/v1", "model": "m1", "timeout": "90"}, key=KEY)
    c, d = migrated(home)
    (x,) = d["items"]
    assert x["name"] == "我的连接" and x["key"]["configured"] is True
    assert keystore.get_api_key(f"conn:{x['id']}") == KEY
    s = c.get("/settings", headers=H).json()
    assert s["timeout"] == 90 and s["connection"]["name"] == "我的连接"


@pytest.mark.parametrize("url", ["https://api.deepseek.com/v1", "https://api.deepseek.com", ""])
def test_migrate_deepseek_urls(home, url):
    seed(home, {"base_url": url, "model": "deepseek-chat"} if url else {"model": "deepseek-chat"})
    _, d = migrated(home)
    x = d["items"][0]
    assert x["provider"] == "deepseek" and x["name"] == "DeepSeek"
    assert x["base_url"] == (url or "https://api.deepseek.com")


def test_migrate_runs_once(home):
    seed(home, key=KEY)
    c, d = migrated(home)
    cid = d["items"][0]["id"]
    c.delete(f"/connections/{cid}", headers=H)       # 用户删掉迁移出来的连接后重启：不再迁一次
    _, d = migrated(home)
    assert d["active"] == "env"


def test_migrate_env_key_is_not_migrated(home, monkeypatch):
    """环境变量不是存储（下次启动照样在），不迁：没有连接，仍走环境变量虚拟连接。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    _, d = migrated(home)
    assert d["active"] == "env"
