"""EV-D4：👎 → 草稿用例。核心被测行为是**默认不泄露数据值**。

这条脚本是唯一会把用户数据写出仓库的路径，所以测试的重点不是"能不能生成 YAML"，
而是"默认路径有没有可能把答案里的数值带出去"。
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.server.db import Base, ChatSession, Feedback, Message

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "draft_case.py")

ANSWER = "华北 2024 年 1 月销量合计 190 件，其中 A 产品 110 件，占 57.9%。"


def _script():
    spec = importlib.util.spec_from_file_location("draft_case_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def db(tmp_path):
    """真表结构（ORM create_all），不是手写 SQL——手写的 schema 一漂就测不到真问题。

    数据集用真的 CSV 路径：真实记录里的 `dataset` 就是绝对路径，这一层必须按真实形态测。
    """
    path = str(tmp_path / "datachat.db")
    csv = tmp_path / "用户订单.csv"
    csv.write_text("date,region,units\n2024-01-01,华北,10\n2024-01-02,华东,20\n", encoding="utf-8")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    S = sessionmaker(engine, expire_on_commit=False)
    with S() as s:
        s.add(ChatSession(id="sess1", agent="react", dataset_id="sales", title="t",
                          created_at="2026-11-07T10:00:00", updated_at="2026-11-07T10:00:00"))
        s.add(Message(id="u1", session_id="sess1", role="user", status="ok",
                      content="2024 年 1 月华北的销量是多少？", created_at="2026-11-07T10:00:01"))
        s.add(Message(id="m1", session_id="sess1", role="assistant", status="ok", content=ANSWER,
                      result_json=json.dumps({"dataset": str(csv),
                                              "question": "2024 年 1 月华北的销量是多少？"},
                                             ensure_ascii=False),
                      created_at="2026-11-07T10:00:02"))
        s.add(Feedback(message_id="m1", rating="down", note="答非所问", updated_at="2026-11-07T10:01:00"))
        s.commit()
    return path


def test_default_draft_never_leaks_answer_values(db, capsys):
    rc = _script().main(["--db", db, "--message-id", "m1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 月华北的销量" in out            # 问题必须留：它就是用例本身
    for leak in ("190", "110", "57.9"):      # 答案里的数值一个都不许出现
        assert leak not in out
    assert 'ground_truth: ""' in out         # gold 必须人工补
    assert "用户备注：答非所问" in out
    assert "原始答案已省略" in out


def test_default_draft_carries_schema_but_no_values(db, tmp_path, capsys):
    rc = _script().main(["--db", db, "--message-id", "m1"])
    out = capsys.readouterr().out
    assert rc == 0 and "schema:" in out and "columns:" in out
    assert "region" in out                   # 列名是结构，可以出
    # 真实记录的 dataset 是绝对路径：只能留文件名，不能把用户名/安装路径带进仓库
    assert "用户订单.csv" in out
    assert str(tmp_path) not in out and "AppData" not in out


def test_raw_prints_warning_and_answer(db, capsys):
    rc = _script().main(["--db", db, "--message-id", "m1", "--raw"])
    cap = capsys.readouterr()
    assert rc == 0
    assert "190" in cap.out and "原始答案" in cap.out
    assert "--raw" in cap.err and "可能带出" in cap.err


def test_missing_message_is_an_error(db, capsys):
    assert _script().main(["--db", db, "--message-id", "nope"]) == 1
    assert "没有这条消息" in capsys.readouterr().out


def test_user_message_id_rejected(db, capsys):
    """传错了那条（用户问题）时要说清楚，不能生成一条 question 为空的草稿。"""
    assert _script().main(["--db", db, "--message-id", "u1"]) == 1
    assert "是 user 消息" in capsys.readouterr().out


def test_requires_down_vote_unless_overridden(db, capsys):
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("update feedback set rating = 'up' where message_id = 'm1'")
    conn.commit()
    conn.close()
    assert _script().main(["--db", db, "--message-id", "m1"]) == 1
    assert "不是 👎" in capsys.readouterr().out
    assert _script().main(["--db", db, "--message-id", "m1", "--any-rating"]) == 0


def test_out_file_and_id_increment(db, tmp_path, capsys):
    mod = _script()
    (tmp_path / "draft_001.yaml").write_text("", encoding="utf-8")
    (tmp_path / "draft_002.yaml").write_text("", encoding="utf-8")
    target = tmp_path / "draft_003.yaml"
    assert mod.main(["--db", db, "--message-id", "m1", "--out", str(target)]) == 0
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "draft_003" in text              # 接着已有的 002 往后编
    assert "190" not in text


def test_runs_as_script_with_schema(db):
    """以脚本方式跑（不是 import）也必须能 import app —— ROOT 少一层会让 schema 静默消失。"""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, SCRIPT, "--db", db, "--message-id", "m1", "--any-rating"],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert "schema:" in out.stdout and "region" in out.stdout


def test_read_only_connection(db):
    """脚本只用 mode=ro 打开：写不进去，跑坏了也动不了用户数据。"""
    import sqlite3
    conn = _script()._connect_ro(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("delete from messages")
    conn.close()
