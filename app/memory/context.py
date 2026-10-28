"""把记忆组装成送进模型的材料（service.py 调用），并给出 result_json 的 memory_* 字段（spec §14.3）。

off：什么都不组装，history 照旧走 user / assistant 消息（service.history_messages），只额外记 history_tokens。
state：历史渲染成数据块（M3 / M5）+ 工作状态块（M1），按 M12 的预算裁剪；ReAct 的消息里不再回灌历史。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.memory import budget as B
from app.memory.snapshots import MAX_TURNS, coerce, render_block
from app.memory.working_state import fold, render


@dataclass
class MemoryContext:
    mode: str = "off"
    state_block: str = ""          # 工作状态块（M1），"" 表示不出现
    history_block: str = ""        # 历史块（M3/M5），"" 表示不出现
    prompt_history: list | None = None   # 仍以消息回灌的历史（off 模式的 (q, a) 列表；state 模式为 None）
    followup: bool = False         # 本轮之前有没有轮次（B69/B70 的语义：有历史时追问可以只凭上下文作答，§1.4 第 1 条）
    history_tokens: int = 0
    trimmed: list = field(default_factory=list)   # memory_trimmed：被裁剪的块名
    warnings: list = field(default_factory=list)

    @property
    def system_block(self) -> str:
        """插进 system 的整段（状态在前、历史在后）；都没有时为 ""。"""
        return "\n\n".join(b for b in (self.state_block, self.history_block) if b)


def off_context(history, history_messages) -> MemoryContext:
    """off：行为与改动前一致。history_tokens 按真正送出去的那几条消息估算（基线）。"""
    msgs = history_messages(history) if history else []
    return MemoryContext(mode="off", prompt_history=history, followup=bool(history),
                         history_tokens=B.estimate_tokens("".join(t for _, t in msgs)))


def state_context(history, token_budget: int) -> MemoryContext:
    snaps = coerce(history)
    mc = MemoryContext(mode="state", prompt_history=None, followup=bool(snaps))
    if not snaps:
        return mc
    state = fold(snaps)
    mc.state_block, cut = render(state, B.STATE_TOKENS)
    if cut:
        mc.trimmed.append("state")
    full, _ = render_block(snaps, 10 ** 9)
    expected = next((s.calls for s in reversed(snaps) if s.calls), None)
    cap = B.history_cap(token_budget, expected, B.estimate_tokens(full))
    mc.history_block, dropped = render_block(snaps, cap)
    mc.history_tokens = B.estimate_tokens(mc.history_block)
    if dropped > max(0, len(snaps) - MAX_TURNS):      # 超过 12 轮的那部分是固定窗口，不算"被预算裁掉"
        mc.trimmed.append("history")
    if mc.trimmed:
        mc.warnings.append(B.TRIM_WARNING)
    return mc


def build(mode: str, history, *, token_budget: int, history_messages) -> MemoryContext:
    return state_context(history, token_budget) if mode == "state" else off_context(history, history_messages)
