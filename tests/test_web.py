"""阶段 5 F0：前端静态托管的 auth 边界、CSP、--open；feedback 表（含旧库兼容）。全部用假模型。"""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.server.app import CSP, create_app
from tests.test_core_analyze import wf_model
from tests.test_server import H, TOKEN, upload

INDEX = '<!doctype html><html><head><script type="module" src="/assets/index-abc.js"></script></head><body></body></html>'


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX, encoding="utf-8")
    (d / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    return str(d)


def client(home, dist=None, factory=None):
    return TestClient(create_app(home, TOKEN, chat_model_factory=factory, web_dist=dist))


# ---------------------------------------------------------------- 静态托管与 auth 边界
def test_static_needs_no_token_but_api_does(home, dist):
    c = client(home, dist)
    r = c.get("/")
    assert r.status_code == 200 and "index-abc.js" in r.text
    assert c.get("/assets/index-abc.js").status_code == 200
    assert c.get("/assets/missing.js").status_code == 404
    # 边界只开了 / 和 /assets：API 和图表照旧要 token
    for path in ("/datasets", "/sessions", "/settings", "/settings/api-key", "/charts/chart_1_abcdef.png"):
        assert c.get(path).status_code == 401, path
    assert c.put("/messages/x/feedback", json={"rating": "up"}).status_code == 401


def test_static_path_traversal_blocked(home, dist, tmp_path):
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    c = client(home, dist)
    for p in ("/assets/../index.html", "/assets/..%2F..%2Fsecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"):
        r = c.get(p)
        assert r.status_code == 404 or "secret" not in r.text, p


def test_index_has_csp_and_hardening_headers(home, dist):
    r = client(home, dist).get("/")
    csp = r.headers["content-security-policy"]
    assert csp == CSP
    for d in ("script-src 'self'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
              "object-src 'none'", "img-src 'self' data: blob:"):
        assert d in csp
    assert "unsafe-eval" not in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_static_still_behind_trusted_host(home, dist):
    assert client(home, dist).get("/", headers={"Host": "evil.example"}).status_code == 400


def test_missing_dist_gives_build_hint(home, tmp_path):
    r = client(home, str(tmp_path / "nope")).get("/")
    assert r.status_code == 503 and "npm run build" in r.text


def test_open_flag_puts_token_in_fragment(monkeypatch, tmp_path):
    import app.server.__main__ as m
    opened = []

    class FakeTimer:
        def __init__(self, _delay, fn, args):
            self.fn, self.args = fn, args

        def start(self):
            opened.extend(self.args)

    class FakeServer:
        def __init__(self, config):
            pass

        def run(self, sockets):
            for s in sockets:
                s.close()

    import threading
    import uvicorn
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    m.main(["--port", "0", "--home", str(tmp_path / "h"), "--token", "abc", "--open"])
    assert len(opened) == 1
    url = opened[0]
    assert url.startswith("http://127.0.0.1:") and url.endswith("/#token=abc")
    assert "?token" not in url                     # 只走 fragment，不进查询串（不发给服务器、不进日志）


# ---------------------------------------------------------------- feedback
def _one_turn(c, sample_path):
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"], "agent": "workflow"}, headers=H).json()
    r = c.post(f"/sessions/{s['id']}/messages", json={"content": "总销量"}, headers=H)
    return s["id"], r.headers["x-message-id"], r.headers["x-user-message-id"]


def test_feedback_roundtrip(home, sample_path):
    c = client(home, factory=lambda: wf_model(["result = int(df['units'].sum())"], answer="总销量 1685"))
    sid, mid, qid = _one_turn(c, sample_path)
    msgs = c.get(f"/sessions/{sid}", headers=H).json()["messages"]
    assert msgs[1]["feedback"] is None and "feedback" not in msgs[0]

    r = c.put(f"/messages/{mid}/feedback", json={"rating": "down", "note": "单价\x00列\x1b[31m 读错\u202e了\n第二行"},
              headers=H)
    assert r.status_code == 200
    assert r.json() == {"message_id": mid, "rating": "down", "note": "单价列[31m 读错了\n第二行"}
    # 撤销评价：rating=None 保留这一行（note 还在）
    r = c.put(f"/messages/{mid}/feedback", json={"rating": None, "note": "留着"}, headers=H)
    assert r.json()["rating"] is None
    fb = c.get(f"/sessions/{sid}", headers=H).json()["messages"][1]["feedback"]
    assert fb == {"rating": None, "note": "留着"}

    assert c.put(f"/messages/{qid}/feedback", json={"rating": "up"}, headers=H).status_code == 400
    assert c.put("/messages/nope/feedback", json={"rating": "up"}, headers=H).status_code == 404
    assert c.put(f"/messages/{mid}/feedback", json={"rating": "meh"}, headers=H).status_code == 422
    assert c.put(f"/messages/{mid}/feedback", json={"note": "x" * 1001}, headers=H).status_code == 422

    # 删会话 → feedback 跟着删
    c.delete(f"/sessions/{sid}", headers=H)
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        assert con.execute("select count(*) from feedback").fetchone()[0] == 0


def test_feedback_rejects_running_message(home, sample_path):
    c = client(home, factory=lambda: wf_model(["result = 1"], answer="1"))
    _, mid, _ = _one_turn(c, sample_path)
    with sqlite3.connect(os.path.join(home, "datachat.db")) as con:
        con.execute("update messages set status='running' where id=?", (mid,))
    assert c.put(f"/messages/{mid}/feedback", json={"rating": "up"}, headers=H).status_code == 409


def test_v1_database_gains_feedback_table_without_touching_old_tables(home, sample_path):
    """旧库（F0 之前没有 feedback 表）启动后：新表出现，旧表结构与行数不变，旧消息可直接评价。"""
    c = client(home, factory=lambda: wf_model(["result = int(df['units'].sum())"], answer="总销量 1685"))
    sid, mid, _ = _one_turn(c, sample_path)
    db = os.path.join(home, "datachat.db")
    old_tables = ("datasets", "dataset_files", "sessions", "messages", "events", "settings")
    with sqlite3.connect(db) as con:
        con.execute("drop table feedback")              # 还原成 v1 库
        before = {t: (con.execute(f"select count(*) from {t}").fetchone()[0],
                      con.execute(f"pragma table_info({t})").fetchall()) for t in old_tables}
        assert "feedback" not in {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    del c

    c2 = client(home)
    with sqlite3.connect(db) as con:
        assert "feedback" in {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        after = {t: (con.execute(f"select count(*) from {t}").fetchone()[0],
                     con.execute(f"pragma table_info({t})").fetchall()) for t in old_tables}
    assert after == before
    assert before["messages"][0] == 2 and before["events"][0] > 0
    assert c2.put(f"/messages/{mid}/feedback", json={"rating": "up"}, headers=H).status_code == 200
    assert c2.get(f"/sessions/{sid}", headers=H).json()["messages"][1]["feedback"]["rating"] == "up"
