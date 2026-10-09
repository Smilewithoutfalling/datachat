from app.core.llm import node_llm, strip_code
from app.tools.plotting import CHART_GUIDE

_PROMPT = """根据分析计划写一段 pandas 代码。

数据表结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

分析计划：
{plan}

严格遵守以下约定：
- 数据已加载到变量 df（pandas DataFrame），不要重新读取文件，不要 import。
- 可直接使用 pd（pandas）和 plt（matplotlib.pyplot，已 import）。
- 把最终答案赋值给变量 result（可以是 DataFrame / Series / 数值 / 字符串），result 必须直接回答问题：
  问"哪个/哪一个"就给标签本身（如 '华南'）；问"多少/是多少"就给数值；问"各…/每…"给以分组键为索引的 Series 或表；
  问"哪些记录"给筛选出的行。不要把中间结果或整张排序表当作答案；需要的辅助数据放在别的变量里。
- 只输出 Python 代码，不要任何解释，不要 markdown 代码块标记。

{chart_guide}"""


def generate_code(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
        plan=state.get("plan", ""),
        chart_guide=CHART_GUIDE,
    )
    return {"code": strip_code(llm.invoke(msg))}
