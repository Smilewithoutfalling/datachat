"""不调用真实 LLM：用脚本化假模型跑通工作流图，验证节点衔接与纠错回路。
阶段 1 起模型经 RunnableConfig 的 configurable["llm"] 注入（analyze() 就是这样做的）。"""
import pytest

from app import graph as graph_mod
from app.core.llm import LLMClient, LLMConfig
from app.core.testing import ScriptedChatModel, prompt_text


def _client(plan, codes, fix_codes, answer):
    codes, fixes = list(codes), list(fix_codes)

    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            return plan
        if "请修正它" in t:
            return fixes.pop(0)
        if "写一段 pandas 代码" in t:
            return codes.pop(0)
        return answer
    return LLMClient(LLMConfig(api_key="x"), model=ScriptedChatModel(responder=respond, calls=[]))


def _run(sample_path, client):
    state = {"question": "总销量", "df_path": sample_path, "schema": "s", "attempts": 0, "max_attempts": 3}
    return graph_mod.build_graph().invoke(state, {"configurable": {"llm": client}})


def test_happy_path(sample_path):
    out = _run(sample_path, _client("1. 求和", ["result = int(df['units'].sum())"], [], "答案"))
    assert out["error"] == "" and out["attempts"] == 0 and out["answer"] == "答案"
    assert isinstance(out["result"], int)          # B07：结构化结果，不是字符串
    assert not out.get("initial_error")


def test_reviewer_fixes_error(sample_path):
    client = _client("p", ["result = df['nope'].sum()"], ["result = int(df['units'].sum())"], "ok")
    out = _run(sample_path, client)
    assert out["error"] == "" and out["attempts"] == 1
    assert "KeyError" in out["initial_error"]


def test_gives_up_after_max_attempts(sample_path):
    bad = "result = df['nope']"
    out = _run(sample_path, _client("p", [bad], [bad, bad, bad], "失败说明"))
    assert out["error"] and out["attempts"] == 3 and out["answer"] == "失败说明"


@pytest.mark.parametrize("state,expected", [
    ({"error": "x", "attempts": 0, "max_attempts": 3}, "fix"),
    ({"error": "x", "attempts": 3, "max_attempts": 3}, "done"),
    ({"error": "", "attempts": 0, "max_attempts": 3}, "done"),
])
def test_route_after_exec(state, expected):
    assert graph_mod._route_after_exec(state) == expected


def test_reviewer_prompt_has_plan_and_chart_guide(sample_path):
    """B06：修复 prompt 必须带上分析计划与绘图要求。"""
    seen = []

    def respond(messages):
        t = prompt_text(messages)
        seen.append(t)
        if "数据分析规划助手" in t:
            return "计划：按地区求和后画柱状图"
        if "请修正它" in t:
            return "result = 1"
        if "写一段 pandas 代码" in t:
            return "result = df['nope']"
        return "ok"
    client = LLMClient(LLMConfig(api_key="x"), model=ScriptedChatModel(responder=respond, calls=[]))
    _run(sample_path, client)
    review = [t for t in seen if "请修正它" in t][0]
    assert "计划：按地区求和后画柱状图" in review
    assert "绘图要求" in review and "ax.set_title" in review
