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


def wf(code="result = df.groupby('product')['units'].sum()", rewrite_reply=None, plan="计划"):
    log = {"planner": [], "codegen": [], "summarizer": [], "rewrite": []}

    def respond(messages):
        t = prompt_text(messages)
        if "你是问题改写器" in t:
            log["rewrite"].append(t)
            return rewrite_reply
        if "数据分析规划助手" in t:
            log["planner"].append(t)
            return plan
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


# ---------------------------------------------------------------- 反问的接线（2026-11-13 晚）
#
# 判据在 app/core/ambiguity.py，这里钉的是**接线**：service 得把「本轮之前有轮次」送进
# workflow，否则 may_clarify 收到的永远是 False，闸门看着有、实际不生效。
# 走 analyze() 而不是直接调图，因为 followup 是在 service 里从记忆上下文取的。

CLARIFY_SAY = "CLARIFY: 您想按销售额还是订单数看？"


def test_followup_blocks_clarify_even_when_off(sample_path):
    """off 档没有状态块，追问仍不许反问 —— 这是全量读数里 28/31 处误伤的根。

    off 下 `mc.state_block` 是空串，planner 的「有上文就放行」那句 prompt 进不去，
    只剩 service 传的 followup 这一条路。不传 = 用户在追问，助手却把上一轮问过的话再问一遍。
    """
    m, log = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "那 S02 呢？", chat_model=m, llm_config=FAST, history=HISTORY)
    assert r.ok and r.executed, "追问被反问拦住了，codegen 一步都没跑"
    assert len(log["codegen"]) == 1, "反问应该被丢掉，回到正常链路"


def test_first_turn_keeps_clarify_alive(sample_path):
    """没有上文、又是评价式问题 → 反问照旧生效，别被闸门一刀切。

    「这些订单的销售额怎么样」既没有上文、也没有前提词，是唯一该反问的形态。
    """
    m, log = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "这些订单的销售额怎么样？", chat_model=m, llm_config=FAST)
    assert r.answer == CLARIFY_SAY[len("CLARIFY: "):]
    assert log["codegen"] == [], "澄清短路后不该再写代码"
    assert not r.executed


def test_premise_imperative_is_not_clarified(sample_path):
    """首轮祈使句在设前提（"只看 2024 年 3 月的订单"），不是提问，不许反问。

    这四道是全量里第 1 轮就被拦下的题（mul_012/020/021/030）：用户下一句才说指标。
    拦下之后 codegen 必须拿到一条能执行的计划 —— 空计划会让它把「口径未定」翻成一句
    没有候选、没有数字的拒答（实测 mul_021 首轮就这样，见 `VETO_PLAN` 的注释）。
    """
    m, log = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "只看 2024 年 3 月的订单，重复录入的只算一次。",
                chat_model=m, llm_config=FAST)
    assert r.executed and len(log["codegen"]) == 1
    assert r.plan == planner.VETO_PLAN


# ---------------------------------------------------------------- clarify 的出口（2026-11-16）
#
# P6：off 档产品里 workflow 反问一次后，用户无论答什么都还会被反问 —— followup 代理不了
# 「上一轮是反问」。现在 prev_clarify 从上一条消息的 result_json.clarify 来，信号优先级最高。


def test_prev_clarify_lets_the_answer_through(sample_path):
    """上一轮在反问 → 这轮无论答什么都不再反问，codegen 照常跑、计划是 VETO_PLAN。

    「按销售额算」在旧判据下 7 种答法全部 may_clarify=True（死循环）。出口修好后：
    prev_clarify=True 直接放行，拿 VETO_PLAN 硬算 —— 算什么口径由计划兜底说明。
    """
    m, log = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "按销售额算", chat_model=m, llm_config=FAST, prev_clarify=True)
    assert r.ok and r.executed, "用户答了反问还被继续反问，clarify 就没有出口"
    assert len(log["codegen"]) == 1 and r.plan == planner.VETO_PLAN


def test_prev_clarify_survives_word_table_judgements(sample_path):
    """出口不受词表判定影响：用户答「按销售额算，但是高不高呢」虽然含评价式词，
    仍是上一轮反问的回答，不许再反问 —— 死循环比一次口径猜测更伤产品。
    """
    m, log = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "就按销售额，高不高呢？", chat_model=m, llm_config=FAST, prev_clarify=True)
    assert r.executed and len(log["codegen"]) == 1


def test_clarify_result_records_the_flag(sample_path):
    """反问轮的 res.clarify 必须为 True —— 产品靠 result_json.clarify 找「上一轮是反问」，
    这个字段不落盘，出口信号就断在源头。"""
    m, _ = wf(plan=CLARIFY_SAY)
    r = analyze(sample_path, "帮我看看这批数据哪个表现最好？", chat_model=m, llm_config=FAST)
    assert r.clarify is True and r.answer == CLARIFY_SAY[len("CLARIFY: "):]
    assert "clarify" in r.to_record(), "to_record 必须带 clarify（result_json 全字段来自它）"
