"""ReAct 版本：把工具选择权交给模型（自主智能体）。

与 graph.py 的"固定工作流"不同，这里模型自己决定：
要不要先看数据、调用几次代码工具、报错后怎么改、何时收尾给结论。
控制流由模型的工具调用驱动，而不是预先写死的图。
"""
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import ensure_dirs
from app.llm import get_llm
from app.tools.csv_io import read_csv
from app.tools.persist import new_chart_path
from app.tools.plotting import CHART_GUIDE
from app.tools.sandbox import run_code
from app.tools.schema import describe_csv


def build_react_agent(df_path: str, checkpointer=None, sink=None):
    """构建一个绑定到指定数据文件的 ReAct 智能体。

    checkpointer: 传入 MemorySaver 可开启多轮记忆（配合 thread_id）。
    sink: 可选 dict，工具每次生成图表会把路径追加到 sink["charts"]，
          供前端在一轮对话后取出展示（每轮前由调用方清空）。
    """
    schema = describe_csv(df_path)
    ensure_dirs()

    @tool
    def run_python_on_data(code: str) -> str:
        """在已加载的数据表 df（pandas DataFrame）上执行 Python/pandas 代码并返回结果。

        约定：
        - df 已就绪，不要重新读文件、不要 import；可用 pd、plt。
        - 把要查看的结论赋值给变量 result。
        - 需要图表时用 plt 绘制并调用 plt.savefig(chart_path) 保存。
        返回执行结果文本或报错信息（报错时请据此修正代码后重试）。
        """
        df = read_csv(df_path)
        chart_path = new_chart_path()
        result, chart, error = run_code(code, df, chart_path)
        if error:
            return f"执行出错：\n{error}"
        if chart and sink is not None:
            sink.setdefault("charts", []).append(chart)
        msg = f"执行成功。result = {str(result)[:1500]}"
        if chart:
            msg += f"\n（已生成图表并保存到 {chart}）"
        return msg

    system = (
        "你是一个数据分析智能体，可以调用工具在真实数据上执行 pandas 代码。\n\n"
        f"数据表结构：\n{schema}\n\n"
        "工作方式：先想清分析思路，再用 run_python_on_data 执行代码来验证；"
        "若报错，读取错误信息、修正代码后重试，直到拿到正确结果。"
        "如果问题需要图表，请务必画图并保存。\n\n"
        f"{CHART_GUIDE}\n\n"
        "最终用中文给出简洁、直接的结论；若已生成图表，说明图表展示了什么。"
    )

    return create_react_agent(
        get_llm(), [run_python_on_data], prompt=system, checkpointer=checkpointer
    )
