"""统一的分析服务函数 analyze()（B16）。

所有入口（run.py / run_react.py / run_eval.py / 两个 Streamlit 页面，以及以后的 FastAPI）
都只调这一个函数，不再各自装配 schema、字典检索、图和模型。

约定：
- 分析过程中的失败（读不了数据、LLM 超时、代码执行失败、ReAct 超步数）不抛异常，
  而是写进结果的 error / error_kind；只有调用参数错误（如未知 agent）才抛 ValueError。
- 数据表只读一次，执行时用副本；question 保持原样，字典说明作为独立的 field_notes（B04）。
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from functools import lru_cache

from app.core.llm import (LLMClient, LLMConfig, LLMError, UsageCallbackHandler,
                          UsageTracker, build_chat_model, classify_error)
from app.core.result import AnalysisResult, Step, format_result, refusal_from_answer

AGENTS = ("workflow", "react")


@lru_cache(maxsize=1)
def _workflow_graph():
    from app.graph import build_graph
    return build_graph()


def analyze(
    dataset,
    question: str,
    *,
    agent: str = "workflow",
    llm_config: LLMConfig | None = None,
    chat_model=None,
    max_attempts: int = 3,
    exec_timeout: int = 20,
    recursion_limit: int = 25,
    use_dictionary: bool = True,
    memory=None,
    thread_id: str | None = None,
    encoding: str | None = None,
    log: bool = False,
) -> AnalysisResult:
    """对一个 CSV 数据集回答一个自然语言问题。

    dataset：CSV 路径（同目录下的同名 .dict.csv 会自动作为数据字典）。
    agent："workflow"（固定状态图，带 reviewer 纠错）或 "react"（模型自主调用工具）。
    llm_config：模型、Key、超时、重试配置；None 时从环境变量读取。
    chat_model：直接注入 LangChain ChatModel（测试/离线评测用），此时不需要 API Key。
    max_attempts：工作流版 reviewer 最多修复几次。
    exec_timeout：单次代码执行超时（秒）。
    recursion_limit：ReAct 版最多走多少步（每次模型调用或工具调用算一步）。
    use_dictionary：是否启用数据字典检索（评测时可关掉，单独衡量 RAG 增益）。
    memory / thread_id：ReAct 多轮对话的 checkpointer（如 MemorySaver）与会话 id。
    encoding：显式指定 CSV 编码；None 时自动检测（失败会报错，不会静默乱码）。
    log：是否把本次记录追加到 outputs/runs.jsonl。
    """
    if agent not in AGENTS:
        raise ValueError(f"未知 agent: {agent!r}，可选 {AGENTS}")

    t0 = time.perf_counter()
    dataset = os.fspath(dataset)
    res = AnalysisResult(agent=agent, dataset=dataset, question=question)
    tracker = UsageTracker()

    try:
        _run(res, tracker, dataset, question, agent=agent, llm_config=llm_config,
             chat_model=chat_model, max_attempts=max_attempts, exec_timeout=exec_timeout,
             recursion_limit=recursion_limit, use_dictionary=use_dictionary,
             memory=memory, thread_id=thread_id, encoding=encoding)
    finally:
        res.timings["total"] = round(time.perf_counter() - t0, 4)
        res.usage = tracker.snapshot()
        if agent == "react":
            res.usage.retries = None     # ReAct 的重试在 openai SDK 内部完成，无法计数
    if log:
        from app.tools.persist import log_run
        log_run({**res.to_record(), "df_path": dataset})
    return res


def _run(res, tracker, dataset, question, *, agent, llm_config, chat_model, max_attempts,
         exec_timeout, recursion_limit, use_dictionary, memory, thread_id, encoding):
    from app.tools.csv_io import read_csv_with_encoding
    from app.tools.dictionary import format_notes, load_retriever, retrieve_notes
    from app.tools.schema import describe_df

    # 1. 数据：只读一次
    t = time.perf_counter()
    try:
        df, enc = read_csv_with_encoding(dataset, encoding)
    except Exception as e:  # noqa: BLE001  文件不存在 / 编码无法识别 / CSV 解析失败
        res.error, res.error_kind = f"数据集读取失败：{type(e).__name__}: {e}", "dataset"
        res.steps.append(Step("load", error=res.error))
        return
    schema = describe_df(df)
    notes = []
    if use_dictionary:
        try:
            notes = retrieve_notes(question, load_retriever(dataset))
        except Exception as e:  # noqa: BLE001  字典坏了不影响主流程，但要留痕
            res.steps.append(Step("dictionary", error=f"数据字典读取失败，已跳过：{e}"))
    res.field_notes = notes
    res.timings["load"] = round(time.perf_counter() - t, 4)
    res.steps.append(Step("load", content=f"{len(df)} 行 × {len(df.columns)} 列，编码 {enc}；"
                                          f"字典命中 {len(notes)} 条",
                          duration_s=res.timings["load"]))

    # 2. 模型
    cfg = llm_config or LLMConfig.from_env()
    if chat_model is None and not cfg.api_key:
        res.error, res.error_kind = "未配置 API Key（DEEPSEEK_API_KEY），无法调用模型。", "llm"
        return

    notes_text = format_notes(notes) if notes else ""
    if agent == "workflow":
        _run_workflow(res, tracker, cfg, chat_model, df, schema, notes_text, question,
                      dataset, max_attempts, exec_timeout)
    else:
        _run_react(res, tracker, cfg, chat_model, df, notes_text, question, dataset,
                   recursion_limit, exec_timeout, memory, thread_id)


# ------------------------------------------------------------------ 工作流版
def _run_workflow(res, tracker, cfg, chat_model, df, schema, notes_text, question, dataset,
                  max_attempts, exec_timeout):
    client = LLMClient(cfg, model=chat_model if chat_model is not None
                       else build_chat_model(cfg, sdk_retries=0), tracker=tracker)
    state = {
        "question": question, "df_path": dataset, "schema": schema,
        "field_notes": notes_text, "attempts": 0, "max_attempts": max_attempts,
        "exec_timeout": exec_timeout,
    }
    config = {
        "configurable": {"llm": client, "df": df},
        # 每轮 reviewer→executor 占 2 步，留足余量，避免 max_attempts 调大后撞上默认上限 25
        "recursion_limit": 2 * max_attempts + 10,
    }
    node_time = defaultdict(float)
    last = time.perf_counter()
    try:
        for chunk in _workflow_graph().stream(state, config, stream_mode="updates"):
            for node, upd in chunk.items():
                now = time.perf_counter()
                dt, last = now - last, now
                upd = upd or {}
                state.update(upd)
                node_time[node] += dt
                res.steps.append(_workflow_step(node, upd, dt))
                if node == "executor":
                    res.executed = not upd.get("error")
    except LLMError as e:
        res.error, res.error_kind = str(e), "llm"
    except Exception as e:  # noqa: BLE001
        res.error, res.error_kind = f"工作流异常：{type(e).__name__}: {e}", "agent"

    res.timings.update({k: round(v, 4) for k, v in node_time.items()})
    res.plan = state.get("plan", "")
    res.code = state.get("code", "")
    res.attempts = state.get("attempts", 0)
    res.initial_error = state.get("initial_error") or None
    res.answer = state.get("answer", "")
    if res.executed:
        res.result = state.get("result")
        res.result_text = state.get("result_text", "")
        res.chart_path = state.get("chart_path") or None
        res.charts = [res.chart_path] if res.chart_path else []
    if res.error is None and state.get("error"):
        res.error, res.error_kind = state["error"], "execution"


def _workflow_step(node, upd, dt) -> Step:
    s = Step(node, duration_s=round(dt, 4))
    if node == "planner":
        s.content = upd.get("plan", "")
    elif node in ("codegen", "reviewer"):
        s.code = upd.get("code", "")
    elif node == "executor":
        s.error = upd.get("error") or None
        s.content = upd.get("result_text", "")
    elif node == "summarizer":
        s.content = upd.get("answer", "")
    return s


# ------------------------------------------------------------------ ReAct 版
def _run_react(res, tracker, cfg, chat_model, df, notes_text, question, dataset,
               recursion_limit, exec_timeout, memory, thread_id):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.errors import GraphRecursionError

    from app.react_agent import build_react_agent

    model = chat_model if chat_model is not None else build_chat_model(cfg, sdk_retries=cfg.max_retries)
    sink = {"execs": [], "charts": []}
    graph = build_react_agent(dataset, checkpointer=memory, sink=sink, model=model, df=df,
                              field_notes=notes_text, exec_timeout=exec_timeout)
    config = {"recursion_limit": recursion_limit, "callbacks": [UsageCallbackHandler(tracker)]}
    if memory is not None:
        config["configurable"] = {"thread_id": thread_id or "default"}

    messages = []
    try:
        out = graph.invoke({"messages": [("user", question)]}, config)
        messages = out["messages"]
    except GraphRecursionError:
        res.error = f"ReAct 超过步数上限（recursion_limit={recursion_limit}）仍未给出结论"
        res.error_kind = "agent"
    except Exception as e:  # noqa: BLE001
        kind, _ = classify_error(e)
        if kind != "unknown":
            res.error, res.error_kind = f"LLM 调用失败（{kind}）：{type(e).__name__}: {e}", "llm"
        else:
            res.error, res.error_kind = f"ReAct 异常：{type(e).__name__}: {e}", "agent"

    # 只看本轮：多轮记忆时 messages 包含历史，取最后一条用户消息之后的部分
    start = 0
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            start = i + 1
    execs = sink["execs"]
    obs_i = 0
    for m in messages[start:]:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                res.steps.append(Step("tool_call", content=str(m.content or ""),
                                      code=(tc.get("args") or {}).get("code", "")))
        elif isinstance(m, ToolMessage):
            e = execs[obs_i] if obs_i < len(execs) else {}
            obs_i += 1
            res.steps.append(Step("observation", content=str(m.content)[:2000],
                                  error=e.get("error"), duration_s=e.get("duration_s")))
        elif isinstance(m, AIMessage):
            res.steps.append(Step("answer", content=str(m.content)))
            res.answer = str(m.content)
    if res.answer.strip().startswith("Sorry, need more steps"):
        # langgraph 剩余步数不足时不抛 GraphRecursionError，而是塞一条英文占位答复（B39）
        res.answer = ""
        if res.error is None:
            res.error = f"ReAct 超过步数上限（recursion_limit={recursion_limit}）仍未给出结论"
            res.error_kind = "agent"

    ok = [e for e in execs if not e["error"]]
    res.attempts = sum(1 for e in execs if e["error"])
    res.initial_error = execs[0]["error"] if execs and execs[0]["error"] else None
    res.charts = list(sink["charts"])
    res.timings["execution"] = round(sum(e["duration_s"] for e in execs), 4)
    if ok:
        last = ok[-1]
        res.executed = True
        res.code = last["code"]
        res.result = last["result"]
        res.result_text = format_result(last["result"])
        res.chart_path = last["chart"] or (res.charts[-1] if res.charts else None)
    elif refusal_from_answer(res.answer) is not None:
        # 模型没调用工具、直接在结论里按契约拒答（B40）
        res.result = res.result_text = refusal_from_answer(res.answer)
        res.executed = True
    elif execs:
        res.code = execs[-1]["code"]
        if res.error is None:
            res.error, res.error_kind = execs[-1]["error"], "execution"
