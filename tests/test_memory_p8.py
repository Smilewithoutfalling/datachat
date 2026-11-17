"""阶段 6.6 P8：记忆关闭（默认）时，送进模型的消息与阶段 6.6 之前逐字节一致；开关的解析顺序。

下面三个哈希是在 3ce6b77（阶段 6.6 之前的 master）上用同一段脚本算出来的：把每次模型调用收到的全部消息
（类型 + 内容）序列化后取 sha256 前 16 位。改动任何会进 prompt 的文本都会让它变；off 下不许变。

**2026-11-13 重立 workflow 三个哈希**（`c2139ed91836bb54` → `8fd780830946e2cc`，
`3c241f4880db5e29` → `39274e0f04024ea3`）：planner 的 prompt 加了「口径不明就输出 CLARIFY」
那段判断规则，workflow 每条题的第一个模型调用因此都变长。react 的哈希一个都没动 —— 变化
只来自那条新分支，不是记忆功能偷改了 prompt。

**2026-11-13 晚再重立一次**（`8fd780830946e2cc` → `d4f7e82e2b41e9cf`，
`39274e0f04024ea3` → `7f38596168979aa0`）：同一天里改 planner prompt 的 A 类措辞
（「不要追问，也不要给替代口径」那一句，为修 ord_024 / inv_021 被反问），改完忘了重立 ——
这个 8fd7 从立的那一分钟起就没再被验证过。这次是补账，不是新变化：把闸门代码整段删掉
重跑，digest 仍是 d4f7，可复现。

两次重立的代价是同一个：这几个基线再也证明不了"与 3ce6b77 一致"，只能证明"与最后一次
改 planner prompt 之后一致"。P8 的约束没有放宽（off 下仍然不许有任何记忆块），但比对的
锚点从"阶段 6.6 之前"变成了"加澄清分支之后"。下次谁要再动 planner 的 prompt，先想清楚
值不值这个价 —— 而且**改完当场重立**，别隔一轮再补。
"""
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel
from app.memory.config import resolve_memory_mode
from tests.test_core_analyze import wf_model

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
BASELINE = {"react_single": "691077ae7cccb7bb", "react_history": "167addb043be1eda", "workflow": "d4f7e82e2b41e9cf"}
# 批 4a 硬规则 3（docs/roadmap/memory-batch4.md §1）：state 档、没有口径、没开改写时，送进模型的消息与 f39753c
# 逐字节一致。下面四个哈希是在 f39753c 上用同一段脚本（run_all + workflow 带 HISTORY）在 DATACHAT_MEMORY=state 下算的。
# workflow 两个随 2026-11-13 的澄清分支一起重立（见模块 docstring），react 两个未动。
STATE_BASELINE = {"react_single": "691077ae7cccb7bb", "react_history": "a9c62ff882a7728a",
                  "workflow": "d4f7e82e2b41e9cf", "workflow_history": "7f38596168979aa0"}
HISTORY = [("哪个地区卖得最好", "华北，540。"), ("再画个图", "已画柱状图")]


def tc(code):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code}, "id": "c1"}])


def digest(calls):
    out = [[[type(m).__name__, m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)]
            for m in msgs] for msgs in calls]
    return hashlib.sha256(json.dumps(out, ensure_ascii=False).encode()).hexdigest()[:16]


def run_all(sample_path, **kw):
    got, results = {}, {}
    m = ScriptedChatModel(replies=[tc("result = df.groupby('region')['units'].sum()"), "华北最多"], calls=[])
    results["react_single"] = analyze(sample_path, "哪个地区卖得最好", agent="react", chat_model=m, llm_config=FAST, **kw)
    got["react_single"] = digest(m.calls)
    m = ScriptedChatModel(replies=[tc("result = 1"), "好的"], calls=[])
    results["react_history"] = analyze(sample_path, "那华东呢", agent="react", chat_model=m, llm_config=FAST,
                                       history=HISTORY, **kw)
    got["react_history"] = digest(m.calls)
    m = wf_model(["result = df.groupby('region')['units'].sum()"])
    results["workflow"] = analyze(sample_path, "哪个地区卖得最好", chat_model=m, llm_config=FAST, **kw)
    got["workflow"] = digest(m.calls)
    return got, results


def run_state_all(sample_path, **kw):
    got, results = run_all(sample_path, **kw)
    m = wf_model(["result = df.groupby('region')['units'].sum()"])
    results["workflow_history"] = analyze(sample_path, "那华东呢", chat_model=m, llm_config=FAST, history=HISTORY, **kw)
    got["workflow_history"] = digest(m.calls)
    return got, results


def test_off_mode_prompt_is_byte_identical(sample_path):
    # 2026-11-16 起产品默认档是 state（C-021），所以这条必须显式传 off：
    # 它验的是"off 与 3ce6b77 逐字节一致"，不是"不传参数时是什么档"。
    got, results = run_all(sample_path, memory_mode="off")
    assert got == BASELINE
    for r in results.values():
        assert r.memory_mode == "off" and r.memory_trimmed == [] and r.rewrite is None


def test_off_mode_explicit_setting_is_byte_identical(sample_path):
    got, _ = run_all(sample_path, memory_mode="off")
    assert got == BASELINE


def test_off_mode_records_history_tokens_baseline(sample_path):
    _, results = run_all(sample_path, memory_mode="off")
    assert results["react_single"].history_tokens == 0
    chars = sum(len(q) + len(a) for q, a in HISTORY)
    assert results["react_history"].history_tokens == -(-chars // 2)     # EST_CHARS_PER_TOKEN=2
    rec = results["react_history"].to_record()
    for k in ("memory_mode", "history_tokens", "memory_trimmed", "rewrite", "result_digest"):
        assert k in rec
    assert results["react_single"].result_digest == "Series(3) 索引=region"


def test_state_mode_changes_prompt_and_reports_state(sample_path, monkeypatch):
    """反面：state 下 history 那一条必须变（历史进了 system 的数据块，不再以消息回灌），结果里如实记 state。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    got, results = run_all(sample_path)
    assert got["react_history"] != BASELINE["react_history"]
    assert got["react_single"] == BASELINE["react_single"]      # 没有历史时 state 也不出任何块
    assert results["react_history"].memory_mode == "state"


@pytest.mark.parametrize("env,setting,want", [
    # 2026-11-16（C-021）：默认档 off → state。env 与 settings 都没给时落 DEFAULT_MODE；
    # "不认识的值"同理落到默认档，不是落到 off。
    (None, None, "state"), (None, "state", "state"), ("off", "state", "off"), ("state", None, "state"),
    ("full", None, "full"),             # 批 4a：full 是独立一档，不再是 state 的别名（原期望 "state"）
    (None, "full", "full"), ("state", "full", "state"),
    ("bogus", "state", "state"),        # 不认识的环境变量值忽略，落到设置
    (None, "bogus", "state"), (None, "off", "off"), ("", "state", "state"), (" STATE ", None, "state"),
])
def test_resolve_memory_mode_order(monkeypatch, env, setting, want):
    if env is None:
        monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    else:
        monkeypatch.setenv("DATACHAT_MEMORY", env)
    assert resolve_memory_mode(setting) == want


def test_default_mode_is_state(monkeypatch):
    """C-021：env 与 settings 都没有时落 state。off 仍是显式档（上面那行的 ("off", …, "off")）。"""
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    assert resolve_memory_mode() == "state"


def test_settings_value_reaches_analyze(sample_path):
    m = ScriptedChatModel(replies=["华东 525"], calls=[])
    r = analyze(sample_path, "那华东呢", agent="react", chat_model=m, llm_config=FAST, history=HISTORY,
                memory_mode="state")
    assert r.memory_mode == "state" and r.ok          # 有历史：只凭上下文作答不算 B69
    sys_text = m.calls[0][0].content
    assert "<<<历史对话开始" in sys_text and len(m.calls[0]) == 2   # system + 本轮问题，历史不再回灌


def test_env_off_overrides_settings_value(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_MEMORY", "off")
    m = ScriptedChatModel(replies=[tc("result = 1"), "好的"], calls=[])
    r = analyze(sample_path, "那华东呢", agent="react", chat_model=m, llm_config=FAST, history=HISTORY,
                memory_mode="state")
    assert r.memory_mode == "off" and digest(m.calls) == BASELINE["react_history"]


# ------------------------------------------------------------------ 批 4a：state 哈希、full、改写开关
@pytest.fixture
def no_rewrite_env(monkeypatch):
    monkeypatch.delenv("DATACHAT_REWRITE", raising=False)


def test_state_mode_prompt_matches_f39753c(sample_path, monkeypatch, no_rewrite_env):
    """硬规则 3：state、没有口径、没开改写 → 与批 3（f39753c）的 state 逐字节一致。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    got, results = run_state_all(sample_path)
    assert got == STATE_BASELINE
    assert all(r.memory_mode == "state" and r.rewrite is None for r in results.values())


def test_state_mode_explicit_rewrite_off_matches_f39753c(sample_path, monkeypatch, no_rewrite_env):
    monkeypatch.delenv("DATACHAT_MEMORY", raising=False)
    got, _ = run_state_all(sample_path, memory_mode="state", rewrite=False)
    assert got == STATE_BASELINE


def test_full_mode_under_budget_equals_state(sample_path, monkeypatch, no_rewrite_env):
    """full 只在历史超上限时才遮罩：短历史下 prompt 与 state 完全相同，结果里如实记 full。"""
    monkeypatch.setenv("DATACHAT_MEMORY", "full")
    got, results = run_state_all(sample_path)
    assert got == STATE_BASELINE
    assert all(r.memory_mode == "full" for r in results.values())


def test_off_mode_ignores_rewrite_switch(sample_path, monkeypatch):
    """P8：改写开关打开、记忆 off 时，prompt 仍与 3ce6b77 一致，也不发改写请求。"""
    monkeypatch.setenv("DATACHAT_REWRITE", "1")
    # 同 test_off_mode_prompt_is_byte_identical：默认档已不是 off（C-021），这里必须显式关
    got, results = run_all(sample_path, memory_mode="off")
    assert got == BASELINE
    got, results = run_all(sample_path, memory_mode="off", rewrite=True)
    assert got == BASELINE
    assert all(r.rewrite is None for r in results.values())
