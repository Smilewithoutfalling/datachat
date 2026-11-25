from app.core.llm import node_llm, strip_code
from app.tools.dataset import SINGLE_ACCESS, is_multi_access
from app.tools.plotting import CHART_GUIDE
from app.tools.sandbox_caps import CAPS, prompt_lines

_PROMPT = """根据分析计划写一段 pandas 代码。

数据表结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

分析计划：
{plan}

严格遵守以下约定：
- {data_access}
{sandbox_lines}
- 把最终答案赋值给变量 {result_var}（可以是 DataFrame / Series / 数值 / 字符串 / dict），{result_var} 必须直接回答问题：
  问"哪个/哪一个"：result 只放标签本身（如 '华南'、'A'、'2024-06'），不要拼接说明文字或数值；
  问"多少/是多少"：给数值；问"各…/每…"：给以分组键为索引的 Series 或表；问"哪些/哪条记录"：给筛选出的行（DataFrame）；
  问题含多个小问（如"分别是多少？哪个更高？"）：result 用 dict 把每个小问都答上，键用简短中文。
  不要把中间结果或整张排序表当作答案；需要的辅助数据放在别的变量里。
  数值答案（含 Series / 表里的数值列）保持数值类型，不要用 f'{{x:.2%}}'、拼接 '%' 等方式把数值变成字符串：题目说"百分比/百分数"时用 ×100 后的数值（写 22.30，不写 0.2230）；只说"占比/比例/增长率"时用 0–1 的小数或 ×100 后的数值均可；题目要求保留几位小数时对数值 round；百分号、千分位等格式化交给最终结论。
  数据回答不了（表里没有所需的字段或信息）时，不要编造或用别的字段凑：result = '无法回答：<一句话原因>'，原因写明具体缺的是哪个字段或信息（如 '无法回答：数据中没有 <缺的字段名> 字段'）；分析计划里已经点名缺什么的，照计划写，不要换成别的字段。
- 只输出 Python 代码，不要任何解释，不要 markdown 代码块标记。

{chart_guide}"""


def generate_code(state, config=None):
    llm = node_llm(config)
    msg = _PROMPT.format(
        schema=state["schema"],
        data_access=state.get("data_access") or SINGLE_ACCESS,
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
        plan=state.get("plan", ""),
        chart_guide=CHART_GUIDE,
        # 第 3 步 S3-1：沙箱那几句从能力对象渲染（app/tools/sandbox_caps.py），不再手写
        sandbox_lines=prompt_lines(is_multi_access(state.get("data_access"), SINGLE_ACCESS)),
        result_var=CAPS.result_var,
    )
    text, truncated = llm.invoke_checked(msg)
    return {"code": strip_code(text), "truncated": truncated}
