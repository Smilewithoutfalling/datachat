"""不调用真实 LLM：用脚本化假模型跑通工作流图，验证节点衔接与纠错回路。
阶段 1 起模型经 RunnableConfig 的 configurable["llm"] 注入（analyze() 就是这样做的）。"""
import pytest

from app import graph as graph_mod
from app.nodes import planner
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


@pytest.mark.parametrize("state,expected", [    ({"error": "x", "attempts": 0, "max_attempts": 3}, "fix"),
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
    assert "绘图要求" in review and "chart(kind, df" in review and "plt.savefig(chart_path)" in review


# ---------------------------------------------------------------- 澄清短路（EV-B7，2026-11-13）
@pytest.mark.parametrize("text,want_clarify,want_plan", [
    ("CLARIFY: 按金额还是件数看？", "按金额还是件数看？", ""),
    ("CLARIFY：按金额还是件数看？", "按金额还是件数看？", ""),        # 全角冒号：中文输出更常见
    ("**CLARIFY**: 按哪个口径？", "按哪个口径？", ""),               # markdown 装饰
    ("- CLARIFY: 按哪个口径？", "按哪个口径？", ""),
    ("CLARIFY:\n按金额还是件数？", "按金额还是件数？", ""),           # 内容在下一行
    ("CLARIFY:", "", "CLARIFY:"),                                   # 空内容 → 当普通计划，走完整链路
    ("1. 先筛选\n2. 求和", "", "1. 先筛选\n2. 求和"),
    ("", "", ""),
])
def test_split_clarify(text, want_clarify, want_plan):
    assert planner.split_clarify(text) == (want_clarify, want_plan)


def test_clarify_short_circuits_codegen_and_executor(sample_path):
    """口径不明时 planner 打标 → 直接到 summarizer，codegen/executor 一步都不跑。

    `_client(codes=[])`：一旦走到 codegen，`codes.pop(0)` 会 IndexError —— 空列表本身就是断言。
    结果必须是「没有 result、没有 code、answer 就是那句反问」：用户拿到的是问句，
    不是某个假设下的数。
    """
    client = _client("CLARIFY: 您想按销售额还是订单数看？", [], [], "不该走到这里")
    out = _run(sample_path, client)
    assert out["clarify"] == "您想按销售额还是订单数看？"
    assert out["answer"] == "您想按销售额还是订单数看？"   # summarizer 原样返回，不过模型
    assert out["plan"] == ""                              # 协议标记不进「分析计划」
    assert out.get("code") is None and out.get("result") is None
    # 短路时 executor 没跑，state 里不会有 error；attempts 停在初始值 0（一次都没重试）。
    assert out.get("error") is None and out.get("attempts") == 0


def test_empty_clarify_marker_still_runs_normally(sample_path):
    """标记在但没内容 → 不放行。半截输出当计划处理，让 codegen 自己决定算还是拒答。"""
    out = _run(sample_path, _client("CLARIFY:", ["result = int(df['units'].sum())"], [], "答案"))
    assert out["answer"] == "答案" and isinstance(out["result"], int)


def test_route_after_plan():
    assert graph_mod._route_after_plan({"clarify": "您想按哪个口径看？"}) == "clarify"
    assert graph_mod._route_after_plan({"clarify": ""}) == "code"
    assert graph_mod._route_after_plan({}) == "code"
