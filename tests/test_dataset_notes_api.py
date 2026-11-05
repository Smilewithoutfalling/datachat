"""批 4b M2 口径库的接口：增查改停、校验、版本化、软遗忘、409、旧库迁移、post_message 透传与 memory_notes。
docs/roadmap/memory-batch4.md §3.4。全部用假模型。"""
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

PROFIT = {"kind": "metric", "name": "利润", "body": "units * price - cost", "unit": "元", "synonyms": "净利；净利润"}
REFUND = {"kind": "rule", "name": "退款不计", "body": "退款单不计入销售额"}


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
    ds = upload(c, sample_path)
    return c, ds["id"]


def notes_url(dsid, *rest):
    return "/".join([f"/datasets/{dsid}/notes", *rest])


def test_notes_crud_and_validation(home, sample_path):
    c, d = setup(home, sample_path)
    assert c.get(notes_url(d), headers=H).json() == []
    r = c.post(notes_url(d), json=PROFIT, headers=H)
    assert r.status_code == 200, r.text
    n = r.json()
    assert {k: n[k] for k in ("kind", "name", "body", "unit", "synonyms", "source", "supersedes", "retired_at")} == {
        "kind": "metric", "name": "利润", "body": "units * price - cost", "unit": "元", "synonyms": "净利,净利润",
        "source": "explicit_user", "supersedes": None, "retired_at": None}
    assert n["sha"] == M.note_sha(M.clean(PROFIT)) and len(n["sha"]) == 12
    assert c.post(notes_url(d), json=REFUND, headers=H).status_code == 200
    assert [x["name"] for x in c.get(notes_url(d), headers=H).json()] == ["利润", "退款不计"]
    # 校验：400 带中文原因
    for bad, why in [({**PROFIT, "kind": "formula"}, "类型"), ({**PROFIT, "name": "  "}, "名称"),
                     ({**PROFIT, "name": "x" * 65}, "64"), ({**PROFIT, "body": "b" * 2001}, "2000"),
                     ({**PROFIT, "unit": "u" * 17}, "16"), ({**PROFIT, "synonyms": "s" * 201}, "200")]:
        r = c.post(notes_url(d), json=bad, headers=H)
        assert r.status_code == 400 and why in r.json()["detail"], (bad, r.text)
    # 控制字符剥掉
    r = c.post(notes_url(d), json={"kind": "rule", "name": "含\x1b税\u202e", "body": "金额\x00含税"}, headers=H)
    assert r.json()["name"] == "含税" and r.json()["body"] == "金额含税"
    # 不存在的数据集 / 口径 → 404；要 token
    assert c.get(notes_url("nope"), headers=H).status_code == 404
    assert c.put(notes_url(d, "nope"), json=PROFIT, headers=H).status_code == 404
    assert c.get(notes_url(d)).status_code == 401


def test_notes_put_creates_new_version(home, sample_path):
    c, d = setup(home, sample_path)
    old = c.post(notes_url(d), json=PROFIT, headers=H).json()
    r = c.put(notes_url(d, old["id"]), json={**PROFIT, "body": "units * price - cost - tax"}, headers=H)
    assert r.status_code == 200
    new = r.json()
    assert new["id"] != old["id"] and new["supersedes"] == old["id"] and new["sha"] != old["sha"]
    active = c.get(notes_url(d), headers=H).json()
    assert [x["id"] for x in active] == [new["id"]]
    hist = c.get(notes_url(d) + "?history=1", headers=H).json()
    by_id = {x["id"]: x for x in hist}
    assert by_id[old["id"]]["retired_at"] and by_id[old["id"]]["body"] == "units * price - cost"   # 旧行内容不改
    # 内容没变：不产生新版本
    same = c.put(notes_url(d, new["id"]), json={**PROFIT, "body": "units * price - cost - tax"}, headers=H).json()
    assert same["id"] == new["id"] and len(c.get(notes_url(d) + "?history=1", headers=H).json()) == 2
    # 已被取代的旧行不能再改
    assert c.put(notes_url(d, old["id"]), json=PROFIT, headers=H).status_code == 409
    # 改名撞上另一条在用的 → 409
    other = c.post(notes_url(d), json={**PROFIT, "name": "毛利"}, headers=H).json()
    assert c.put(notes_url(d, other["id"]), json={**PROFIT, "name": "利润"}, headers=H).status_code == 409


def test_notes_delete_is_soft(home, sample_path):
    c, d = setup(home, sample_path)
    n = c.post(notes_url(d), json=PROFIT, headers=H).json()
    r = c.delete(notes_url(d, n["id"]), headers=H)
    assert r.status_code == 204
    assert c.get(notes_url(d), headers=H).json() == []
    hist = c.get(notes_url(d) + "?history=1", headers=H).json()
    assert len(hist) == 1 and hist[0]["retired_at"]
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        assert con.execute("select count(*) from dataset_notes").fetchone()[0] == 1     # 行还在
    assert c.delete(notes_url(d, n["id"]), headers=H).status_code == 204              # 再停一次也是 204
    # 停用后可以重新加同名
    assert c.post(notes_url(d), json=PROFIT, headers=H).status_code == 200


def test_notes_duplicate_active_name_409(home, sample_path):
    c, d = setup(home, sample_path)
    assert c.post(notes_url(d), json=PROFIT, headers=H).status_code == 200
    r = c.post(notes_url(d), json={**PROFIT, "body": "别的公式"}, headers=H)
    assert r.status_code == 409 and "编辑" in r.json()["detail"]
    # 同名不同类型可以并存（唯一性是 (kind, name)）
    assert c.post(notes_url(d), json={**REFUND, "name": "利润"}, headers=H).status_code == 200
    # 别的数据集同名不冲突
    d2 = upload(c, sample_path, name="另一个")["id"]
    assert c.post(notes_url(d2), json=PROFIT, headers=H).status_code == 200


def test_unique_index_backstops_route(home, sample_path):
    """部分唯一索引兜底：绕过路由直接插第二条在用的同名行会被数据库拒绝；停用的行不占名额。"""
    c, d = setup(home, sample_path)
    c.post(notes_url(d), json=PROFIT, headers=H)
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        row = ("x1", d, "metric", "利润", "b", "", "", "", "explicit_user", None, None, "t")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("insert into dataset_notes values (?,?,?,?,?,?,?,?,?,?,?,?)", row)
        con.execute("insert into dataset_notes values (?,?,?,?,?,?,?,?,?,?,?,?)", row[:10] + ("t", "t"))


def test_old_db_gets_notes_table(home, sample_path):
    """旧库（批 4b 之前没有 dataset_notes）启动后：新表出现，旧表结构与行数不变，口径接口直接可用。"""
    m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
    c, d = setup(home, sample_path, factory=lambda: m)
    s = c.post("/sessions", json={"dataset_id": d, "agent": "react"}, headers=H).json()
    c.post(f"/sessions/{s['id']}/messages", json={"content": "总销量"}, headers=H)
    db = os.path.join(home, "datachat.db")
    old_tables = ("datasets", "dataset_files", "sessions", "messages", "events", "feedback", "settings", "connections")
    with sqlite3.connect(db) as con:
        con.execute("drop table dataset_notes")         # 还原成批 4a 的库
        before = {t: (con.execute(f"select count(*) from {t}").fetchone()[0],
                      con.execute(f"pragma table_info({t})").fetchall()) for t in old_tables}
        assert "dataset_notes" not in {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    del c
    c2 = TestClient(create_app(home, TOKEN))
    with sqlite3.connect(db) as con:
        names = {r[0] for r in con.execute("select name from sqlite_master")}
        assert {"dataset_notes", "ux_dataset_notes_active", "ix_dataset_notes_dataset_id"} <= names
        after = {t: (con.execute(f"select count(*) from {t}").fetchone()[0],
                     con.execute(f"pragma table_info({t})").fetchall()) for t in old_tables}
        fks = con.execute("pragma foreign_key_list(dataset_notes)").fetchall()
    assert after == before and before["messages"][0] == 2
    assert [(f[2], f[3], f[4], f[6]) for f in fks] == [("datasets", "dataset_id", "id", "CASCADE")]
    assert c2.post(notes_url(d), json=PROFIT, headers=H).status_code == 200


# ------------------------------------------------------------------ post_message 透传
def _ask(c, sid, q):
    return sse(c.post(f"/sessions/{sid}/messages", json={"content": q}, headers=H).text)[-1][1]["data"]["result"]


@pytest.mark.parametrize("agent", ["react", "workflow"])
def test_post_message_injects_notes_when_state(home, sample_path, agent):
    seen = []

    def respond(messages):
        seen.append(messages)
        t = "".join(str(m.content) for m in messages)
        if agent == "workflow":
            if "数据分析规划助手" in t:
                return "计划"
            if "写一段 pandas 代码" in t:
                return "result = 1"
            return "结论"
        return tc("result = 1") if len(seen) % 2 == 1 else "好"
    m = ScriptedChatModel(responder=respond, calls=[])
    c, d = setup(home, sample_path, factory=lambda: m)
    n = c.post(notes_url(d), json=PROFIT, headers=H).json()
    s = c.post("/sessions", json={"dataset_id": d, "agent": agent}, headers=H).json()
    # off：不注入，memory_notes = []
    r = _ask(c, s["id"], "利润是多少")
    assert r["memory_mode"] == "off" and r["memory_notes"] == []
    assert not any(M.BLOCK_HEAD in str(x.content) for msgs in seen for x in msgs)
    seen.clear()
    c.put("/settings", json={"memory_mode": "state"}, headers=H)
    r = _ask(c, s["id"], "利润是多少")
    assert r["memory_mode"] == "state" and r["memory_notes"] == [{"name": "利润", "sha": n["sha"]}]
    assert any(M.BLOCK_HEAD in str(x.content) for msgs in seen for x in msgs)
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        stored = json.loads(con.execute("select result_json from messages where role='assistant' "
                                        "order by created_at desc, rowid desc limit 1").fetchone()[0])
    assert stored["memory_notes"] == r["memory_notes"]
    # 停用后不再注入
    c.delete(notes_url(d, n["id"]), headers=H)
    seen.clear()
    r = _ask(c, s["id"], "利润是多少")
    assert r["memory_notes"] == [] and not any(M.BLOCK_HEAD in str(x.content) for msgs in seen for x in msgs)


def test_settings_reports_rewrite_setting_and_env(home, monkeypatch):
    c = TestClient(create_app(home, TOKEN))
    mem = c.get("/settings", headers=H).json()["memory"]
    assert mem["rewrite"] is False and mem["rewrite_setting"] is False and mem["rewrite_env"] is None
    mem = c.put("/settings", json={"memory_mode": "full", "memory_rewrite": True}, headers=H).json()["memory"]
    assert mem == {"mode": "full", "setting": "full", "env": None, "rewrite": True, "rewrite_setting": True,
                   "rewrite_env": None}
    monkeypatch.setenv("DATACHAT_REWRITE", "0")
    mem = c.get("/settings", headers=H).json()["memory"]
    assert mem["rewrite"] is False and mem["rewrite_setting"] is True and mem["rewrite_env"] is False
