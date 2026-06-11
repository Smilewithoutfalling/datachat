from langgraph.graph import StateGraph, START, END

from app.state import AgentState
from app.nodes.planner import plan
from app.nodes.codegen import generate_code
from app.nodes.executor import execute
from app.nodes.reviewer import review_and_fix
from app.nodes.summarizer import summarize


def _route_after_exec(state):
    """执行后的条件路由：报错且还有重试次数 → 去 reviewer 修代码；否则 → 总结。"""
    if state.get("error") and state.get("attempts", 0) < state.get("max_attempts", 3):
        return "fix"
    return "done"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", plan)
    g.add_node("codegen", generate_code)
    g.add_node("executor", execute)
    g.add_node("reviewer", review_and_fix)
    g.add_node("summarizer", summarize)

    g.add_edge(START, "planner")
    g.add_edge("planner", "codegen")
    g.add_edge("codegen", "executor")
    # 反思纠错闭环：executor → (报错) → reviewer → executor，循环至成功或用尽重试
    g.add_conditional_edges(
        "executor", _route_after_exec, {"fix": "reviewer", "done": "summarizer"}
    )
    g.add_edge("reviewer", "executor")
    g.add_edge("summarizer", END)

    return g.compile()
