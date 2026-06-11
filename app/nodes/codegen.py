from app.llm import get_llm, strip_code
from app.tools.plotting import CHART_GUIDE

_PROMPT = """根据分析计划写一段 pandas 代码。

数据表结构：
{schema}

用户问题：{question}

分析计划：
{plan}

严格遵守以下约定：
- 数据已加载到变量 df（pandas DataFrame），不要重新读取文件，不要 import。
- 可直接使用 pd（pandas）和 plt（matplotlib.pyplot，已 import）。
- 把最终答案赋值给变量 result（可以是 DataFrame / Series / 数值 / 字符串）。
- 只输出 Python 代码，不要任何解释，不要 markdown 代码块标记。

{chart_guide}"""


def generate_code(state):
    llm = get_llm()
    msg = _PROMPT.format(
        schema=state["schema"],
        question=state["question"],
        plan=state["plan"],
        chart_guide=CHART_GUIDE,
    )
    return {"code": strip_code(llm.invoke(msg).content)}
