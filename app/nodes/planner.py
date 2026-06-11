from app.llm import get_llm

_PROMPT = """你是数据分析规划助手。下面是数据表的结构：
{schema}

用户问题：{question}

请用 3-5 个步骤说明如何用 pandas 分析得到答案。只描述思路，不要写代码。"""


def plan(state):
    llm = get_llm()
    msg = _PROMPT.format(schema=state["schema"], question=state["question"])
    return {"plan": llm.invoke(msg).content}
