"""ReAct 版本：把工具选择权交给模型（自主智能体）。

与 graph.py 的"固定工作流"不同，这里模型自己决定：
要不要先看数据、调用几次代码工具、报错后怎么改、何时收尾给结论。
控制流由模型的工具调用驱动，而不是预先写死的图。

阶段 1 起由 app/core/service.py 的 analyze() 装配调用：模型、数据表、字段说明都由调用方传入。
"""
import time

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import ensure_dirs
from app.core.result import format_result
from app.tools.csv_io import read_csv
from app.tools.persist import new_chart_path
from app.tools.plotting import CHART_GUIDE
from app.tools.sandbox import run_code
from app.tools.schema import describe_df


def build_react_agent(df_path: str, checkpointer=None, sink=None, *, model=None,
                      df=None, field_notes: str = "", exec_timeout: int = 20):
    """构建一个绑定到指定数据文件的 ReAct 智能体。

    checkpointer: 传入 MemorySaver 可开启多轮记忆（配合 thread_id）。
    sink: 可选 dict。每次工具执行都把记录追加到 sink["execs"]
          （code / result 原始对象 / chart / error / duration_s），生成的图表追加到 sink["charts"]；
          analyze() 据此取最终结果，不必重新执行代码（B07）。
    model: 已配置好超时/重试的 ChatModel；None 时按环境变量构建（旧用法）。
    df: 已读好的 DataFrame（每次执行用副本）；None 时读 df_path。
    field_notes: 本轮问题检索到的字段说明（已格式化），放进系统提示而不是拼进用户问题（B04）。
    """
    if df is None:
        df = read_csv(df_path)
    schema = describe_df(df)
    ensure_dirs()
    if model is None:
        from app.llm import get_llm
        model = get_llm()

    @tool
    def run_python_on_data(code: str) -> str:
        """在已加载的数据表 df（pandas DataFrame）上执行 Python/pandas 代码并返回结果。

        约定：
        - df 已就绪，不要重新读文件、不要 import；可用 pd、plt。
        - 把要查看的结论赋值给变量 result。
        - 需要图表时用 plt 绘制并调用 plt.savefig(chart_path) 保存。
        返回执行结果文本或报错信息（报错时请据此修正代码后重试）。
        """
        chart_path = new_chart_path()
        t0 = time.perf_counter()
        result, chart, error = run_code(code, df.copy(), chart_path, timeout=exec_timeout)
        if sink is not None:
            sink.setdefault("execs", []).append({
                "code": code, "result": None if error else result, "chart": chart,
                "error": error, "duration_s": time.perf_counter() - t0,
            })
        if error:
            return f"执行出错：\n{error}"
        if chart and sink is not None:
            sink.setdefault("charts", []).append(chart)
        msg = f"执行成功。result = {format_result(result, max_chars=1500)}"
        if chart:
            msg += f"\n（已生成图表并保存到 {chart}）"
        return msg

    system = (
        "你是一个数据分析智能体，可以调用工具在真实数据上执行 pandas 代码。\n\n"
        f"数据表结构：\n{schema}\n\n"
        f"与本轮问题相关的字段说明（来自数据字典）：\n{field_notes or '（无）'}\n\n"
        "工作方式：先想清分析思路，再用 run_python_on_data 执行代码来验证；"
        "若报错，读取错误信息、修正代码后重试，直到拿到正确结果。"
        "你最后一次成功执行的代码里的 result 会被当作最终答案保存和展示，所以最后一次执行时 result 必须直接回答问题："
        "问\"哪个\"给标签本身，问\"多少\"给数值，问\"各…/每…\"给以分组键为索引的 Series 或表，问\"哪些记录\"给筛选出的行；"
        "不要用中间表或整张排序表收尾。"
        "如果问题需要图表，请务必画图并保存。\n\n"
        f"{CHART_GUIDE}\n\n"
        "最终用中文给出简洁、直接的结论；若已生成图表，说明图表展示了什么。"
    )

    return create_react_agent(
        model, [run_python_on_data], prompt=system, checkpointer=checkpointer
    )
