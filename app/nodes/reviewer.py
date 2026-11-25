"""B06：修复 prompt 补上分析计划、字段说明和 CHART_GUIDE，
避免修好报错的同时丢掉原本的分析思路和图表要求。"""
from app.core.llm import node_llm, strip_code
from app.tools.dataset import REVIEW_SINGLE_ACCESS, is_multi_access
from app.tools.plotting import CHART_GUIDE
from app.tools.sandbox_caps import CAPS, prompt_lines
from app.tools.sanity import sanity_message

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
- {data_access}
{sandbox_lines}
- 最终答案赋给 {result_var}，{result_var} 必须直接回答问题：问哪个只给标签本身（不拼说明文字），问多少给数值，问各…给分组结果，多个小问用 dict 全部答上；不要用中间结果代替。数值答案保持数值类型，不要格式化成带 '%' 的字符串：题目说"百分比/百分数"时用 ×100 后的数值（写 22.30，不写 0.2230），只说"占比/比例/增长率"时 0–1 的小数或 ×100 均可，格式化交给最终结论。
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
        # A2：执行成功但结果可疑时没有 error，把可疑点当「错误信息」给它（提示里允许原样保留）
        error=state.get("error") or sanity_message(state.get("sanity_issue", "")),
        chart_guide=CHART_GUIDE,
        # 第 3 步 S3-1：沙箱那几句从能力对象渲染（app/tools/sandbox_caps.py），与 codegen 同一份
        sandbox_lines=prompt_lines(is_multi_access(state.get("data_access_review"), REVIEW_SINGLE_ACCESS)),
        result_var=CAPS.result_var,
    )
    text, truncated = llm.invoke_checked(msg)
    return {
        "code": strip_code(text),
        "truncated": truncated,
        "attempts": state.get("attempts", 0) + 1,
    }
