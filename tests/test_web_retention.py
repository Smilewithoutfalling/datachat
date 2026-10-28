"""阶段 6.6：M0 保留与删除（删会话 / 数据集 / 单条消息连带删图、SQLite 空间回收），以及记忆开关在后端的接线。全部用假模型。"""
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.core.testing import ScriptedChatModel
from app.server.app import create_app
from app.server.db import make_sessionmaker
from app.server.retention import chart_files_of, incremental_vacuum, prepare_auto_vacuum
from tests.test_server import H, TOKEN, sse, upload

PLOT = "plt.plot([1, 2]); plt.savefig(chart_path); result = df.groupby('region')['units'].sum()"


def tc(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": f"c{i}"}])


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


def client(home, m):
    return TestClient(create_app(home, TOKEN, chat_model_factory=lambda: m))


def charts(home):
    d = os.path.join(home, "charts")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def ask(c, sid, text):
    return sse(c.post(f"/sessions/{sid}/messages", json={"content": text}, headers=H).text)


def new_session(c, ds, agent="react"):
    return c.post("/sessions", json={"dataset_id": ds["id"], "agent": agent}, headers=H).json()


# ------------------------------------------------------------------ 删图
def test_delete_session_removes_chart_files(home, sample_path):
    m = ScriptedChatModel(replies=[tc(PLOT), "一", tc(PLOT), "二"], calls=[])
    c = client(home, m)
    ds = upload(c, sample_path)
    s1, s2 = new_session(c, ds), new_session(c, ds)
    ask(c, s1["id"], "画图")
    ask(c, s2["id"], "画图")
    before = charts(home)
    assert len(before) == 2
    assert c.delete(f"/sessions/{s1['id']}", headers=H).status_code == 200
    after = charts(home)
    assert len(after) == 1 and set(after) < set(before)           # 只删这个会话的，别的会话的图还在
    msgs = c.get(f"/sessions/{s2['id']}", headers=H).json()["messages"]
    assert c.get(msgs[1]["result"]["chart_path"], headers=H).status_code == 200


def test_delete_dataset_removes_all_session_charts(home, sample_path, tmp_path):
    m = ScriptedChatModel(replies=[tc(PLOT), "一", tc(PLOT), "二", tc(PLOT), "三"], calls=[])
    c = client(home, m)
    ds, other = upload(c, sample_path), upload(c, sample_path, name="另一个")
    ask(c, new_session(c, ds)["id"], "画图")
    ask(c, new_session(c, ds)["id"], "画图")
    ask(c, new_session(c, other)["id"], "画图")
    assert len(charts(home)) == 3
    assert c.delete(f"/datasets/{ds['id']}", headers=H).status_code == 200
    assert len(charts(home)) == 1


def test_delete_message_removes_pair_and_cascades(home, sample_path):
    m = ScriptedChatModel(replies=[tc(PLOT), "一", tc("result = 1", 2), "二"], calls=[])
    c = client(home, m)
    s = new_session(c, upload(c, sample_path))
    ask(c, s["id"], "画图")
    ask(c, s["id"], "再算")
    msgs = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"]
    first_a = msgs[1]
    assert c.put(f"/messages/{first_a['id']}/feedback", json={"rating": "up"}, headers=H).status_code == 200
    assert c.delete(f"/messages/{msgs[0]['id']}", headers=H).status_code == 400      # 用户消息：拆对，拒绝
    assert c.delete("/messages/nope", headers=H).status_code == 404
    assert c.delete(f"/messages/{first_a['id']}", headers=H).status_code == 204
    rest = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"]
    assert [x["content"] for x in rest] == ["再算", "二"] and charts(home) == []
    db = sqlite3.connect(os.path.join(home, "datachat.db"))
    assert db.execute("select count(*) from events where message_id=?", (first_a["id"],)).fetchone()[0] == 0
    assert db.execute("select count(*) from feedback").fetchone()[0] == 0


def test_delete_message_keeps_history_alternating(home, sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), "一", tc("result = 2", 2), "二", tc("result = 3", 3), "三",
                                   "四"], calls=[])
    c = client(home, m)
    s = new_session(c, upload(c, sample_path))
    for q in ("问一", "问二", "问三"):
        ask(c, s["id"], q)
    msgs = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"]
    assert c.delete(f"/messages/{msgs[3]['id']}", headers=H).status_code == 204       # 删中间一轮
    rest = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"]
    assert [x["role"] for x in rest] == ["user", "assistant", "user", "assistant"]
    ask(c, s["id"], "问四")
    last = str(m.calls[-1])
    assert "问一" in last and "问三" in last and "问二" not in last and "二" not in last.replace("问二", "")


def test_delete_message_rejected_while_running(home, sample_path):
    m = ScriptedChatModel(replies=[tc("result = 1"), "一"], calls=[])
    c = client(home, m)
    s = new_session(c, upload(c, sample_path))
    ask(c, s["id"], "问一")
    a = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"][1]
    db = sqlite3.connect(os.path.join(home, "datachat.db"))
    db.execute("insert into messages (id, session_id, role, content, status, created_at) values "
               "('run1', ?, 'assistant', '', 'running', '2099-01-01T00:00:00.000+00:00')", (s["id"],))
    db.commit()
    assert c.delete(f"/messages/{a['id']}", headers=H).status_code == 409


def test_chart_files_of_rejects_paths_outside_chart_dir(tmp_path):
    cd = str(tmp_path / "charts")
    rj = json.dumps({"chart_path": os.path.join(cd, "chart_1_abc123.png"),
                     "charts": [{"png": "../../etc/passwd", "option": None},
                                {"png": "../../x/chart_9_zzz.png", "option": None},
                                {"png": "/etc/chart_2_evil.png", "option": None},
                                {"png": os.path.join(cd, "chart_1_abc123.png"), "option": None},
                                {"png": os.path.join(cd, "not_a_chart.png"), "option": None},
                                "C:/Users/me/x.png", {"png": None, "option": {"series": []}}]})
    ev = [json.dumps({"chart": os.path.join(cd, "chart_3_def456.png")}), "not json"]
    assert chart_files_of(rj, cd, ev) == [os.path.join(cd, "chart_1_abc123.png"), os.path.join(cd, "chart_3_def456.png")]
    assert chart_files_of(None, cd) == [] and chart_files_of("{bad", cd) == []


# ------------------------------------------------------------------ 空间回收
def test_auto_vacuum_enabled_and_freelist_shrinks(tmp_path):
    p = str(tmp_path / "new.db")
    S = make_sessionmaker(p)
    eng = S.kw["bind"]
    raw = sqlite3.connect(p)
    assert raw.execute("PRAGMA auto_vacuum").fetchone()[0] == 2           # 新库：INCREMENTAL
    raw.execute("create table junk(x)")
    raw.executemany("insert into junk values (?)", [("x" * 2000,)] * 500)
    raw.commit()
    raw.execute("delete from junk")
    raw.commit()
    free = raw.execute("PRAGMA freelist_count").fetchone()[0]
    raw.close()
    assert free > 100
    assert incremental_vacuum(eng) == free
    assert sqlite3.connect(p).execute("PRAGMA freelist_count").fetchone()[0] < free


def test_old_db_converted_only_when_fragmented(tmp_path):
    p = str(tmp_path / "old.db")
    raw = sqlite3.connect(p)                         # 旧库：auto_vacuum=NONE
    raw.execute("create table junk(x)")
    raw.executemany("insert into junk values (?)", [("x" * 2000,)] * 500)
    raw.commit()
    assert prepare_auto_vacuum(raw, p) == "skipped_ratio"
    raw.execute("delete from junk")
    raw.commit()
    assert prepare_auto_vacuum(raw, p) == "converted"
    assert raw.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    assert raw.execute("PRAGMA freelist_count").fetchone()[0] == 0
    assert prepare_auto_vacuum(raw, p) == "already"
    raw.close()
    S = make_sessionmaker(p)                         # 旧表、旧行原样
    assert S.kw["bind"].info["auto_vacuum"] == "already"


def test_incremental_vacuum_is_noop_on_none_mode(tmp_path):
    p = str(tmp_path / "none.db")
    raw = sqlite3.connect(p)
    raw.execute("create table t(x)")
    raw.commit()
    raw.close()
    from sqlalchemy import create_engine
    assert incremental_vacuum(create_engine(f"sqlite:///{p}")) == 0


# ------------------------------------------------------------------ 记忆开关接线
def test_settings_memory_mode_roundtrip(home, monkeypatch):
    c = client(home, ScriptedChatModel(replies=[], calls=[]))
    assert c.get("/settings", headers=H).json()["memory"] == {"mode": "off", "setting": "off", "env": None}
    r = c.put("/settings", json={"memory_mode": "state"}, headers=H)
    assert r.status_code == 200 and r.json()["memory"] == {"mode": "state", "setting": "state", "env": None}
    assert c.put("/settings", json={"memory_mode": "full"}, headers=H).status_code == 422
    monkeypatch.setenv("DATACHAT_MEMORY", "off")
    assert c.get("/settings", headers=H).json()["memory"] == {"mode": "off", "setting": "state", "env": "off"}


def test_state_mode_end_to_end_with_failed_turn(home, sample_path):
    """设置页打开 state：失败轮（取消）进历史（M5），历史以数据块进 system，result_json 记 state；
    工作状态从上一轮代码里抽出筛选（M1）。"""
    m = ScriptedChatModel(replies=[tc("result = df[df.region == '华北']['units'].sum()"), "华北 540 件"], calls=[])
    c = client(home, m)
    assert c.put("/settings", json={"memory_mode": "state"}, headers=H).status_code == 200
    s = new_session(c, upload(c, sample_path))
    e1 = ask(c, s["id"], "华北卖了多少")
    assert e1[-1][1]["data"]["result"]["memory_mode"] == "state"
    db = sqlite3.connect(os.path.join(home, "datachat.db"))              # 造一轮被取消的
    db.execute("insert into messages (id, session_id, role, content, status, created_at) values "
               "('u2', ?, 'user', '按产品拆开看看', 'ok', '2099-01-01T00:00:00.000+00:00'),"
               "('a2', ?, 'assistant', '已停止', 'cancelled', '2099-01-01T00:00:00.001+00:00')", (s["id"], s["id"]))
    db.commit()
    m.replies += ["刚才那个是按产品拆华北"]
    e3 = ask(c, s["id"], "刚才那个继续")
    r3 = e3[-1][1]["data"]["result"]
    assert r3["memory_mode"] == "state" and r3["history_tokens"] > 0 and r3["memory_trimmed"] == []
    sys_text = m.calls[-1][0].content
    assert "问：华北卖了多少\n答：华北 540 件" in sys_text
    assert "问：按产品拆开看看\n状态：已取消" in sys_text
    assert '筛选：region == "华北"' in sys_text
    assert len(m.calls[-1]) == 2                                        # system + 本轮，历史不再以消息回灌
