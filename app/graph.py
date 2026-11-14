from langgraph.graph import StateGraph, START, END

from app.state import AgentState
from app.nodes.planner import plan
from app.nodes.codegen import generate_code
from app.nodes.executor import execute
from app.nodes.reviewer import review_and_fix
from app.nodes.summarizer import summarize


def _route_after_plan(state, config=None):
    """planner 之后：口径不明就短路到 summarizer，跳过 codegen / executor。

    为什么要短路而不是让 codegen 也写一句「您想按哪个口径看」：codegen 的输出会被
    executor 当代码执行，中文问句进去就是 SyntaxError；就算它识相地写了
    `result = '…'`，那个字符串也会被当成"答案"，判分器与用户都分不清它是澄清还是拒答。

    这条分支是 2026-11-13 补的。在此之前 workflow 结构上无法表达反问
    （旧测试名就叫 test_workflow_cannot_express_clarify），clarify 题在它上面恒为 0 分。
    """
    if state.get("clarify"):
        return "clarify"
    return "code"


def _route_after_exec(state, config=None):
    """执行后的条件路由：报错且还有重试次数 → 去 reviewer 修代码；否则 → 总结。
    V2d §2d：本轮 token 已达预算（含预留）时，即使还有重试次数也不进 reviewer，与重试用尽走同一条路。"""
    if state.get("error") and state.get("attempts", 0) < state.get("max_attempts", 3):
        tracker = _tracker(config)
        if tracker is not None and tracker.over_budget():
            tracker.mark_budget_hit()
            return "done"
        return "fix"
    return "done"


def _tracker(config):
    conf = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    client = conf.get("llm")
    return getattr(client, "tracker", None)


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", plan)
    g.add_node("codegen", generate_code)
    g.add_node("executor", execute)
    g.add_node("reviewer", review_and_fix)
    g.add_node("summarizer", summarize)

    g.add_edge(START, "planner")
    # 澄清短路：planner 判定「口径不明」时直接去 summarizer，codegen/executor 一步都不跑。
    # 这条边让 workflow 从"只会算或拒答"变成能反问，代价是 planner prompt 多了一段判断规则。
    g.add_conditional_edges(
        "planner", _route_after_plan, {"clarify": "summarizer", "code": "codegen"}
    )
    g.add_edge("codegen", "executor")
    # 反思纠错闭环：executor → (报错) → reviewer → executor，循环至成功或用尽重试
    g.add_conditional_edges(
        "executor", _route_after_exec, {"fix": "reviewer", "done": "summarizer"}
    )
    g.add_edge("reviewer", "executor")
    g.add_edge("summarizer", END)

    return g.compile()
