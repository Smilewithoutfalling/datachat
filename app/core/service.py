"""统一的分析服务函数 analyze()（B16）。

所有入口（run.py / run_react.py / run_eval.py / 两个 Streamlit 页面，以及以后的 FastAPI）
都只调这一个函数，不再各自装配 schema、字典检索、图和模型。

约定：
- 分析过程中的失败（读不了数据、LLM 超时、代码执行失败、ReAct 超步数）不抛异常，
  而是写进结果的 error / error_kind；只有调用参数错误（如未知 agent）才抛 ValueError。
- 数据表只读一次，执行时用副本；question 保持原样，字典说明作为独立的 field_notes（B04）。

阶段 4（M09）：真正的实现是生成器 analyze_stream()，边跑边产出事件（app/core/events.py）；
analyze() 只是把它跑完、取 done 事件里的结果。两者走同一条代码路径，评测数字不受影响。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict
from functools import lru_cache

from app.core.llm import (api_error_text, LLMClient, LLMConfig, LLMError, UsageCallbackHandler,
                          UsageTracker, build_chat_model, classify_error)
from app.core.events import CANCELLED_MESSAGE, Emitter, Event
from app.core.result import (AnalysisResult, Step, chart_items, chart_warnings, format_result, last_png,
                             refusal_from_answer)

AGENTS = ("workflow", "react")
EVENT_TEXT_CHARS = 2000        # 事件里结果/输出文本的截断长度（完整结果在 done 事件里）

logger = logging.getLogger("datachat.analyze")


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
    history=None,
    encoding: str | None = None,
    log: bool = False,
    trace_id: str | None = None,
) -> AnalysisResult:
    """对一个 CSV 数据集回答一个自然语言问题。

    dataset：CSV 路径（同目录下的同名 .dict.csv 会自动作为数据字典）；
             或目录 / CSV 路径列表 = 多表数据集（代码里用 dfs['表名']，见 app/tools/dataset.py）。
    agent："workflow"（固定状态图，带 reviewer 纠错）或 "react"（模型自主调用工具）。
    llm_config：模型、Key、超时、重试配置；None 时从环境变量读取。
    chat_model：直接注入 LangChain ChatModel（测试/离线评测用），此时不需要 API Key。
    max_attempts：工作流版 reviewer 最多修复几次。
    exec_timeout：单次代码执行超时（秒）。
    recursion_limit：ReAct 版最多走多少步（每次模型调用或工具调用算一步）。
    use_dictionary：是否启用数据字典检索（评测时可关掉，单独衡量 RAG 增益）。
    memory / thread_id：ReAct 多轮对话的 checkpointer（如 MemorySaver）与会话 id。
    history：ReAct 多轮对话的另一种方式：之前各轮的 [(问题, 结论), ...]，按时间顺序（阶段 4，后端从
             messages 表重建，重启不丢）。只带问答，不带中间的工具调用与输出；只取最近 MAX_HISTORY_TURNS 轮。
             与 memory 互斥。工作流版忽略。
    encoding：显式指定 CSV 编码；None 时自动检测（失败会报错，不会静默乱码）。
    log：是否把本次记录追加到 outputs/runs.jsonl。
    trace_id：本次分析的追踪 id（以后由 API 传入消息 id）；None 时生成一个。
    """
    res = None
    for ev in analyze_stream(dataset, question, agent=agent, llm_config=llm_config, chat_model=chat_model,
                             max_attempts=max_attempts, exec_timeout=exec_timeout,
                             recursion_limit=recursion_limit, use_dictionary=use_dictionary,
                             memory=memory, thread_id=thread_id, history=history, encoding=encoding, log=log,
                             trace_id=trace_id):
        if ev.type == "done":
            res = ev.result
    return res


def analyze_stream(
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
    history=None,
    encoding: str | None = None,
    log: bool = False,
    trace_id: str | None = None,
    cancel=None,
):
    """analyze() 的流式版本：一个生成器，按发生顺序产出 Event（类型见 app/core/events.py）。

    参数与 analyze() 相同。最后一个事件一定是 done（携带完整 AnalysisResult，见 Event.result）；
    分析失败时 done 之前有一个 fatal=True 的 error 事件。调用方中途停止迭代（如 SSE 客户端断开）
    会关闭生成器，正在进行的图执行随之停止，此时没有 done 事件、也不写 runs.jsonl。

    cancel：可选的 threading.Event（阶段 5 F2，停止按钮）。每产出一个事件前（含 done 之前）检查一次，
    置位就关掉内部生成器提前收尾：error_kind="cancelled"，照常产出 fatal error + done。粒度与断开连接相同——
    正在进行的那次 LLM 调用或代码执行会跑完，下一个事件之前才停。
    """
    if agent not in AGENTS:
        raise ValueError(f"未知 agent: {agent!r}，可选 {AGENTS}")
    if memory is not None and history:
        raise ValueError("memory 与 history 只能二选一")

    trace_id = trace_id or uuid.uuid4().hex
    em = Emitter(trace_id)
    t0 = time.perf_counter()
    from app.tools.dataset import dataset_label
    if not isinstance(dataset, (list, tuple)):
        dataset = os.fspath(dataset)
    res = AnalysisResult(agent=agent, dataset=dataset_label(dataset), question=question, trace_id=trace_id)
    tracker = UsageTracker()
    logger.info("analyze start trace=%s agent=%s dataset=%s", trace_id, agent, res.dataset)

    def cancelled():
        if cancel is None or not cancel.is_set() or res.error_kind == "cancelled":
            return False
        res.error, res.error_kind = CANCELLED_MESSAGE, "cancelled"
        res.steps.append(Step("cancel", error=res.error))
        return True

    inner = _run(em, res, tracker, dataset, question, agent=agent, llm_config=llm_config,
                 chat_model=chat_model, max_attempts=max_attempts, exec_timeout=exec_timeout,
                 recursion_limit=recursion_limit, use_dictionary=use_dictionary,
                 memory=memory, thread_id=thread_id, history=history, encoding=encoding)
    try:
        for ev in inner:
            if cancelled():
                break
            yield ev
        else:
            cancelled()            # 内部跑完、done 之前再查一次：停止已落库为 cancelled，结果不能报成功
    finally:
        inner.close()              # 提前收尾或外层被关闭（客户端断开）时，停掉正在进行的图执行
        res.timings["total"] = round(time.perf_counter() - t0, 4)
        res.usage = tracker.snapshot()
    if log:
        from app.tools.persist import log_run
        log_run({**res.to_record(), "df_path": res.dataset})
    if res.error is not None:
        logger.warning("analyze failed trace=%s kind=%s: %s", trace_id, res.error_kind, res.error[:300])
        yield em.error(res.error, res.error_kind, fatal=True)
    logger.info("analyze done trace=%s ok=%s total=%.2fs", trace_id, res.ok, res.timings["total"])
    yield em.done(res)


def _run(em, res, tracker, dataset, question, *, agent, llm_config, chat_model, max_attempts,
         exec_timeout, recursion_limit, use_dictionary, memory, thread_id, history, encoding):
    from app.tools.dataset import describe_data, load_data
    from app.tools.dictionary import format_notes, load_retriever, retrieve_notes

    # 1. 数据：只读一次
    t = time.perf_counter()
    try:
        df, load_desc = load_data(dataset, encoding)   # 单表 DataFrame 或多表 {表名: DataFrame}
    except Exception as e:  # noqa: BLE001  文件不存在 / 编码无法识别 / CSV 解析失败
        res.error, res.error_kind = f"数据集读取失败：{type(e).__name__}: {e}", "dataset"
        res.steps.append(Step("load", error=res.error))
        return
    schema = describe_data(df)
    notes = []
    if use_dictionary:
        try:
            notes = retrieve_notes(question, load_retriever(dataset))
        except Exception as e:  # noqa: BLE001  字典坏了不影响主流程，但要留痕
            res.steps.append(Step("dictionary", error=f"数据字典读取失败，已跳过：{e}"))
            yield em.error(res.steps[-1].error, "dataset", fatal=False)
    res.field_notes = notes
    res.timings["load"] = round(time.perf_counter() - t, 4)
    res.steps.append(Step("load", content=f"{load_desc}；字典命中 {len(notes)} 条",
                          duration_s=res.timings["load"]))

    # 2. 模型
    cfg = llm_config or LLMConfig.from_env()
    if chat_model is None and not cfg.api_key:
        res.error, res.error_kind = ("未配置 API Key，无法调用模型。运行 python -m app.core.keystore set 存进系统钥匙串，"
                                             "或设置环境变量 DEEPSEEK_API_KEY。"), "llm"
        return

    notes_text = format_notes(notes) if notes else ""
    if agent == "workflow":
        yield from _run_workflow(em, res, tracker, cfg, chat_model, df, schema, notes_text, question,
                      dataset, max_attempts, exec_timeout)
    else:
        yield from _run_react(em, res, tracker, cfg, chat_model, df, notes_text, question, dataset,
                   recursion_limit, exec_timeout, memory, thread_id, history)


# ------------------------------------------------------------------ 工作流版
def _run_workflow(em, res, tracker, cfg, chat_model, df, schema, notes_text, question, dataset,
                  max_attempts, exec_timeout):
    client = LLMClient(cfg, model=chat_model if chat_model is not None
                       else build_chat_model(cfg, sdk_retries=0), tracker=tracker)
    from app.tools.dataset import access_rule, dataset_label, review_access_rule
    state = {
        "question": question, "df_path": dataset_label(dataset), "schema": schema,
        "data_access": access_rule(df), "data_access_review": review_access_rule(df),
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
                    _tally_charts(res, upd)
                ev = _workflow_event(em, node, upd, dt, state)
                if ev is not None:
                    yield ev
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
        res.charts = chart_items(res.chart_path, state.get("chart_options") or [])
    res.warnings += chart_warnings(res, (state.get("chart_warnings") or []) if res.executed else [])
    if res.error is None and state.get("error"):
        res.error, res.error_kind = state["error"], "execution"
    if res.answer and res.executed and refusal_from_answer(res.answer) is None:
        from app.core.grounding import unverified_numbers
        res.unverified_numbers = unverified_numbers(res.answer, [question, res.result_text])


def _tally_charts(res, e: dict):
    """把一次执行的 chart() 统计累加进结果（工作流 executor 的 update 或 ReAct 的 exec 记录，字段名相同）。"""
    res.chart_calls += e.get("chart_calls") or 0
    res.chart_errors += e.get("chart_errors") or []
    res.charts_discarded += e.get("charts_discarded") or 0
    internal = e.get("chart_internal_errors") or []
    if internal:
        res.chart_internal_errors += internal
        logger.error("chart() 内部错误（必须清零）trace=%s %s", res.trace_id, internal)


def _chart_event_fields(e: dict) -> dict:
    return {"options": e.get("chart_options") or [], "chart_errors": e.get("chart_errors") or [],
            "charts_discarded": e.get("charts_discarded") or 0}


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


def _workflow_event(em, node, upd, dt, state) -> Event | None:
    if node == "planner":
        return em.plan(upd.get("plan", ""))
    if node in ("codegen", "reviewer"):
        return em.code(upd.get("code", ""), source=node, attempt=state.get("attempts", 0))
    if node == "executor":
        err = upd.get("error") or None
        return em.exec(ok=err is None, result_text=(upd.get("result_text") or "")[:EVENT_TEXT_CHARS],
                       error=err, duration_s=round(dt, 4), chart=None if err else (upd.get("chart_path") or None),
                       **_chart_event_fields(upd))
    if node == "summarizer":
        return em.answer(upd.get("answer", ""))
    return None


# ------------------------------------------------------------------ ReAct 版
REACT_GATEWAY_RETRIES = 2      # 网关以错误内容充当回复时，整轮重跑的次数（B62；带多轮记忆时不重跑）

FINALIZE_PROMPT = (
    "你是一个数据分析智能体。工具调用次数已经用完，不能再执行代码。"
    "请只根据下面已经拿到的执行结果，用中文给出最终结论；结论里的数字必须来自这些结果，不要估算或编造。"
    "如果这些结果不足以回答，或者数据里本来就没有所需的信息，结论第一行必须以'无法回答：'开头并说明原因。"
)


MAX_HISTORY_TURNS = 10
MAX_HISTORY_ANSWER_CHARS = 2000


def _head(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def history_messages(history) -> list:
    """[(问题, 结论), ...] → 交替的 user / assistant 消息，只留最近 MAX_HISTORY_TURNS 轮，结论截断。"""
    out = []
    for q, a in list(history or [])[-MAX_HISTORY_TURNS:]:
        out += [("user", str(q)), ("assistant", _head(str(a), MAX_HISTORY_ANSWER_CHARS))]
    return out


def _react_invoke(graph, question, config, em, sink, attempt, out, history=None):
    """流式执行，保留最后一个状态：撞上 GraphRecursionError 时也拿得到已有的消息（B61）。
    边跑边把本轮新增的工具调用 / 执行结果作为 code / exec 事件产出；结论在收尾判定后才产出
    （它可能被判为网关错误或步数占位而作废）。结果写进 out["messages"] / out["err"]。"""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.errors import GraphRecursionError
    messages, err, seen, n_tool = [], None, 0, 0
    try:
        for state in graph.stream({"messages": history_messages(history) + [("user", question)]}, config,
                                  stream_mode="values"):
            messages = state.get("messages", messages)
            start = 0
            for i, m in enumerate(messages):
                if isinstance(m, HumanMessage):
                    start = i + 1
            for m in messages[max(start, seen):]:
                if isinstance(m, AIMessage) and m.tool_calls:
                    for tc in m.tool_calls:
                        yield em.code((tc.get("args") or {}).get("code", ""), source="tool_call",
                                      attempt=attempt, thought=str(m.content or ""))
                elif isinstance(m, ToolMessage):
                    execs = sink.get("execs", [])
                    e = execs[n_tool] if n_tool < len(execs) else {}
                    n_tool += 1
                    yield em.exec(ok=not e.get("error"), result_text=str(m.content)[:EVENT_TEXT_CHARS],
                                  error=e.get("error"), duration_s=e.get("duration_s"),
                                  chart=e.get("chart"), stdout=(e.get("stdout") or "")[:EVENT_TEXT_CHARS],
                                  attempt=attempt, **_chart_event_fields(e))
            seen = len(messages)
    except GraphRecursionError as e:
        err = e
    out["messages"], out["err"] = messages, err


def _final_text(messages):
    from langchain_core.messages import AIMessage
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not m.tool_calls:
            return str(m.content or "")
        if isinstance(m, AIMessage):
            return ""
    return ""


def _run_react(em, res, tracker, cfg, chat_model, df, notes_text, question, dataset,
               recursion_limit, exec_timeout, memory, thread_id, history=None):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langgraph.errors import GraphRecursionError

    from app.core.grounding import unverified_numbers
    from app.react_agent import build_react_agent

    # 重试由 ReAct 循环自己做并计数（B21），SDK 不再重试
    model = chat_model if chat_model is not None else build_chat_model(cfg, sdk_retries=0)
    config = {"recursion_limit": recursion_limit, "callbacks": [UsageCallbackHandler(tracker)]}
    if memory is not None:
        config["configurable"] = {"thread_id": thread_id or "default"}

    retries = 0 if memory is not None else REACT_GATEWAY_RETRIES
    for attempt in range(retries + 1):
        sink = {"execs": [], "charts": []}
        graph = build_react_agent(dataset, checkpointer=memory, sink=sink, model=model, df=df,
                                  field_notes=notes_text, exec_timeout=exec_timeout,
                                  llm_config=cfg, tracker=tracker,
                                  nudge_no_exec=memory is None and not history)
        messages, rec_err = [], None
        res.error = res.error_kind = None
        out = {}
        try:
            yield from _react_invoke(graph, question, config, em, sink, attempt, out, history)
            messages, rec_err = out["messages"], out["err"]
        except Exception as e:  # noqa: BLE001
            kind, _ = classify_error(e)
            if kind != "unknown":
                res.error, res.error_kind = f"LLM 调用失败（{kind}）：{type(e).__name__}: {e}", "llm"
            else:
                res.error, res.error_kind = f"ReAct 异常：{type(e).__name__}: {e}", "agent"
        if sink.get("nudges"):
            res.steps.append(Step("nudge", content="模型没执行代码也没按契约拒答就要结束，已提醒一次（B70）"))
        # B62：网关以错误 JSON 充当回复（可能被截断）→ 整轮重跑
        # B69：一次代码都没执行、也没按契约拒答就收尾（回归 m09 只回了一个 'B'）→ 同样整轮重跑
        final = _final_text(messages)
        why = None
        if rec_err is None and res.error is None:
            if api_error_text(final) is not None:
                why = f"接口返回错误内容：{api_error_text(final)}"
            # 带 history 时追问可以只凭上下文作答（"解释一下上面的结果"），不按 B69 判为异常
            elif not history and not sink["execs"] and refusal_from_answer(final) is None \
                    and not final.strip().startswith("Sorry, need more steps"):
                why = f"模型没有执行代码也没有按契约拒答：{final[:200]!r}"
        if why and attempt < retries:
            tracker.add_retry()
            res.steps.append(Step("retry", error=f"重跑本轮：{why}"))
            yield em.error(res.steps[-1].error, "llm" if why.startswith("接口") else "agent", fatal=False)
            time.sleep(min(cfg.backoff_base * 2 ** attempt, cfg.backoff_max))
            continue
        break

    # 只看本轮：多轮记忆时 messages 包含历史，取最后一条用户消息之后的部分
    start = 0
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            start = i + 1
    execs = sink["execs"]
    obs_i = 0
    evidence = [question]
    for m in messages[start:]:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                res.steps.append(Step("tool_call", content=str(m.content or ""),
                                      code=(tc.get("args") or {}).get("code", "")))
        elif isinstance(m, ToolMessage):
            e = execs[obs_i] if obs_i < len(execs) else {}
            obs_i += 1
            evidence.append(str(m.content))
            evidence.append(e.get("stdout") or "")
            res.steps.append(Step("observation", content=str(m.content)[:2000],
                                  error=e.get("error"), duration_s=e.get("duration_s")))
        elif isinstance(m, AIMessage):
            res.steps.append(Step("answer", content=str(m.content)))
            res.answer = str(m.content)
    bad = api_error_text(res.answer)
    if bad is not None:
        # 网关以错误 JSON 充当回复（B45 / B62）：不是答案，按 LLM 基础设施失败记
        res.answer = ""
        if res.error is None:
            res.error = f"LLM 调用失败（gateway_error）：接口返回错误内容：{bad}"
            res.error_kind = "llm"

    # B61：步数用完（GraphRecursionError，或 langgraph 塞进来的英文占位答复 B39）→ 不再只给一句报错，
    # 用已有的执行结果强制收尾一次；收尾也失败才按 agent 错误记
    out_of_steps = rec_err is not None or res.answer.strip().startswith("Sorry, need more steps")
    if out_of_steps:
        res.answer = ""
        forced = None
        if res.error is None:
            obs = [t for t in evidence[1:] if t][-8:]
            try:
                msg = model.invoke(
                    [SystemMessage(FINALIZE_PROMPT),
                     HumanMessage(f"问题：{question}\n\n已经拿到的执行结果（按时间顺序，可能为空）：\n"
                                  + ("\n\n---\n\n".join(obs) if obs else "（无）"))],
                    config={"callbacks": [UsageCallbackHandler(tracker)]})
                forced = str(getattr(msg, "content", "") or "")
                if api_error_text(forced) is not None or not forced.strip():
                    forced = None
            except Exception:  # noqa: BLE001
                forced = None
        if forced:
            res.answer = forced
            res.steps.append(Step("forced_answer", content=forced))
            res.warnings.append(f"ReAct 达到步数上限（recursion_limit={recursion_limit}），已根据已有执行结果强制收尾")
        elif res.error is None:
            res.error = f"ReAct 超过步数上限（recursion_limit={recursion_limit}）仍未给出结论"
            res.error_kind = "agent"

    ok = [e for e in execs if not e["error"]]
    res.attempts = sum(1 for e in execs if e["error"])
    res.initial_error = execs[0]["error"] if execs and execs[0]["error"] else None
    res.charts = list(sink["charts"])
    for e in execs:
        _tally_charts(res, e)
    res.timings["execution"] = round(sum(e["duration_s"] for e in execs), 4)
    refusal = refusal_from_answer(res.answer)
    if out_of_steps and refusal is not None and res.error is None:
        # 强制收尾判定为拒答：以拒答为准，不拿探索中途的 result（如 m09 的占位 'ok'）冒充答案
        res.result = res.result_text = refusal
        res.executed = True
    elif ok:
        last = ok[-1]
        res.executed = True
        res.code = last["code"]
        res.result = last["result"]
        res.result_text = format_result(last["result"])
        res.chart_path = last["chart"] or last_png(res.charts)
    elif refusal is not None:
        # 模型没调用工具、直接在结论里按契约拒答（B40）
        res.result = res.result_text = refusal
        res.executed = True
    elif execs:
        res.code = execs[-1]["code"]
        if res.error is None:
            res.error, res.error_kind = execs[-1]["error"], "execution"
    elif res.error is None and memory is None and not history:
        # B69：单轮分析里没有执行结果、也不是拒答，不能算成功（多轮追问可以只用文字回答，不在此列）
        res.error = f"ReAct 未执行任何代码也未按契约拒答（结论：{res.answer[:100]!r}）"
        res.error_kind = "agent"

    res.warnings += chart_warnings(res, [w for e in ok for w in e.get("chart_warnings") or []])
    if res.answer and refusal is None:
        res.unverified_numbers = unverified_numbers(res.answer, evidence)
    if res.answer:
        yield em.answer(res.answer, forced=bool(out_of_steps and res.answer))
