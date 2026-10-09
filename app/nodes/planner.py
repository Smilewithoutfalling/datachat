from app.core.llm import node_llm

_PROMPT = """你是数据分析规划助手。下面是数据表的结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

请用 3-5 个步骤说明如何用 pandas 分析得到答案。只描述思路，不要写代码。"""


def plan(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
    )
    return {"plan": llm.invoke(msg)}
