"""阶段 5 F2：停止（POST /messages/{id}/cancel）—— CAS 写库、finally CAS、done_seen、analyze_stream(cancel=)。不调模型。"""
import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.core import analyze_stream
from app.core.events import CANCELLED_MESSAGE, ERROR_KINDS
from app.server.app import create_app
from app.server.db import Message, make_sessionmaker
from app.core.testing import prompt_text
from tests.test_core_analyze import wf_model
from tests.test_server import H, TOKEN, sse, upload


def hooked(on, hook, **kw):
    """wf_model，但在提示词里出现 on 的那次模型调用时先执行 hook()。"""
    m = wf_model(["result = 1"], **kw)
    inner = m.responder

    def respond(messages):
        if on in prompt_text(messages):
            hook()
        return inner(messages)
    m.responder = respond
    return m


# ---------------------------------------------------------------- analyze_stream(cancel=)
def test_stream_cancel_stops_before_next_event(sample_path):
    ev = threading.Event()
    model = hooked("写一段 pandas 代码", ev.set)
    evs = list(analyze_stream(sample_path, "总销量", chat_model=model, cancel=ev))
    assert [e.type for e in evs] == ["plan", "error", "done"]       # codegen 那次调用跑完，code 事件之前停
    assert evs[1].data == {"message": CANCELLED_MESSAGE, "kind": "cancelled", "fatal": True}   # 常量文案，不带异常
    assert evs[-1].result.error == CANCELLED_MESSAGE
    r = evs[-1].result
    assert r.error_kind == "cancelled" and not r.ok and r.steps[-1].name == "cancel"


def test_answer_is_a_checkpoint(sample_path):
    """取消落在 summarizer 那次模型调用期间：调用跑完，但 answer 事件之前的检查就停下，answer 不发出。
    late-cancel 窗口因此只剩 answer 发出之后到 done 之前（只有收尾记账，没有模型调用）。"""
    ev = threading.Event()
    m = wf_model(["result = 1"])
    inner = m.responder

    def respond(messages):
        t = prompt_text(messages)
        if not any(k in t for k in ("数据分析规划助手", "请修正它", "写一段 pandas 代码")):
            ev.set()                                                 # summarizer
        return inner(messages)
    m.responder = respond
    evs = list(analyze_stream(sample_path, "总销量", chat_model=m, cancel=ev))
    types = [e.type for e in evs]
    assert "answer" not in types and types[-2:] == ["error", "done"] and "exec" in types


def test_stream_cancel_after_last_event_still_reports_cancelled(sample_path):
    ev = threading.Event()
    gen = analyze_stream(sample_path, "总销量", chat_model=wf_model(["result = 1"]), cancel=ev)
    types = []
    for e in gen:
        types.append(e.type)
        if e.type == "answer":
            ev.set()                                                 # 内部已跑完、done 之前
    assert types[-2:] == ["error", "done"] and "answer" in types


def test_stream_without_cancel_unchanged(sample_path):
    evs = list(analyze_stream(sample_path, "总销量", chat_model=wf_model(["result = 1"]), cancel=threading.Event()))
    assert evs[-1].type == "done" and evs[-1].result.ok


# ---------------------------------------------------------------- POST /messages/{id}/cancel
@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


def running_id(c, sid):
    [m] = [m for m in c.get(f"/sessions/{sid}", headers=H).json()["messages"] if m["status"] == "running"]
    return m["id"]


def setup(home, sample_path, on, hook_factory):
    box = {}
    app = create_app(home, TOKEN, chat_model_factory=lambda: hooked(on, lambda: hook_factory(box)))
    c = TestClient(app)
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    box.update(c=TestClient(app), sid=s["id"])
    return c, s["id"], box


def test_cancel_mid_run_cas_and_immediate_reask(home, sample_path):
    def hook(box):
        cc = box["c"]
        mid = running_id(cc, box["sid"])
        box["mid"] = mid
        r = cc.post(f"/messages/{mid}/cancel", headers=H)
        box["first"] = r.status_code, r.json()
        box["reask_ok"] = cc.post(f"/messages/{mid}/cancel", headers=H).status_code   # 已 cancelled → 409
    c, sid, box = setup(home, sample_path, "写一段 pandas 代码", hook)
    r = c.post(f"/sessions/{sid}/messages", json={"content": "总销量"}, headers=H)
    evs = sse(r.text)
    assert [t for t, _ in evs] == ["plan", "error", "done"]
    assert evs[1][1]["data"]["kind"] == "cancelled"
    assert box["first"] == (200, {"id": box["mid"], "status": "cancelled"}) and box["reask_ok"] == 409
    msgs = c.get(f"/sessions/{sid}", headers=H).json()["messages"]
    a = msgs[-1]
    assert a["status"] == "cancelled" and a["content"] == CANCELLED_MESSAGE and a["result"] is None
    assert evs[1][1]["data"]["message"] == CANCELLED_MESSAGE
    assert [e["type"] for e in a["events"]] == ["plan", "error"]   # done 不落库，重放时前端按 status 合成
    # 立刻重问不撞 409
    r2 = c.post(f"/sessions/{sid}/messages", json={"content": "再问"}, headers=H)
    assert r2.status_code == 200


def test_finally_cas_does_not_overwrite_cancel_that_landed_late(home, sample_path):
    """取消落库在 analyze_stream 最后一次检查之后（这里直接改库、不置位信号）：分析照常 ok 结束，
    但 finally 的 CAS 命中 0 行，库里仍是 cancelled、result_json 为空。"""
    def hook(box):
        S = make_sessionmaker(os.path.join(home, "datachat.db"))
        with S() as db:
            m = db.get(Message, running_id(box["c"], box["sid"]))
            m.status, m.content = "cancelled", "已取消"
            db.commit()
    c, sid, box = setup(home, sample_path, "写一段 pandas 代码", hook)
    evs = sse(c.post(f"/sessions/{sid}/messages", json={"content": "总销量"}, headers=H).text)
    assert evs[-1][0] == "done" and evs[-1][1]["data"]["result"]["error"] is None
    a = c.get(f"/sessions/{sid}", headers=H).json()["messages"][-1]
    assert a["status"] == "cancelled" and a["result"] is None


def test_finished_message_cancel_409_and_guards(home, sample_path):
    c, sid, _ = setup(home, sample_path, "不会出现的提示词", lambda box: None)
    c.post(f"/sessions/{sid}/messages", json={"content": "总销量"}, headers=H)
    q, a = c.get(f"/sessions/{sid}", headers=H).json()["messages"]
    assert a["status"] == "ok"
    assert c.post(f"/messages/{a['id']}/cancel", headers=H).status_code == 409      # 已完成的轮次不动
    assert c.get(f"/sessions/{sid}", headers=H).json()["messages"][1]["status"] == "ok"
    assert c.post(f"/messages/{q['id']}/cancel", headers=H).status_code == 400
    assert c.post("/messages/nope/cancel", headers=H).status_code == 404
    assert c.post(f"/messages/{a['id']}/cancel").status_code == 401


def test_stream_exception_without_done_is_error_not_cancelled(home, sample_path, monkeypatch):
    import app.core as core

    def broken(*a, **kw):
        yield from ()
        raise RuntimeError("boom")
    monkeypatch.setattr(core, "analyze_stream", broken)
    c = TestClient(create_app(home, TOKEN, chat_model_factory=lambda: wf_model(["result = 1"])),
                   raise_server_exceptions=False)
    ds = upload(c, sample_path)
    sid = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()["id"]
    c.post(f"/sessions/{sid}/messages", json={"content": "q"}, headers=H)   # 流中途抛异常（已发出响应头）
    a = c.get(f"/sessions/{sid}", headers=H).json()["messages"][-1]
    from app.core.events import STREAM_ABORTED_MESSAGE
    assert a["status"] == "error" and a["content"] == STREAM_ABORTED_MESSAGE    # 不带异常 repr / 堆栈
    assert "boom" not in a["content"] and "RuntimeError" not in a["content"]


# ---------------------------------------------------------------- gen_ui_types
def test_gen_ui_types_check_passes_and_detects_drift(tmp_path, monkeypatch):
    import scripts.gen_ui_types as g
    assert g.main(["--check"]) == 0
    monkeypatch.setattr(g, "OUT_DIR", str(tmp_path))
    assert g.main(["--check"]) == 1                     # 文件缺失
    assert g.main([]) == 0 and g.main(["--check"]) == 0
    p = tmp_path / "events.json"
    good = p.read_text(encoding="utf-8")
    for old, new in (('"done"', '"finish"'), ('"interrupted"', '"aborted"'), ('"已取消"', '"取消"'),
                     ('"running"', '"pending"'), ('"分析已中断（连接已断开）"', '"连接断开"')):
        p.write_text(good.replace(old, new, 1), encoding="utf-8")
        assert g.main(["--check"]) == 1, old            # 事件类型 / error_kind / 文案 / 消息状态任一漂移都报


def _error_kind_writes(tree):
    """一棵 AST 里所有"写 error_kind"的字面量：x.error_kind = …、x["error_kind"] = …（含元组解包）、
    {"error_kind": …}、f(error_kind=…)、em.error(msg, kind, …) 的 kind。条件表达式只看两个分支；比较（读）不算。"""
    import ast

    def consts(node):
        if isinstance(node, ast.IfExp):
            return consts(node.body) | consts(node.orelse)
        return {node.value} if isinstance(node, ast.Constant) and isinstance(node.value, str) else set()

    def is_kind_target(e):
        return ((isinstance(e, ast.Attribute) and e.attr == "error_kind")
                or (isinstance(e, ast.Subscript) and isinstance(e.slice, ast.Constant) and e.slice.value == "error_kind"))
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                elts = t.elts if isinstance(t, ast.Tuple) else [t]
                for i, e in enumerate(elts):
                    if is_kind_target(e):
                        v = n.value.elts[i] if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) else n.value
                        used |= consts(v)
        if isinstance(n, ast.Dict):                                   # {"error_kind": "x"}
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "error_kind":
                    used |= consts(v)
        if isinstance(n, ast.Call):                                   # AnalysisResult(error_kind="x")、.replace(error_kind=…)
            used |= {c for kw in n.keywords if kw.arg == "error_kind" for c in consts(kw.value)}
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "error"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "em" and len(n.args) >= 2):
            used |= consts(n.args[1])
    return used


def test_error_kinds_written_by_service_are_registered():
    """service.py 写进 error_kind 的字面量必须在 ERROR_KINDS 里；除 interrupted（只落在 messages.status）外都实际出现过。"""
    import ast
    import inspect

    import app.core.service as svc
    used = _error_kind_writes(ast.parse(inspect.getsource(svc)))
    assert used == set(ERROR_KINDS) - {"interrupted"}, used ^ (set(ERROR_KINDS) - {"interrupted"})


# 评测记录（app/eval/runner.py 的结果 dict）自己的 kind：标答代码执行失败，不是 AnalysisResult，也不会到前端
EVAL_ONLY_KINDS = {("app/eval/runner.py", "ground_truth")}


def test_only_service_writes_error_kind():
    """约定写成测试：整个 app/ 包里只有 core/service.py 允许写 error_kind（及 em.error 的 kind）。
    别处冒出新 kind 时 ERROR_KINDS 不变、gen --check 也查不出，所以在这里拦。"""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for f in sorted((root / "app").rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if rel == "app/core/service.py":
            continue
        for k in _error_kind_writes(ast.parse(f.read_text(encoding="utf-8"))):
            if (rel, k) not in EVAL_ONLY_KINDS:
                bad.append((rel, k))
    assert bad == []


def test_restart_marks_interrupted_not_cancelled(home, sample_path):
    """后端重启清理遗留 running：status=interrupted + 常量文案。用户没点过停止，不能显示"已取消"。"""
    from app.core.events import INTERRUPTED_MESSAGE
    c, sid, _ = setup(home, sample_path, "不会出现的提示词", lambda box: None)
    S = make_sessionmaker(os.path.join(home, "datachat.db"))
    with S() as db:
        db.add(Message(session_id=sid, role="assistant", status="running"))
        db.commit()
    c2 = TestClient(create_app(home, TOKEN, chat_model_factory=lambda: wf_model(["result = 1"])))
    [a] = c2.get(f"/sessions/{sid}", headers=H).json()["messages"]
    assert a["status"] == "interrupted" and a["content"] == INTERRUPTED_MESSAGE != CANCELLED_MESSAGE
    assert c2.post(f"/messages/{a['id']}/cancel", headers=H).status_code == 409       # 已结束
    assert c2.post(f"/sessions/{sid}/messages", json={"content": "重试"}, headers=H).status_code == 200


def _status_writes(tree, *, local_names):
    """写 status 的字面量：x.status = …、f(status=…)（Message(...)、update().values(...)）、{"status": …}；
    local_names=True 时另算局部变量 status = …（app/server 里 stream() 先算 status 再 CAS 写库）。含元组解包与条件表达式两分支。"""
    import ast

    def consts(node):
        if isinstance(node, ast.IfExp):
            return consts(node.body) | consts(node.orelse)
        return {node.value} if isinstance(node, ast.Constant) and isinstance(node.value, str) else set()

    def is_target(e):
        return ((isinstance(e, ast.Attribute) and e.attr == "status")
                or (local_names and isinstance(e, ast.Name) and e.id == "status"))
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                elts = t.elts if isinstance(t, ast.Tuple) else [t]
                for i, e in enumerate(elts):
                    if is_target(e):
                        v = n.value.elts[i] if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) else n.value
                        used |= consts(v)
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "status":
                    used |= consts(v)
        if isinstance(n, ast.Call):
            used |= {c for kw in n.keywords if kw.arg == "status" for c in consts(kw.value)}
    return used


def test_status_writes_are_registered():
    """与 error_kind 对称：app/ 里写进 status 的字面量都必须在 MESSAGE_STATUSES 里（常量本身 gen --check 管，
    "有人写了别的字符串"这里管）。局部变量 status 只在 app/server 里算（app/eval/report.py 有个同名的展示用局部变量）。"""
    import ast
    import pathlib

    from app.server.db import MESSAGE_STATUSES
    root = pathlib.Path(__file__).resolve().parents[1]
    bad, seen = [], set()
    for f in sorted((root / "app").rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        used = _status_writes(ast.parse(f.read_text(encoding="utf-8")), local_names=rel.startswith("app/server/"))
        seen |= used
        bad += [(rel, s) for s in used if s not in MESSAGE_STATUSES]
    assert bad == []
    assert seen == set(MESSAGE_STATUSES), seen ^ set(MESSAGE_STATUSES)      # 每个状态都有人写；扫描器没失明


def test_status_scanner_sees_every_write_form():
    import ast
    src = ('m.status = "a"\nm.status, m.content = "b", 1\nMessage(status="c")\nupdate(M).values(status="d")\n'
           'x = {"status": "e"}\nstatus = "f" if ok else "g"\nif m.status == "no": pass\n')
    assert _status_writes(ast.parse(src), local_names=True) == set("abcdefg")
    assert _status_writes(ast.parse(src), local_names=False) == set("abcde")


def test_client_disconnect_is_interrupted_not_cancelled(home, sample_path, monkeypatch):
    """SSE 客户端断开（关标签页、网络抖动）不是用户点停止：status=interrupted + DISCONNECTED_MESSAGE。
    TestClient 不会真正断开，这里截下 stream() 生成器，读一个事件后 close()——等同 Starlette 在断开时关闭它。"""
    import app.server.app as srv
    from fastapi.responses import Response

    from app.core.events import DISCONNECTED_MESSAGE
    captured = []
    monkeypatch.setattr(srv, "StreamingResponse", lambda content, **kw: (captured.append(content), Response("x"))[1])
    c, sid, _ = setup(home, sample_path, "不会出现的提示词", lambda box: None)
    c.post(f"/sessions/{sid}/messages", json={"content": "总销量"}, headers=H)
    gen = captured[0]
    assert "event: plan" in next(gen)
    gen.close()
    a = c.get(f"/sessions/{sid}", headers=H).json()["messages"][-1]
    assert a["status"] == "interrupted" and a["content"] == DISCONNECTED_MESSAGE
    assert a["content"] != CANCELLED_MESSAGE and [e["type"] for e in a["events"]] == ["plan"]


def test_cancel_then_disconnect_stays_cancelled(home, sample_path, monkeypatch):
    """前端点停止：先 POST /cancel，再断开 fetch。cancel 的 CAS 先落库，断开分支的 CAS 命中 0 行，仍是 cancelled。"""
    import app.server.app as srv
    from fastapi.responses import Response
    captured = []
    monkeypatch.setattr(srv, "StreamingResponse", lambda content, **kw: (captured.append(content), Response("x"))[1])
    c, sid, _ = setup(home, sample_path, "不会出现的提示词", lambda box: None)
    c.post(f"/sessions/{sid}/messages", json={"content": "总销量"}, headers=H)
    gen = captured[0]
    next(gen)
    mid = running_id(c, sid)
    assert c.post(f"/messages/{mid}/cancel", headers=H).status_code == 200
    gen.close()
    a = c.get(f"/sessions/{sid}", headers=H).json()["messages"][-1]
    assert a["status"] == "cancelled" and a["content"] == CANCELLED_MESSAGE
