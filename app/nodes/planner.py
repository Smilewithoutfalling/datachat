from app.core.llm import node_llm
from app.memory.metrics import PLANNER_REFUSAL_LINE

_PROMPT = """你是数据分析规划助手。下面是数据表的结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

请用 3-5 个步骤说明如何用 pandas 分析得到答案。只描述思路，不要写代码。
若表里没有回答问题所需的字段或信息，直接写明"数据不足以回答"以及缺少什么，不要用其他字段替代。"""


def plan(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
    )
    # 阶段 6.6 M1：工作状态块；批 4b M2：口径块（在状态块之前，优先级 表结构 > 口径 > 字段说明）。
    # 两者都已带数据标记，插在表结构之后；都没有时 prompt 不变（P8 / state 哈希）。
    blocks = [b for b in (state.get("metrics_block"), state.get("memory_state")) if b]
    if blocks:
        joined = "\n\n".join(blocks)
        msg = msg.replace("\n\n相关字段说明（来自数据字典）：", f"\n\n{joined}\n\n相关字段说明（来自数据字典）：", 1)
    if state.get("metrics_block"):   # 拒答补句：只在有口径块时出现
        msg += "\n" + PLANNER_REFUSAL_LINE
    return {"plan": llm.invoke(msg)}
