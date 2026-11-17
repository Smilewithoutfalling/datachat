"""P0：workflow 的 planner 读最近几轮对话原文（不只是折叠后的工作状态块）。

BACKLOG P0 的事实：同一套 34 道多轮题，react 34/34、workflow + state 24/34。
差的不是记忆开关 —— 开关已经开了，`fold()` 也把结构化口径（表 / 筛选 / 指标）提出来了。
差的是**原文**：指代和被省略的主语（「那 S02 呢」「换成上个月」「再算上它」）只活在这两句话里，
折叠成 `筛选：region == "华北"` 之后就没了。

这里钉五件事：
1. state / full 档、有历史时，planner 的 prompt 里有带数据标记的最近几轮原文；
2. 只给最近 `PLANNER_TURNS` 轮，轮次编号是会话里的**真实**序号（3 轮取后 2 轮 → 第 2/3 轮）；
3. off 档、首轮仍然不带（P8 的逐字节哈希由 test_memory_p8.py 兜住，这里钉「整块不出现」）；
4. 原文只给 planner，不给 codegen / summarizer（同一份材料不重复付钱）；
5. 有原文就算「有上文」：planner 的 FOLLOWUP_HINT 不依赖折叠状态块是否存在。

最后一条是 P0 的**实质**：原来 `elif state.get("memory_state")` 把「是不是追问」绑在状态块上，
而状态块为空（首轮、fold 提不出东西、off 档）时那句话进不去，追问就会被当成新问题反问。
"""
import pytest

from app.core import LLMConfig, analyze
from app.memory.budget import PLANNER_TOKENS
from app.memory.context import PLANNER_TURNS
from app.memory.snapshots import BLOCK_HEAD, BLOCK_TAIL, TurnSnapshot, render_block
from app.nodes import planner
from tests.test_workflow_memory import wf

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)
HISTORY = [("华北卖了多少", "华北 540 件", "result = df[df.region == '华北']['units'].sum()")]
THREE = [("第一轮：华东卖了多少", "华东 320 件"),
         ("第二轮：那华南呢", "华南 280 件"),
         ("第三轮：两个加起来呢", "600 件")]


@pytest.mark.parametrize("mode", ["state", "full"])
def test_planner_sees_recent_turns(sample_path, mode):
    m, log = wf()
    r = analyze(sample_path, "那 S02 呢", chat_model=m, llm_config=FAST,
                history=HISTORY, memory_mode=mode)
    assert r.ok and r.memory_mode == mode
    p = log["planner"][0]
    assert BLOCK_HEAD in p and BLOCK_TAIL in p
    assert "华北卖了多少" in p and "华北 540 件" in p, "上一轮的问与答都要在，只给答案等于没给指代"
    # 位置：原文排在口径块 / 状态块之后、字段说明之前 —— 它是参考材料，不是本轮要遵守的口径
    assert p.index("数据表的结构") < p.index(BLOCK_HEAD) < p.index("相关字段说明")


def test_window_is_last_two_turns_with_real_numbers(sample_path):
    m, log = wf()
    r = analyze(sample_path, "那上个月呢", chat_model=m, llm_config=FAST,
                history=THREE, memory_mode="state")
    assert r.ok
    p = log["planner"][0]
    # 只看历史块正文：状态块（memory_state）里本来就有「- 第N轮：<用户原话>」的前提行，
    # 拿整段 prompt 判「第一轮在不在」会被那几行骗过去。
    seg = p[p.index(BLOCK_HEAD):p.index(BLOCK_TAIL)]
    assert PLANNER_TURNS == 2                       # 窗口宽度是设计值，改它要重立 P8 哈希
    assert "第二轮：那华南呢" in seg and "第三轮：两个加起来呢" in seg
    assert "第一轮：华东卖了多少" not in seg, "超出窗口的轮次不该进 planner（省下的正是首轮的 token）"
    assert "[第2轮" in seg and "[第3轮" in seg and "[第1轮" not in seg, "轮次编号必须是会话真实序号"


def test_off_mode_has_no_history_block(sample_path):
    m, log = wf()
    r = analyze(sample_path, "那 S02 呢", chat_model=m, llm_config=FAST,
                history=HISTORY, memory_mode="off")
    assert r.ok
    assert BLOCK_HEAD not in log["planner"][0], "off 档 planner 不许出现历史块（P8）"


def test_first_turn_has_no_history_block(sample_path):
    m, log = wf()
    r = analyze(sample_path, "哪个地区卖得最好", chat_model=m, llm_config=FAST, memory_mode="state")
    assert r.ok
    assert BLOCK_HEAD not in log["planner"][0], "首轮没有历史，prompt 必须与改动前逐字节相同"


def test_history_only_for_planner(sample_path):
    m, log = wf()
    r = analyze(sample_path, "那 S02 呢", chat_model=m, llm_config=FAST,
                history=HISTORY, memory_mode="state")
    assert r.ok
    for node in ("codegen", "summarizer"):
        assert BLOCK_HEAD not in log[node][0], node


def test_planner_followup_hint_does_not_require_state_block():
    """P0 的实质：有原文就算有上文。

    原来 FOLLOWUP_HINT 的开关是 `state.get("memory_state")`，而 fold() 在只有问答、
    没有代码的轮次上提不出任何字段（`memory_state` 是空串）—— 那种轮次里 planner
    既看不到原文、也不被告知这是追问，于是反问。
    """
    seen = []

    class L:
        def invoke(self, msg):
            seen.append(msg)
            return "计划"
    cfg = {"configurable": {"llm": L()}}
    base = {"schema": "列：a", "field_notes": "", "question": "那 S02 呢"}
    planner.plan({**base, "memory_history": "<<<历史>>>"}, cfg)
    planner.plan({**base, "memory_state": "<<<状态>>>"}, cfg)
    planner.plan(dict(base), cfg)
    assert planner.FOLLOWUP_HINT in seen[0], "只有原文、没有状态块时也必须放行追问"
    assert planner.FOLLOWUP_HINT in seen[1]
    assert planner.FOLLOWUP_HINT not in seen[2], "首轮没有上文，不许凭空放宽"


def test_render_block_last_n_is_a_window_not_a_trim():
    """窗口省略不算「被预算裁掉」：dropped=0，否则调用方会报一句不存在的
    「上下文较长，已自动省略部分较早的对话」。"""
    snaps = [TurnSnapshot(q=f"问{i}", a_brief=f"答{i}") for i in range(1, 6)]
    block, dropped = render_block(snaps, 10 ** 6, last_n=2)
    assert dropped == 0 and "[第4轮" in block and "[第5轮" in block and "[第1轮" not in block
    assert render_block(snaps, 10 ** 6, last_n=0) == ("", 0)
    # 窗口内仍受预算约束：只剩一轮还超时截问题原文，不把整块丢掉
    long = [TurnSnapshot(q="问" * 5000, a_brief="答")]
    block, dropped = render_block(long, PLANNER_TOKENS, last_n=1)
    assert dropped == 0 and len(block) < 5000


def test_planner_window_trim_is_recorded_only_for_workflow():
    """窗口内两轮问题加起来上千字 → 截原文并记一条 `planner`，不静默。

    同时钉住「react 不算这块」：`planner=False` 时既没有块，也不许出现这个标签 ——
    否则 react 的报告会把「历史太长」误记成「planner 被裁」，那是假归因。
    """
    from app.memory.context import state_context
    long = [TurnSnapshot(q="长" * 2000, a_brief="答") for _ in range(2)]
    mc = state_context(long, 130_000, planner=True)
    assert "planner" in mc.trimmed and mc.planner_history
    mc2 = state_context(long, 130_000)               # 默认 planner=False，react 走这条
    assert "planner" not in mc2.trimmed and mc2.planner_history == ""
