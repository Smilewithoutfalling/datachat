"""批 4a M8 workflow 记忆（docs/roadmap/memory-batch4.md §3.2）。

批 1 已经让 state 下 workflow 的 planner 拿到工作状态块；这里补上缺的测试，并钉住「改写后的问题送进 workflow」。
"""
import json

import pytest

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel, prompt_text
from app.memory.working_state import STATE_HEAD
from app.nodes import planner
from tests.test_memory_p8 import BASELINE, digest

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
HISTORY = [("华北卖了多少", "华北 540 件", "result = df[df.region == '华北']['units'].sum()")]
TODAY_REWRITE = json.dumps({"rewritten": "华北按产品拆开的销量", "needs_clarify": False, "reason": ""},
                           ensure_ascii=False)


def wf(code="result = df.groupby('product')['units'].sum()", rewrite_reply=None):
    log = {"planner": [], "codegen": [], "summarizer": [], "rewrite": []}

    def respond(messages):
        t = prompt_text(messages)
        if "你是问题改写器" in t:
            log["rewrite"].append(t)
            return rewrite_reply
        if "数据分析规划助手" in t:
            log["planner"].append(t)
            return "计划"
        if "写一段 pandas 代码" in t:
            log["codegen"].append(t)
            return code
        log["summarizer"].append(t)
        return "结论"
    return ScriptedChatModel(responder=respond, calls=[]), log


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)


@pytest.mark.parametrize("mode", ["state", "full"])
def test_workflow_gets_state_block(sample_path, mode):
    m, log = wf()
    r = analyze(sample_path, "按产品拆开看看", chat_model=m, llm_config=FAST, history=HISTORY, memory_mode=mode)
    assert r.ok and r.memory_mode == mode
    p = log["planner"][0]
    assert STATE_HEAD in p and 'region == "华北"' in p
    assert p.index("数据表的结构") < p.index(STATE_HEAD) < p.index("相关字段说明")       # 插在表结构之后
    assert all(STATE_HEAD not in t for t in log["codegen"] + log["summarizer"])     # 只给 planner
    assert "<<<历史对话开始" not in p                                                 # workflow 不吃历史块


def test_workflow_prompt_unchanged_when_off(sample_path):
    """与 P8 的 workflow 哈希同一份数据：off 下带不带历史、开不开改写，workflow 的 prompt 都与 3ce6b77 一致。"""
    for kw in ({}, {"history": HISTORY}, {"history": HISTORY, "rewrite": True}):
        from tests.test_core_analyze import wf_model
        m = wf_model(["result = df.groupby('region')['units'].sum()"])
        r = analyze(sample_path, "哪个地区卖得最好", chat_model=m, llm_config=FAST, **kw)
        assert digest(m.calls) == BASELINE["workflow"] and r.rewrite is None


def test_workflow_uses_rewritten_question(sample_path):
    m, log = wf(rewrite_reply=TODAY_REWRITE)
    r = analyze(sample_path, "那个按产品拆开呢", chat_model=m, llm_config=FAST, history=HISTORY,
                memory_mode="state", rewrite=True)
    assert r.ok and r.question == "那个按产品拆开呢" and r.rewrite["changed"] is True
    for node in ("planner", "codegen", "summarizer"):
        assert "用户问题：华北按产品拆开的销量" in log[node][0], node
        assert "那个按产品拆开呢" not in log[node][0], node


def test_workflow_rewrite_fallback_keeps_original(sample_path):
    m, log = wf(rewrite_reply="not json")
    r = analyze(sample_path, "那个按产品拆开呢", chat_model=m, llm_config=FAST, history=HISTORY,
                memory_mode="state", rewrite=True)
    assert r.ok and r.rewrite["changed"] is False
    assert "用户问题：那个按产品拆开呢" in log["planner"][0]


def test_workflow_planner_no_blank_line_when_empty():
    seen = []

    class L:
        def invoke(self, msg):
            seen.append(msg)
            return "计划"
    cfg = {"configurable": {"llm": L()}}
    base = {"schema": "列：a", "field_notes": "", "question": "问"}
    planner.plan(dict(base), cfg)
    planner.plan({**base, "memory_state": ""}, cfg)
    planner.plan({**base, "memory_state": "<<<状态>>>"}, cfg)
    assert seen[0] == seen[1] and "\n\n\n" not in seen[0]
    assert "\n\n<<<状态>>>\n\n相关字段说明" in seen[2] and "\n\n\n" not in seen[2]
