"""ReAct 版本：把工具选择权交给模型（自主智能体）。

与 graph.py 的"固定工作流"不同，这里模型自己决定：
要不要先看数据、调用几次代码工具、报错后怎么改、何时收尾给结论。
控制流由模型的工具调用驱动，而不是预先写死的图。

阶段 1 起由 app/core/service.py 的 analyze() 装配调用：模型、数据表、字段说明都由调用方传入。

B20（阶段 4 收尾）：不再用已弃用的 langgraph.prebuilt.create_react_agent，改为自己用 StateGraph 搭
"模型 → 工具 → 模型"的循环（build_loop）。行为与原来一致：系统提示在调用时放在最前、不进状态；
状态是 messages（add_messages 合并），可接 checkpointer；步数上限仍由 recursion_limit 控制，
用完抛 GraphRecursionError，由 service 强制收尾（B61）。不同点：模型调用的重试在这里做
（只重试超时 / 限流 / 连接 / 5xx，指数退避），每次重试记进 tracker，ReAct 的重试次数不再是 None（B21）。
"""
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.config import ensure_dirs
from app.core.result import chart_items, chart_note, format_result
from app.tools.dataset import access_rule, copy_data, is_multi, load_data, describe_data
from app.tools.persist import new_chart_path
from app.tools.plotting import CHART_GUIDE
from app.tools.sandbox import run_code


PRINT_CHARS = 2000          # 回给模型的 print 输出上限（字符）


def _clip(text: str, n: int) -> str:
    text = (text or "").rstrip()
    if len(text) <= n:
        return text
    return text[: n // 2] + f"\n…（省略 {len(text) - n} 字符）…\n" + text[-n // 2:]


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _invoke_with_retry(model, messages, config, llm_config, tracker, sleep):
    """调一次模型；超时 / 限流 / 连接 / 5xx 按 llm_config 重试（指数退避），其他错误直接抛。"""
    from app.core.llm import classify_error
    max_retries = llm_config.max_retries if llm_config is not None else 0
    attempts = 0
    while True:
        attempts += 1
        try:
            return model.invoke(messages, config)
        except Exception as e:  # noqa: BLE001
            _, retryable = classify_error(e)
            if not retryable or attempts > max_retries:
                raise
            if tracker is not None:
                tracker.add_retry()
            sleep(min(llm_config.backoff_max, llm_config.backoff_base * 2 ** (attempts - 1)))


def build_loop(model, tools, system: str, checkpointer=None, *, llm_config=None, tracker=None,
               sleep=time.sleep):
    """ReAct 主循环：agent 节点调模型；有工具调用就进 tools 节点逐个执行，再回 agent；没有就结束。"""
    bound = model.bind_tools(tools)
    by_name = {t.name: t for t in tools}

    def agent(state: AgentState, config):
        msg = _invoke_with_retry(bound, [SystemMessage(system)] + list(state["messages"]), config,
                                 llm_config, tracker, sleep)
        return {"messages": [msg]}

    def run_tools(state: AgentState, config):
        last = state["messages"][-1]
        out = []
        for tc in last.tool_calls:
            t = by_name.get(tc.get("name"))
            if t is None:
                content = f"错误：没有名为 {tc.get('name')!r} 的工具，可用的只有 {sorted(by_name)}。"
            else:
                try:
                    content = str(t.invoke(tc.get("args") or {}, config))
                except Exception as e:  # noqa: BLE001  参数不对等：把错误回给模型让它改，和原 ToolNode 一样
                    content = f"错误：{type(e).__name__}: {e}\n请修正后重试。"
            out.append(ToolMessage(content=content, tool_call_id=tc.get("id") or "", name=tc.get("name") or ""))
        return {"messages": out}

    def route(state: AgentState):
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", run_tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)


def build_react_agent(df_path: str, checkpointer=None, sink=None, *, model=None,
                      df=None, field_notes: str = "", exec_timeout: int = 20,
                      llm_config=None, tracker=None, sleep=time.sleep):
    """构建一个绑定到指定数据文件的 ReAct 智能体。

    checkpointer: 传入 MemorySaver 可开启多轮记忆（配合 thread_id）。
    sink: 可选 dict。每次工具执行都把记录追加到 sink["execs"]
          （code / result 原始对象 / chart / error / duration_s / stdout，以及 chart() 的 chart_options 等字段），
          成功执行产出的图表以 {"png", "option"} 条目追加到 sink["charts"]（[26]）；
          analyze() 据此取最终结果，不必重新执行代码（B07）。
    model: 已配置好超时/重试的 ChatModel；None 时按环境变量构建（旧用法）。
    df: 已读好的 DataFrame 或 {表名: DataFrame}（多表，阶段 3.5）；每次执行用副本；None 时读 df_path。
    field_notes: 本轮问题检索到的字段说明（已格式化），放进系统提示而不是拼进用户问题（B04）。
    llm_config / tracker: 模型调用的重试参数与重试计数（B21）；llm_config 为 None 时不重试。
    """
    if df is None:
        df = load_data(df_path)[0]
    schema = describe_data(df)
    multi = is_multi(df)
    ensure_dirs()
    if model is None:
        from app.llm import get_llm
        model = get_llm()

    @tool
    def run_python_on_data(code: str) -> str:
        """在已加载的数据表 df（pandas DataFrame）上执行 Python/pandas 代码并返回结果。

        约定：
        - df 已就绪，不要重新读文件；pd、np、plt、chart 已就绪，无需 import。
        - 把答案赋值给变量 result。
        - print() 的输出也会返回给你（过长会截断），可以用来查看中间结果。
        - 需要图表时优先用 chart(kind, df, x=, y=, series=, title=) 出图；五种图型以外才用 plt 并 plt.savefig(chart_path)。
        返回执行结果文本或报错信息（报错时请据此修正代码后重试）。
        """
        chart_path = new_chart_path()
        t0 = time.perf_counter()
        cap = {}
        result, chart, error = run_code(code, copy_data(df), chart_path, timeout=exec_timeout, capture=cap)
        printed = cap.get("stdout") or ""
        options = cap.get("charts") or []
        chart_errs = cap.get("chart_errors") or []
        if sink is not None:
            sink.setdefault("execs", []).append({
                "code": code, "result": None if error else result, "chart": chart,
                "error": error, "duration_s": time.perf_counter() - t0, "stdout": printed,
                "chart_options": options, "chart_calls": cap.get("chart_calls", 0), "chart_errors": chart_errs,
                "chart_internal_errors": cap.get("chart_internal_errors") or [],
                "charts_discarded": cap.get("charts_discarded", 0), "chart_warnings": cap.get("chart_warnings") or [],
            })
        shown = _clip(printed, PRINT_CHARS)
        if error:
            return f"执行出错：\n{error}" + (f"\n\n出错前的 print 输出：\n{shown}" if shown else "")
        if sink is not None:
            sink.setdefault("charts", []).extend(chart_items(chart, options))
        msg = f"执行成功。result = {format_result(result, max_chars=1500)}"
        if shown:
            msg += f"\n\nprint 输出：\n{shown}"
        if chart:
            msg += f"\n（已生成图表并保存到 {chart}）"
        if options:
            msg += "\n" + chart_note(None, options)
        if chart_errs:
            msg += "\nchart() 未出图：" + "；".join(chart_errs[:4])
        return msg

    if multi:
        # 多表：工具说明里的 df 换成 dfs（单表时工具说明与阶段 3 逐字一致）
        run_python_on_data.description = run_python_on_data.description.replace(
            "在已加载的数据表 df（pandas DataFrame）上", "在已加载的多张数据表 dfs（dict：表名 → DataFrame）上"
        ).replace("- df 已就绪，", "- dfs 已就绪（没有 df），")
    system = (
        "你是一个数据分析智能体，可以调用工具在真实数据上执行 pandas 代码。\n\n"
        f"数据表结构：\n{schema}\n\n"
        + (f"取数约定：{access_rule(df)}\n\n" if multi else "") +
        f"与本轮问题相关的字段说明（来自数据字典）：\n{field_notes or '（无）'}\n\n"
        "工作方式：先想清分析思路，再用 run_python_on_data 执行代码来验证；"
        "若报错，读取错误信息、修正代码后重试，直到拿到正确结果。"
        "你最后一次成功执行的代码里的 result 会被当作最终答案保存和展示，所以最后一次执行时 result 必须直接回答问题："
        "问\"哪个\"时 result 只放标签本身（如 '华中'，不要拼接说明文字或数值），问\"多少\"给数值，"
        "问\"各…/每…\"给以分组键为索引的 Series 或表，问\"哪些/哪条记录\"给筛选出的行（DataFrame），"
        "问题含多个小问时 result 用 dict 把每个小问都答上；数值、说明放在最终中文结论里。"
        "只有一个问题时不要把答案装进 dict，也不要在 result 里附带样本数、计数、明细、中间统计或其他口径的结果"
        "（这些写进最终结论）；口径有歧义时选一种最合理的作为 result，其他口径在结论里说明。"
        "不要用中间表或整张排序表收尾。"
        "如果数据回答不了（表里没有所需的字段或信息），不要编造或用别的字段凑："
        "问题里的指标（如利润、毛利、成本、年龄、性别）在表里没有对应字段、也不能按通行定义由现有字段算出时，"
        "就属于回答不了，不要自己给指标另下定义（例如把'售价−运费'当作利润），也不要用代理变量估算；"
        "仍然调用一次 run_python_on_data，代码为 result = '无法回答：<一句话原因>'（原因说明缺什么，"
        "如 '无法回答：数据中没有成本字段'），最终结论的第一行也必须原样以 '无法回答：' 开头"
        "（不要写成'无法直接回答''无法计算'等其他说法）。"
        "如果问题需要图表，请务必出图。\n\n"
        f"{CHART_GUIDE}\n\n"
        "最终用中文给出简洁、直接的结论；结论里的数字必须来自工具返回的 result 或 print 输出，不要估算或编造；"
        "若已生成图表，说明图表展示了什么。"
    )

    return build_loop(model, [run_python_on_data], system, checkpointer,
                      llm_config=llm_config, tracker=tracker, sleep=sleep)
