"""阶段 6.6 M12：记忆按 token 计预算（估算比例与 llm.py 一致），超了先砍历史，并给 warning。"""
from app.core import LLMConfig, analyze
from app.core.llm import EST_CHARS_PER_TOKEN, _est
from app.core.testing import ScriptedChatModel
from app.memory import budget as B
from app.memory.context import state_context
from app.memory.snapshots import TurnSnapshot

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)


def test_estimate_tokens_chinese_and_ascii():
    assert EST_CHARS_PER_TOKEN == 2
    for t in ("", "a", "中文四个", "x" * 4001, "混合 mixed 文本"):
        assert B.estimate_tokens(t) == _est(len(t))


def test_projection_gate_tightens_history_cap():
    # 默认预算：fixed=8000，阈值 0.6×122000=73200；6 次×6k=36k 不收紧，15 次×6k=90k 收紧
    assert B.history_cap(130_000, 6, 6000) == B.HISTORY_TOKENS
    assert B.history_cap(130_000, None, 6000) == B.HISTORY_TOKENS
    assert B.history_cap(130_000, 15, 6000) == B.HISTORY_TOKENS_TIGHT
    assert B.history_cap(130_000, 15, 1000) == B.HISTORY_TOKENS        # 历史小：调用多也不收紧
    assert B.history_cap(0, 50, 6000) == B.HISTORY_TOKENS               # 预算关闭


def test_fit_drops_history_first_and_never_exceeds_cap():
    snaps = [TurnSnapshot(q="需" * 4000, a_brief="结" * 300)] + [TurnSnapshot(q=f"问{i}" + "粘" * 3990)
                                                               for i in range(3)] + [TurnSnapshot(q="问8")]
    mc = state_context(snaps, 130_000)
    assert mc.history_tokens <= B.HISTORY_TOKENS
    assert "history" in mc.trimmed and mc.warnings == [B.TRIM_WARNING]
    assert "需需需" not in mc.history_block and "问8" in mc.history_block   # 砍的是最早的那一轮


def test_no_warning_when_under_budget():
    mc = state_context([TurnSnapshot(q="各地区销量", a_brief="华北最高")], 130_000)
    assert mc.trimmed == [] and mc.warnings == [] and mc.history_tokens > 0


def test_twelve_turn_window_is_not_a_budget_trim():
    mc = state_context([TurnSnapshot(q=f"问{i}") for i in range(20)], 130_000)
    assert mc.trimmed == [] and mc.warnings == []


def test_paste_4000_chars_plus_10_turns_does_not_hit_budget(sample_path, monkeypatch):
    """§3.6 的最坏情形：多轮各粘 4000 字 + 9 轮正常问答（估算超过 6000 token）。state 下历史被限在 6000 以内、
    先砍最早的轮次；本轮不触顶，warning 写进结果。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    hist = [("需" * 4000, "结论" * 500)] + [(f"第{i}轮问题", "结论" * 150) for i in range(9)]
    hist = [TurnSnapshot(q=q, a_brief=a[:300]) for q, a in hist] + [TurnSnapshot(q="长" * 4000, a_brief="长结论")
                                                                    for _ in range(3)]
    m = ScriptedChatModel(replies=["根据上文，华北最高"], calls=[])
    r = analyze(sample_path, "所以呢", agent="react", chat_model=m, llm_config=FAST, history=hist)
    assert r.ok and r.memory_mode == "state"
    assert r.history_tokens <= B.HISTORY_TOKENS and r.memory_trimmed == ["history"]
    assert B.TRIM_WARNING in r.warnings and not r.usage.budget_hit
