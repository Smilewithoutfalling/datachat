from app.core.llm import node_llm

_OK_PROMPT = """根据分析结果，用中文简洁、直接地回答用户问题。

用户问题：{question}

分析结果：
{result}
{chart_note}

请给出结论，不要复述代码。若结果标注为"仅显示部分行"，不要对未显示的数据下结论。"""

_FAIL_PROMPT = """分析未能成功完成。

用户问题：{question}
最后一次的错误：{error}

请用中文向用户简要说明没能得出结果，并给出可能的原因或下一步建议。"""


def summarize(state, config=None):
    llm = node_llm(config)
    if state.get("error"):
        msg = _FAIL_PROMPT.format(question=state["question"], error=state["error"])
    else:
        note = f"（已生成图表 {state['chart_path']}）" if state.get("chart_path") else ""
        text = state.get("result_text")
        if text is None:
            text = str(state.get("result"))
        msg = _OK_PROMPT.format(question=state["question"], result=text, chart_note=note)
    return {"answer": llm.invoke(msg)}
