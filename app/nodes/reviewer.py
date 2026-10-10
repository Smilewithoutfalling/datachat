"""B06：修复 prompt 补上分析计划、字段说明和 CHART_GUIDE，
避免修好报错的同时丢掉原本的分析思路和图表要求。"""
from app.core.llm import node_llm, strip_code
from app.tools.plotting import CHART_GUIDE

_PROMPT = """之前生成的 pandas 代码执行出错了，请修正它。

数据表结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

分析计划（修正时保持这个思路，不要删掉原本要做的步骤）：
{plan}

出错的代码：
{code}

错误信息：
{error}

请输出修正后的完整 Python 代码，规则不变：
- 用变量 df，不要重新读文件；pd、np、plt 已就绪，无需 import，不要导入其他库。
- 最终答案赋给 result，result 必须直接回答问题：问哪个只给标签本身（不拼说明文字），问多少给数值，问各…给分组结果，多个小问用 dict 全部答上；不要用中间结果代替。
- 数据回答不了（表里没有所需的字段或信息）时，不要编造或用别的字段凑：result = '无法回答：<一句话原因>'，原因说明缺什么，如 '无法回答：数据中没有成本字段'。
- 原代码若画了图，修正后的代码也要画图，并遵守下面的绘图要求。
- 只输出代码，不要解释，不要 markdown 标记。

{chart_guide}"""


def review_and_fix(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
        plan=state.get("plan", "") or "（无）",
        code=state["code"],
        error=state["error"],
        chart_guide=CHART_GUIDE,
    )
    return {
        "code": strip_code(llm.invoke(msg)),
        "attempts": state.get("attempts", 0) + 1,
    }
