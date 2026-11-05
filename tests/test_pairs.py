"""批 4b M9 accepted pairs 最小版：只在 full、只给 ReAct、只用 👍 过的轮次，每轮现算。
docs/roadmap/memory-batch4.md §3.7。"""
import hashlib

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel
from app.memory import pairs as P
from app.server.app import create_app
from tests.test_memory_p8 import STATE_BASELINE, run_state_all
from tests.test_server import H, TOKEN, sse, upload

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
CODE = "result = df.groupby('region')['units'].sum()"


def tc(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": f"c{i}"}])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)


# ------------------------------------------------------------------ 纯函数
def test_dataset_fingerprint_definition():
    files = [("b.csv", "22"), ("a.csv", "11"), ("a.dict.csv", "33")]
    want = hashlib.sha256("a.csv:11\na.dict.csv:33\nb.csv:22\n".encode()).hexdigest()[:12]
    assert P.dataset_fingerprint(files) == want
    assert P.dataset_fingerprint(list(reversed(files))) == want

    class F:
        def __init__(self, fn, h):
            self.filename, self.sha256 = fn, h
    assert P.dataset_fingerprint([F(*f) for f in files]) == want
    assert P.dataset_fingerprint([("a.csv", "12")]) != P.dataset_fingerprint([("a.csv", "11")])


def test_pairs_top3_by_bm25():
    pairs = [{"question": q, "code": f"result = {i}"} for i, q in enumerate(
        ["各地区的销量合计", "各地区的平均单价", "各产品的销量合计", "华东每月的销量趋势", "员工人数"])]
    got = P.search("各地区销量合计是多少", pairs)
    assert len(got) == 3 and got[0]["question"] == "各地区的销量合计"
    assert "员工人数" not in [g["question"] for g in got]
    assert P.search("完全无关的东西", pairs) == [] and P.search("销量", []) == []


def test_render_has_no_answer_text():
    pairs = [{"question": "各地区销量", "code": CODE, "answer": "华北 540 最多", "result_text": "华北 540"}]
    block = P.render(pairs)
    assert block.startswith(P.BLOCK_HEAD) and block.endswith(P.BLOCK_TAIL) and P.TITLE in block
    assert CODE in block and "各地区销量" in block
    assert "540" not in block and "华北" not in block and "answer" not in block


def test_render_caps_code_and_block():
    long = "x = 1\n" * 400
    block = P.render([{"question": "q1", "code": long}])
    assert len(block) < len(long) and "…" in block
    many = [{"question": f"问题{i}", "code": "y = 2\n" * 240} for i in range(3)]
    from app.memory.budget import estimate_tokens
    b = P.render(many)
    assert estimate_tokens(b) <= P.BLOCK_TOKENS and "问题0" in b and "问题2" not in b
    assert P.render([]) == "" and P.render([{"question": "", "code": "a"}]) == ""


@pytest.mark.parametrize("res,status,rating,ok", [
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "华北最多"}, "ok", "up", True),
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "华北最多"}, "ok", "down", False),
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "华北最多"}, "ok", None, False),
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "华北最多"}, "error", "up", False),
    ({"executed": False, "code": CODE, "unverified_numbers": [], "answer": "x"}, "ok", "up", False),
    ({"executed": True, "code": " ", "unverified_numbers": [], "answer": "x"}, "ok", "up", False),
    ({"executed": True, "code": CODE, "unverified_numbers": ["42"], "answer": "x"}, "ok", "up", False),
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "无法回答：没有成本字段"}, "ok", "up", False),
    ({"executed": True, "code": CODE, "unverified_numbers": [], "answer": "x", "result_text": "无法回答：缺列"}, "ok", "up", False),
    (None, "ok", "up", False),
])
def test_pair_requires_thumb_up_and_exec(res, status, rating, ok):
    assert P.eligible(res, status, rating) is ok


def test_pair_requires_no_unverified_numbers():
    base = {"executed": True, "code": CODE, "answer": "华北最多"}
    assert P.eligible({**base, "unverified_numbers": []}, "ok", "up")
    assert not P.eligible({**base, "unverified_numbers": ["999"]}, "ok", "up")


def test_pairs_only_in_full(sample_path):
    pairs = [{"question": "哪个地区卖得最好", "code": CODE}]
    seen = {}
    for mode in ("off", "state", "full"):
        m = ScriptedChatModel(replies=[tc("result = 1"), "好"], calls=[])
        analyze(sample_path, "哪个地区卖得最好", agent="react", chat_model=m, llm_config=FAST, memory_mode=mode,
                accepted_pairs=pairs)
        seen[mode] = m.calls[0][0].content
    assert P.BLOCK_HEAD not in seen["off"] and P.BLOCK_HEAD not in seen["state"]
    assert P.BLOCK_HEAD in seen["full"]
    s = seen["full"]
    assert s.index("如果问题需要图表，请务必出图。") < s.index(P.BLOCK_HEAD) < s.index("chart(")   # CHART_GUIDE 之前
    # workflow 不放示例
    from tests.test_core_analyze import wf_model
    m = wf_model(["result = 1"])
    analyze(sample_path, "哪个地区卖得最好", chat_model=m, llm_config=FAST, memory_mode="full", accepted_pairs=pairs)
    assert not any(P.BLOCK_HEAD in str(x.content) for msgs in m.calls for x in msgs)


def test_full_without_pairs_equals_state_hash(sample_path, monkeypatch):
    """没有样本（None / []）时 full 与 state 的 prompt 逐字节相同（块不出现）。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "full")
    for p in (None, []):
        got, _ = run_state_all(sample_path, accepted_pairs=p)
        assert got == STATE_BASELINE


# ------------------------------------------------------------------ 走 API：每轮从库里现算
class Rig:
    def __init__(self, home, sample_path):
        self.calls = []

        def respond(messages):
            self.calls.append(messages)
            return tc(CODE) if len(self.calls) % 2 == 1 else "华北最多"
        self.m = ScriptedChatModel(responder=respond, calls=[])
        self.c = TestClient(create_app(home, TOKEN, chat_model_factory=lambda: self.m))
        self.c.put("/settings", json={"memory_mode": "full"}, headers=H)
        self.ds = upload(self.c, sample_path)["id"]

    def session(self, ds=None, agent="react"):
        return self.c.post("/sessions", json={"dataset_id": ds or self.ds, "agent": agent}, headers=H).json()["id"]

    def ask(self, sid, q):
        self.calls.clear()
        ev = sse(self.c.post(f"/sessions/{sid}/messages", json={"content": q}, headers=H).text)
        return ev[-1][1]["data"]["result"], ev[-1][1]["trace_id"]

    def system(self):
        return self.calls[0][0].content

    def thumb(self, mid, rating="up"):
        assert self.c.put(f"/messages/{mid}/feedback", json={"rating": rating}, headers=H).status_code == 200


@pytest.fixture
def rig(tmp_path, sample_path):
    return Rig(str(tmp_path / "home"), sample_path)


def test_pairs_used_across_sessions_via_api(rig):
    s1 = rig.session()
    r, mid = rig.ask(s1, "哪个地区卖得最好")
    assert r["ok"] and r["executed"] and r["unverified_numbers"] == []
    rig.thumb(mid)
    s2 = rig.session()
    rig.ask(s2, "哪个地区卖得最好呢")
    assert P.BLOCK_HEAD in rig.system() and CODE in rig.system() and "华北最多" not in rig.system()


def test_pairs_exclude_current_session(rig):
    s1 = rig.session()
    _, mid = rig.ask(s1, "哪个地区卖得最好")
    rig.thumb(mid)
    rig.ask(s1, "哪个地区卖得最好呢")          # 同一会话：不拿自己会话的样本
    assert P.BLOCK_HEAD not in rig.system()


def test_pair_disappears_when_feedback_removed(rig):
    s1 = rig.session()
    _, mid = rig.ask(s1, "哪个地区卖得最好")
    rig.thumb(mid)
    s2 = rig.session()
    rig.ask(s2, "哪个地区卖得最好")
    assert P.BLOCK_HEAD in rig.system()
    rig.c.put(f"/messages/{mid}/feedback", json={"rating": None}, headers=H)
    s3 = rig.session()
    rig.ask(s3, "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()
    rig.thumb(mid, "down")
    rig.ask(rig.session(), "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()
    # 删掉那一轮：样本跟着消失
    rig.thumb(mid)
    assert rig.c.delete(f"/messages/{mid}", headers=H).status_code == 204
    rig.ask(rig.session(), "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()


def test_pairs_cross_dataset_not_returned(rig, tmp_path, sample_path):
    s1 = rig.session()
    _, mid = rig.ask(s1, "哪个地区卖得最好")
    rig.thumb(mid)
    other_csv = tmp_path / "other.csv"
    other_csv.write_text(open(sample_path, encoding="utf-8").read() + "2024-12-31,华南,C,1,1.0\n", encoding="utf-8")
    other = upload(rig.c, str(other_csv))["id"]
    rig.ask(rig.session(other), "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()
    # 同一份文件重新上传：指纹相同，算同一数据集
    same = upload(rig.c, sample_path, name="重新上传")["id"]
    rig.ask(rig.session(same), "哪个地区卖得最好")
    assert P.BLOCK_HEAD in rig.system()


def test_pairs_only_full_and_react_via_api(rig):
    s1 = rig.session()
    _, mid = rig.ask(s1, "哪个地区卖得最好")
    rig.thumb(mid)
    rig.c.put("/settings", json={"memory_mode": "state"}, headers=H)
    rig.ask(rig.session(), "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()
    rig.c.put("/settings", json={"memory_mode": "off"}, headers=H)
    rig.ask(rig.session(), "哪个地区卖得最好")
    assert P.BLOCK_HEAD not in rig.system()
