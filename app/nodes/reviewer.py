"""B06：修复 prompt 补上分析计划、字段说明和 CHART_GUIDE，
避免修好报错的同时丢掉原本的分析思路和图表要求。"""
from app.core.llm import node_llm, strip_code
from app.tools.dataset import REVIEW_SINGLE_ACCESS
from app.tools.plotting import CHART_GUIDE

NOT_CODE_PLACEHOLDER = "（上一次没有输出代码，输出的是一段文字说明；请按上面的分析计划重新写完整代码）"

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
- {data_access}pd、np、plt、chart 已就绪，无需 import，不要导入其他库。
- 代码在受限沙箱里执行：df 等数据变量一定已就绪，直接使用，不要判断变量是否存在；没有 globals / locals / eval / exec / open 等内置函数。
- 最终答案赋给 result，result 必须直接回答问题：问哪个只给标签本身（不拼说明文字），问多少给数值，问各…给分组结果，多个小问用 dict 全部答上；不要用中间结果代替。
- 数据回答不了（表里没有所需的字段或信息）时，不要编造或用别的字段凑：result = '无法回答：<一句话原因>'，原因写明具体缺的是哪个字段或信息（如 '无法回答：数据中没有 <缺的字段名> 字段'）；分析计划里已经点名缺什么的，照计划写，不要换成别的字段。
- 原代码若画了图（chart() 或 plt），修正后的代码也要画图，并遵守下面的绘图要求。
- 只输出代码，不要解释，不要 markdown 标记。

{chart_guide}"""


def review_and_fix(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        data_access=state.get("data_access_review") or REVIEW_SINGLE_ACCESS,
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
        plan=state.get("plan", "") or "（无）",
        # F3：上一次输出的是文字不是代码时，不把那段文字当「出错的代码」喂回去（否则 reviewer 会接着复述）
        code=NOT_CODE_PLACEHOLDER if state.get("not_code") else state["code"],
        error=state["error"],
        chart_guide=CHART_GUIDE,
    )
    text, truncated = llm.invoke_checked(msg)
    return {
        "code": strip_code(text),
        "truncated": truncated,
        "attempts": state.get("attempts", 0) + 1,
    }
