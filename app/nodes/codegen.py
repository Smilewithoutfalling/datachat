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
- 数据已加载到变量 df（pandas DataFrame），不要重新读取文件。
- pd（pandas）、np（numpy）、plt（matplotlib.pyplot）已就绪，无需 import；不要导入其他库。
- 把最终答案赋值给变量 result（可以是 DataFrame / Series / 数值 / 字符串 / dict），result 必须直接回答问题：
  问"哪个/哪一个"：result 只放标签本身（如 '华南'、'A'、'2024-06'），不要拼接说明文字或数值；
  问"多少/是多少"：给数值；问"各…/每…"：给以分组键为索引的 Series 或表；问"哪些/哪条记录"：给筛选出的行（DataFrame）；
  问题含多个小问（如"分别是多少？哪个更高？"）：result 用 dict 把每个小问都答上，键用简短中文。
  不要把中间结果或整张排序表当作答案；需要的辅助数据放在别的变量里。
  数据回答不了（表里没有所需的字段或信息）时，不要编造或用别的字段凑：result = '无法回答：<一句话原因>'，原因说明缺什么，如 '无法回答：数据中没有成本字段'。
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
