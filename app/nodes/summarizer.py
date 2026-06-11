from app.llm import get_llm

_OK_PROMPT = """根据分析结果，用中文简洁、直接地回答用户问题。

用户问题：{question}

分析结果：
{result}
{chart_note}

请给出结论，不要复述代码。"""

_FAIL_PROMPT = """分析未能成功完成。

用户问题：{question}
最后一次的错误：{error}

请用中文向用户简要说明没能得出结果，并给出可能的原因或下一步建议。"""


def summarize(state):
    llm = get_llm()
    if state.get("error"):
        msg = _FAIL_PROMPT.format(question=state["question"], error=state["error"])
    else:
        note = "（已生成图表 outputs/chart.png）" if state.get("chart_path") else ""
        msg = _OK_PROMPT.format(
            question=state["question"], result=state["result"], chart_note=note
        )
    return {"answer": llm.invoke(msg).content}
