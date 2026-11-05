"""批 4b M10 口径的生命周期：随数据集级联删除、导入（CSV / JSON，幂等、整批校验）、导出、sha、跨会话共用。
docs/roadmap/memory-batch4.md §3.5。"""
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.core.testing import ScriptedChatModel
from app.memory import metrics as M
from app.server.app import create_app
from tests.test_server import H, TOKEN, sse, upload

CSV = "kind,name,body,unit,synonyms\nmetric,利润,units * price - cost,元,净利;净利润\nrule,退款不计,退款单不计入销售额,,\n"


def tc(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": f"c{i}"}])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


def setup(home, sample_path, factory=None):
    c = TestClient(create_app(home, TOKEN, chat_model_factory=factory))
    return c, upload(c, sample_path)["id"]


def imp(c, d, body, ctype="text/csv"):
    data = body.encode("utf-8") if isinstance(body, str) else body
    return c.post(f"/datasets/{d}/notes/import", content=data, headers={**H, "Content-Type": ctype})


def active(c, d):
    return c.get(f"/datasets/{d}/notes", headers=H).json()


def test_notes_deleted_with_dataset(home, sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    c, d = setup(home, sample_path, factory=lambda: m)
    keep = upload(c, sample_path, name="留着")["id"]
    assert imp(c, d, CSV).status_code == 200 and imp(c, keep, CSV).status_code == 200
    s = c.post("/sessions", json={"dataset_id": d, "agent": "react"}, headers=H).json()
    c.post(f"/sessions/{s['id']}/messages", json={"content": "总销量"}, headers=H)
    c.delete(f"/datasets/{d}/notes/{active(c, d)[0]['id']}", headers=H)      # 停用的行也要一起删
    assert c.delete(f"/datasets/{d}", headers=H).status_code == 200
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        assert con.execute("select count(*) from dataset_notes where dataset_id=?", (d,)).fetchone()[0] == 0
        assert con.execute("select count(*) from sessions where dataset_id=?", (d,)).fetchone()[0] == 0
        assert con.execute("select count(*) from dataset_notes where dataset_id=?", (keep,)).fetchone()[0] == 2
    assert c.get(f"/datasets/{d}/notes", headers=H).status_code == 404
    assert len(active(c, keep)) == 2


def test_import_csv_idempotent(home, sample_path):
    c, d = setup(home, sample_path)
    r = imp(c, d, CSV)
    assert r.status_code == 200 and r.json() == {"added": 2, "updated": 0, "unchanged": 0, "errors": []}
    got = {x["name"]: x for x in active(c, d)}
    assert got["利润"]["synonyms"] == "净利,净利润" and got["退款不计"]["kind"] == "rule"
    r = imp(c, d, CSV)
    assert r.json() == {"added": 0, "updated": 0, "unchanged": 2, "errors": []}
    assert len(c.get(f"/datasets/{d}/notes?history=1", headers=H).json()) == 2      # 没有重复行
    # GBK 编码的 CSV（Excel 常见）同样能读
    gbk = "kind,name,body\nrule,含税,金额一律含税\n".encode("gb18030")
    assert imp(c, d, gbk).json()["added"] == 1


def test_import_changed_body_supersedes(home, sample_path):
    c, d = setup(home, sample_path)
    imp(c, d, CSV)
    old = {x["name"]: x for x in active(c, d)}["利润"]
    r = imp(c, d, CSV.replace("units * price - cost", "units * price - cost - tax"))
    assert r.json() == {"added": 0, "updated": 1, "unchanged": 1, "errors": []}
    new = {x["name"]: x for x in active(c, d)}["利润"]
    assert new["supersedes"] == old["id"] and new["sha"] != old["sha"]
    hist = {x["id"]: x for x in c.get(f"/datasets/{d}/notes?history=1", headers=H).json()}
    assert hist[old["id"]]["retired_at"] and hist[old["id"]]["body"] == "units * price - cost"


def test_import_rejects_whole_batch_on_bad_row(home, sample_path):
    c, d = setup(home, sample_path)
    bad = CSV + "formula,坏的,x,,\nmetric,,没有名字,,\n"
    r = imp(c, d, bad)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "第 4 行" in detail and "第 5 行" in detail and "没有写入任何一条" in detail
    assert active(c, d) == []                                  # 不写一半
    dup = CSV + "metric,利润,别的公式,,\n"
    r = imp(c, d, dup)
    assert r.status_code == 400 and "与第 2 行同名" in r.json()["detail"] and active(c, d) == []
    assert imp(c, d, "name,body\na,b\n").status_code == 400    # 表头缺 kind
    assert imp(c, d, "").status_code == 400
    assert imp(c, d, b"\xff\xfe\x00bad\x81", "text/csv").status_code in (200, 400)   # 编码探测：不 500
    assert imp(c, d, "{not json", "application/json").status_code == 400
    assert imp(c, d, json.dumps({"kind": "rule"}), "application/json").status_code == 400
    r = imp(c, d, json.dumps([{"kind": "rule", "name": "a", "body": "b"}, "x"]), "application/json")
    assert r.status_code == 400 and "第 2 行" in r.json()["detail"] and active(c, d) == []
    assert c.post("/datasets/nope/notes/import", content=CSV.encode(), headers=H).status_code == 404


def test_import_json_array(home, sample_path):
    c, d = setup(home, sample_path)
    body = json.dumps([{"kind": "metric", "name": "利润", "body": "a - b", "synonyms": ["净利", "净利润"]},
                       {"kind": "规则", "name": "含税", "body": "金额含税"}], ensure_ascii=False)
    r = imp(c, d, body, "application/json")
    assert r.json()["added"] == 2
    got = {x["name"]: x for x in active(c, d)}
    assert got["利润"]["synonyms"] == "净利,净利润" and got["含税"]["kind"] == "rule"


def test_export_roundtrip(home, sample_path):
    c, d = setup(home, sample_path)
    imp(c, d, CSV)
    c.post(f"/datasets/{d}/notes", json={"kind": "rule", "name": "停掉的", "body": "x"}, headers=H)
    c.delete(f"/datasets/{d}/notes/{[x for x in active(c, d) if x['name'] == '停掉的'][0]['id']}", headers=H)
    r = c.get(f"/datasets/{d}/notes/export?format=csv", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "kind,name,body,unit,synonyms" and "净利;净利润" in text and "停掉的" not in text
    j = c.get(f"/datasets/{d}/notes/export?format=json", headers=H).json()
    assert {x["name"] for x in j} == {"利润", "退款不计"}
    # 重新上传的数据集：导入导出的文件 → 内容与 sha 完全一致
    d2 = upload(c, sample_path, name="重新上传")["id"]
    assert imp(c, d2, r.content).json()["added"] == 2
    d3 = upload(c, sample_path, name="再来一次")["id"]
    assert imp(c, d3, json.dumps(j, ensure_ascii=False), "application/json").json()["added"] == 2
    sha = lambda x: sorted((n["name"], n["sha"]) for n in active(c, x))      # noqa: E731
    assert sha(d) == sha(d2) == sha(d3)
    assert c.get(f"/datasets/{d}/notes/export?format=xml", headers=H).status_code == 422


def test_note_sha_changes_on_body_edit(home, sample_path):
    c, d = setup(home, sample_path)
    n = c.post(f"/datasets/{d}/notes", json={"kind": "metric", "name": "利润", "body": "a - b"}, headers=H).json()
    assert n["sha"] == M.note_sha({"kind": "metric", "name": "利润", "body": "a - b", "unit": "", "synonyms": ""})
    n2 = c.put(f"/datasets/{d}/notes/{n['id']}", json={"kind": "metric", "name": "利润", "body": "a - b - c"},
               headers=H).json()
    assert n2["sha"] != n["sha"] and len(n2["sha"]) == 12


def test_new_session_uses_old_notes(home, sample_path):
    """第一个会话里加口径，第二个会话（同一数据集）的 system 里出现口径块；别的数据集的会话里没有。"""
    calls = []

    def respond(messages):
        calls.append(messages)
        return tc("result = 1") if len(calls) % 2 == 1 else "好"
    m = ScriptedChatModel(responder=respond, calls=[])
    c, d = setup(home, sample_path, factory=lambda: m)
    other = upload(c, sample_path, name="别的")["id"]
    c.put("/settings", json={"memory_mode": "state"}, headers=H)
    s1 = c.post("/sessions", json={"dataset_id": d, "agent": "react"}, headers=H).json()
    sse(c.post(f"/sessions/{s1['id']}/messages", json={"content": "总销量"}, headers=H).text)
    c.post(f"/datasets/{d}/notes", json={"kind": "metric", "name": "利润", "body": "units * price"}, headers=H)
    calls.clear()
    s2 = c.post("/sessions", json={"dataset_id": d, "agent": "react"}, headers=H).json()
    r = sse(c.post(f"/sessions/{s2['id']}/messages", json={"content": "利润是多少"}, headers=H).text)[-1][1]
    assert M.BLOCK_HEAD in calls[0][0].content and r["data"]["result"]["memory_notes"][0]["name"] == "利润"
    calls.clear()
    s3 = c.post("/sessions", json={"dataset_id": other, "agent": "react"}, headers=H).json()
    sse(c.post(f"/sessions/{s3['id']}/messages", json={"content": "利润是多少"}, headers=H).text)
    assert M.BLOCK_HEAD not in calls[0][0].content
