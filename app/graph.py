from langgraph.graph import StateGraph, START, END

from app.state import AgentState
from app.nodes.planner import plan, replan
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


def _can_replan(state, config) -> bool:
    """第 3 步 S3-3：本轮还没 replan 过，且 tracker 没有超预算（超预算时与重试用尽走同一条路：去 summarizer）。"""
    if state.get("replanned"):
        return False
    tracker = _tracker(config)
    if tracker is not None and tracker.over_budget():
        tracker.mark_budget_hit()
        return False
    return True


def _route_after_exec(state, config=None):
    """执行后的条件路由：报错（或 A2 结果可疑）且还有重试次数 → 去 reviewer 修代码；否则 → 总结。
    V2d §2d：本轮 token 已达预算（含预留）时，即使还有重试次数也不进 reviewer，与重试用尽走同一条路。

    第 3 步 S3-3（phase75-step3.md §4）：reviewer 次数用尽仍然报错、或仍然可疑 → replan（每轮最多一次、不超预算）。
    codegen 列缺失、executor 第一次报错照旧进 reviewer，不触发 replan（边界 2）：要求 reviewer 至少修过一次
    （attempts > 0），max_attempts=0 时第一次报错也不会直接 replan。"""
    # A2：sanity_issue 和报错走同一条路，区别只在于用尽或超预算时它的结果还在，照常去 summarizer
    if not (state.get("error") or state.get("sanity_issue")):
        return "done"
    if state.get("attempts", 0) < state.get("max_attempts", 3):
        tracker = _tracker(config)
        if tracker is not None and tracker.over_budget():
            tracker.mark_budget_hit()
            return "done"
        return "fix"
    if state.get("attempts", 0) > 0 and _can_replan(state, config):
        return "replan"
    return "done"


def scope_gate(state, config=None):
    """第 3 步 S3-2 口径闸（phase75-step3.md §3）：reviewer 出代码之后的确定性判定，不调用模型。

    修复改了口径（增删真实列、改过滤条件；拼错的列名改对、空结果下同列同运算符只换字面量不算）→ 丢弃这次修复：
    code 回退成修复前的代码，记下 scope_rejected，由路由送 replan。判定与评估层 reviewer.scope 同一份
    （app/tools/code_scope.compare_scope）。不拦的情况：修复前不是完整代码 / 解析不了（与评估层 NOT_CHECKED 一致）；
    修复后的代码解析不了或被截断 —— 交给 executor，让它的报错进入下一轮修复（边界 2：异常不设为拦截点）。"""
    from app.tools import code_scope
    from app.tools.sandbox_caps import CAPS
    from app.tools.sanity import is_empty_issue
    base = state.get("code_before_fix") or ""
    if not base or state.get("truncated"):
        return {"scope_rejected": ""}
    chk = code_scope.compare_scope(base, state.get("code") or "", code_scope.columns_of(_data(state, config)),
                                   _multi(state, config), result_var=CAPS.result_var,
                                   empty_before=is_empty_issue(state.get("sanity_issue") or ""))
    if chk.changed:
        return {"code": base, "scope_rejected": chk.summary()}
    return {"scope_rejected": ""}


def _route_after_gate(state, config=None):
    """口径闸之后：放行 → executor；拒收 → replan（预算内、本轮没 replan 过），否则 → summarizer。
    被拒收的修复不执行：拒收后不能 replan 时也不回 executor（回退后的代码就是上一次执行过的那段，再跑一遍
    只会得到同一个结果），直接带着修复前的结果 / 报错去总结。"""
    if state.get("scope_rejected"):
        return "replan" if _can_replan(state, config) else "done"
    return "run"


def _data(state, config):
    conf = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    df = conf.get("df")
    if df is not None:
        return df
    from app.tools.dataset import load_data
    return load_data(state["df_path"])[0]


def _multi(state, config) -> bool:
    from app.tools.dataset import is_multi
    return is_multi(_data(state, config))


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
    g.add_node("scope_gate", scope_gate)
    g.add_node("replan", replan)
    g.add_node("summarizer", summarize)

    g.add_edge(START, "planner")
    # 澄清短路：planner 判定「口径不明」时直接去 summarizer，codegen/executor 一步都不跑。
    # 这条边让 workflow 从"只会算或拒答"变成能反问，代价是 planner prompt 多了一段判断规则。
    g.add_conditional_edges(
        "planner", _route_after_plan, {"clarify": "summarizer", "code": "codegen"}
    )
    g.add_edge("codegen", "executor")
    # 反思纠错闭环：executor → (报错) → reviewer → 口径闸 → executor，循环至成功或用尽重试；
    # 第 3 步：用尽 / 口径闸拒收 → replan → codegen → executor（每轮最多一次）
    g.add_conditional_edges(
        "executor", _route_after_exec, {"fix": "reviewer", "replan": "replan", "done": "summarizer"}
    )
    g.add_edge("reviewer", "scope_gate")
    g.add_conditional_edges(
        "scope_gate", _route_after_gate, {"run": "executor", "replan": "replan", "done": "summarizer"}
    )
    g.add_edge("replan", "codegen")
    g.add_edge("summarizer", END)

    return g.compile()
