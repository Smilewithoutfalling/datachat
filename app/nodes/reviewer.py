from app.llm import get_llm, strip_code

_PROMPT = """之前生成的 pandas 代码执行出错了，请修正它。

数据表结构：
{schema}

用户问题：{question}

出错的代码：
{code}

错误信息：
{error}

请输出修正后的完整 Python 代码，规则不变：
- 用变量 df，不要 import，不要重新读文件。
- 最终答案赋给 result；若画图则 plt.savefig(chart_path)。
- 只输出代码，不要解释，不要 markdown 标记。"""


def review_and_fix(state):
    llm = get_llm()
    msg = _PROMPT.format(
        schema=state["schema"],
        question=state["question"],
        code=state["code"],
        error=state["error"],
    )
    return {
        "code": strip_code(llm.invoke(msg).content),
        "attempts": state.get("attempts", 0) + 1,
    }
