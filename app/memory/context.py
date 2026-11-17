"""把记忆组装成送进模型的材料（service.py 调用），并给出 result_json 的 memory_* 字段（spec §14.3）。

off：什么都不组装，history 照旧走 user / assistant 消息（service.history_messages），只额外记 history_tokens。
state：历史渲染成数据块（M3 / M5）+ 工作状态块（M1），按 M12 的预算裁剪；ReAct 的消息里不再回灌历史。
full：同 state；完整历史超过本轮上限时先遮罩（M4，app/memory/compact.py），遮罩后仍超才丢最早的轮次。
      没超上限时 full 与 state 的输出逐字节相同。

workflow 的 planner 另有一条 `planner_history`（P0）：折叠后的工作状态块只保留结构化的口径
（表、筛选、指标），指代与被省略的主语全在原文里（「那 S02 呢」「换成上个月」）。原来 workflow
拿不到原文，多轮比 react 少 25 题。这里只补最近 PLANNER_TURNS 轮的原文给 planner，
不进 ReAct 的 system_block —— 那条路本来就有完整历史块，重复喂等于同一个东西付两遍钱。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.memory import budget as B
from app.memory.snapshots import MAX_TURNS, coerce, render_block
from app.memory.working_state import fold, render_ex

# P0：给 workflow 的 planner 补多少轮原文。2 是「指代够用」与「prompt 不变胖」之间的取值：
# 追问的指代几乎都落在上一轮（「那华东呢」「再算上它」），超过两轮还在指代的句子本身
# 就说不清。改这个数会改 state/full 档 workflow 的 prompt 哈希（tests/test_memory_p8.py）。
PLANNER_TURNS = 2


@dataclass
class MemoryContext:
    mode: str = "off"
    state_block: str = ""          # 工作状态块（M1），"" 表示不出现
    history_block: str = ""        # 历史块（M3/M5），"" 表示不出现
    planner_history: str = ""      # 只给 workflow planner 的最近几轮原文（P0），"" 表示不出现
    prompt_history: list | None = None   # 仍以消息回灌的历史（off 模式的 (q, a) 列表；state 模式为 None）
    followup: bool = False         # 本轮之前有没有轮次（B69/B70 的语义：有历史时追问可以只凭上下文作答，§1.4 第 1 条）
    prev_clarify: bool = False     # 上一轮是反问（may_clarify 的出口信号；clarify 轮不产生快照代码，
                                   # 所以不能从 snaps 推断，必须显式传）。不进 prompt
    history_tokens: int = 0
    trimmed: list = field(default_factory=list)   # memory_trimmed：被裁剪的块名
    warnings: list = field(default_factory=list)
    snaps: list = field(default_factory=list)     # state 时本轮之前的快照（B3 get_turn 读它）；off 时为空

    def tools(self) -> list:
        """记忆给 ReAct 追加的工具：state / full 且本轮之前有轮次时是 [get_turn]，否则 []（off 工具表不变，P8）。
        get_turn 读的是原始快照（self.snaps），不是遮罩后的。"""
        if self.mode == "off" or not self.snaps:
            return []
        from app.memory.recall import make_tool
        return [make_tool(self.snaps)]

    @property
    def system_block(self) -> str:
        """插进 system 的整段（状态在前、历史在后）；都没有时为 ""。"""
        return "\n\n".join(b for b in (self.state_block, self.history_block) if b)


def off_context(history, history_messages, prev_clarify: bool = False) -> MemoryContext:
    """off：行为与改动前一致。history_tokens 按真正送出去的那几条消息估算（基线）。"""
    msgs = history_messages(history) if history else []
    return MemoryContext(mode="off", prompt_history=history, followup=bool(history),
                         prev_clarify=prev_clarify,
                         history_tokens=B.estimate_tokens("".join(t for _, t in msgs)))


def state_context(history, token_budget: int, mode: str = "state", prev_clarify: bool = False,
                  planner: bool = False) -> MemoryContext:
    snaps = coerce(history)
    mc = MemoryContext(mode=mode, prompt_history=None, followup=bool(snaps), snaps=snaps,
                       prev_clarify=prev_clarify)
    if not snaps:
        return mc
    state = fold(snaps)
    mc.state_block, cut, cut_c = render_ex(state, B.STATE_TOKENS)
    if cut:
        mc.trimmed.append("state")
    if cut_c:                                          # 用户前提区被裁（B1：最后才裁，一旦裁了单独记）
        mc.trimmed.append("constraints")
    full, _ = render_block(snaps, 10 ** 9)
    expected = next((s.calls for s in reversed(snaps) if s.calls), None)
    cap = B.history_cap(token_budget, expected, B.estimate_tokens(full))
    if mode == "full":                                 # M4：先遮罩再丢轮；只遮罩不丢轮不算裁剪（能用 get_turn 取回）
        from app.memory.compact import fit
        mc.history_block, dropped, _ = fit(snaps, cap)
    else:
        mc.history_block, dropped = render_block(snaps, cap)
    mc.history_tokens = B.estimate_tokens(mc.history_block)
    if dropped > max(0, len(snaps) - MAX_TURNS):      # 超过 12 轮的那部分是固定窗口，不算"被预算裁掉"
        mc.trimmed.append("history")
    # P0：planner 的窗口按轮数切，不按预算——两轮原文最多几百 token，超 1200 就截问题原文，
    # 这里不看本轮总预算：planner 只调用一次，投影闸门（M12）算的是每次调用都要付的块。
    # 只有 workflow 有 planner：react 不算这一块 —— 算了也不送出去，只会在报告里多出一个
    # `memory_trimmed` 标签，把"历史太长"记成"planner 被裁"，那是假归因。
    if planner:
        mc.planner_history, p_cut = render_block(snaps, B.PLANNER_TOKENS, last_n=PLANNER_TURNS)
        if p_cut:                               # 窗口内还被裁（两轮问题加起来上千字）：留痕，别静默
            mc.trimmed.append("planner")
    if mc.trimmed:
        mc.warnings.append(B.TRIM_WARNING)
    return mc


def build(mode: str, history, *, token_budget: int, history_messages, prev_clarify: bool = False,
          planner: bool = False) -> MemoryContext:
    if mode in ("state", "full"):
        return state_context(history, token_budget, mode, prev_clarify=prev_clarify, planner=planner)
    return off_context(history, history_messages, prev_clarify=prev_clarify)
