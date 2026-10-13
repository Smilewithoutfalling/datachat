"""阶段 4：FastAPI 后端。验收路径"上传 → 提问 → 流式结果 → 历史可查 → 重启后会话还在"。全部用假模型。"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core.testing import ScriptedChatModel
from app.server.app import create_app
from tests.test_core_analyze import tool_call, wf_model

TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}


def sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


def client(home, factory=None, **kw):
    return TestClient(create_app(home, TOKEN, chat_model_factory=factory, **kw))


def upload(c, *paths, name=""):
    files = [("files", (os.path.basename(p), open(p, "rb"), "text/csv")) for p in paths]
    r = c.post("/datasets", files=files, data={"name": name}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_and_host(home):
    c = client(home)
    assert c.get("/health").json() == {"ok": True}
    assert c.get("/datasets").status_code == 401
    assert c.get("/datasets", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/datasets", headers=H).status_code == 200
    assert c.get("/datasets", headers={**H, "Host": "evil.example"}).status_code == 400   # DNS rebinding


def test_full_flow_workflow_and_restart(home, sample_path):
    c = client(home, lambda: wf_model(["result = int(df['units'].sum())"], answer="总销量 1685"))
    ds = upload(c, sample_path, os.path.join(os.path.dirname(sample_path), "sample.dict.csv"))
    assert {f["filename"] for f in ds["files"]} == {"sample.csv", "sample.dict.csv"}
    assert "units" in ds["tables"]["df"]
    s = c.post("/sessions", json={"dataset_id": ds["id"], "agent": "workflow"}, headers=H).json()

    r = c.post(f"/sessions/{s['id']}/messages", json={"content": "哪个地区卖得最好"}, headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = sse(r.text)
    assert [t for t, _ in evs] == ["plan", "code", "exec", "answer", "done"]
    msg_id = r.headers["x-message-id"]
    assert all(e["trace_id"] == msg_id for _, e in evs)
    done = evs[-1][1]["data"]["result"]
    assert done["ok"] and done["answer"] == "总销量 1685" and "dataset" not in done
    assert any(f == "region" for f, _ in done["field_notes"])          # 字典随数据集上传后生效

    c2 = client(home)                                                  # 重启：新进程、同一数据目录
    sess = c2.get(f"/sessions/{s['id']}", headers=H).json()
    assert sess["title"] == "哪个地区卖得最好"
    user, asst = sess["messages"]
    assert user["role"] == "user" and user["content"] == "哪个地区卖得最好"
    assert asst["id"] == msg_id and asst["status"] == "ok" and asst["content"] == "总销量 1685"
    assert [e["type"] for e in asst["events"]] == ["plan", "code", "exec", "answer"]
    assert asst["result"]["result_text"]
    assert [x["id"] for x in c2.get("/sessions", headers=H).json()] == [s["id"]]


def test_failure_is_persisted(home, sample_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    c = client(home)                                                   # 真实模型路径，但没有 Key
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    evs = sse(c.post(f"/sessions/{s['id']}/messages", json={"content": "q"}, headers=H).text)
    assert [t for t, _ in evs] == ["error", "done"] and evs[0][1]["data"]["fatal"]
    asst = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"][1]
    assert asst["status"] == "error" and "API Key" in asst["content"]


def test_react_multi_turn_memory_and_chart(home, sample_path):
    replies = [tool_call("plt.plot([1, 2]); plt.savefig(chart_path); result = 1"), "第一轮", "第二轮"]
    m = ScriptedChatModel(replies=replies, calls=[])
    c = client(home, lambda: m)
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"], "agent": "react"}, headers=H).json()
    e1 = sse(c.post(f"/sessions/{s['id']}/messages", json={"content": "画图"}, headers=H).text)
    chart = next(e["data"]["chart"] for t, e in e1 if t == "exec")
    assert chart.startswith("/charts/chart_")
    assert c.get(chart, headers=H).headers["content-type"] == "image/png"
    assert c.get(chart + f"?token={TOKEN}").status_code == 200        # <img src> 用
    assert c.get("/charts/..%2Fdatachat.db", headers=H).status_code == 404
    e2 = sse(c.post(f"/sessions/{s['id']}/messages", json={"content": "接着说"}, headers=H).text)
    assert e2[-1][1]["data"]["result"]["answer"] == "第二轮"
    assert "画图" in str(m.calls[-1]) and "第一轮" in str(m.calls[-1])  # 同一会话带上下文

    m.replies.append("第三轮")                                         # 重启后上下文仍在（从 messages 表重建）
    c2 = client(home, lambda: m)
    sse(c2.post(f"/sessions/{s['id']}/messages", json={"content": "再来"}, headers=H).text)
    last = str(m.calls[-1])
    assert all(x in last for x in ("画图", "第一轮", "接着说", "第二轮", "再来"))


def test_multi_table_dataset(home, tmp_path):
    a, b = tmp_path / "orders.csv", tmp_path / "users.csv"
    a.write_text("oid,uid\n1,1\n2,1\n", encoding="utf-8")
    b.write_text("uid,name\n1,甲\n", encoding="utf-8")
    c = client(home, lambda: wf_model(["result = len(dfs['orders'])"]))
    ds = upload(c, str(a), str(b), name="店铺")
    assert ds["name"] == "店铺" and set(ds["tables"]) == {"orders", "users"}
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    done = sse(c.post(f"/sessions/{s['id']}/messages", json={"content": "订单数"}, headers=H).text)[-1][1]
    assert done["data"]["result"]["result_text"].startswith("2")


@pytest.mark.parametrize("fname", ["../x.csv", "x.txt", ".hidden.csv", "only.dict.csv"])
def test_upload_rejects(home, tmp_path, fname):
    p = tmp_path / "f.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    c = client(home)
    r = c.post("/datasets", files=[("files", (fname, open(p, "rb"), "text/csv"))], headers=H)
    if fname == "../x.csv":                       # 路径部分被去掉，只留文件名，落在数据集自己的目录里
        assert r.status_code == 200 and r.json()["files"][0]["filename"] == "x.csv"
        assert not os.path.exists(os.path.join(home, "datasets", "x.csv"))
    else:
        assert r.status_code == 400
    assert c.get("/datasets", headers=H).status_code == 200


def test_settings_and_api_key_never_returned(home, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    c = client(home)
    assert c.get("/settings/api-key", headers=H).json() == {"configured": False, "source": None}
    r = c.put("/settings/api-key", json={"api_key": "sk-secret-123"}, headers=H)
    assert r.json() == {"configured": True, "source": "keyring"} and "sk-secret" not in r.text
    assert c.put("/settings", json={"model": "qwen-x"}, headers=H).json()["model"] == "qwen-x"
    assert "sk-secret" not in c.get("/settings", headers=H).text
    assert c.delete("/settings/api-key", headers=H).json()["configured"] is False


def test_concurrent_message_rejected_and_running_recovered(home, sample_path):
    from app.server.db import Message, make_sessionmaker
    c = client(home, lambda: wf_model(["result = 1"]))
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    S = make_sessionmaker(os.path.join(home, "datachat.db"))
    with S() as db:
        db.add(Message(session_id=s["id"], role="assistant", status="running"))
        db.commit()
    assert c.post(f"/sessions/{s['id']}/messages", json={"content": "q"}, headers=H).status_code == 409
    c2 = client(home, lambda: wf_model(["result = 1"]))                # 重启：遗留的 running 标成 cancelled
    msgs = c2.get(f"/sessions/{s['id']}", headers=H).json()["messages"]
    assert [m["status"] for m in msgs] == ["cancelled"]
    assert c2.post(f"/sessions/{s['id']}/messages", json={"content": "q"}, headers=H).status_code == 200


def test_delete_dataset_cascades(home, sample_path):
    c = client(home, lambda: wf_model(["result = 1"]))
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    c.post(f"/sessions/{s['id']}/messages", json={"content": "q"}, headers=H)
    assert c.delete(f"/datasets/{ds['id']}", headers=H).json() == {"ok": True}
    assert c.get(f"/sessions/{s['id']}", headers=H).status_code == 404
    assert not os.path.exists(os.path.join(home, "datasets", ds["id"]))
