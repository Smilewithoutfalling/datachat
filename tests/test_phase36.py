"""阶段 3.6：阶段 3.5 闸门暴露的问题（B61–B64、B66）。每条测试对应一道闸门失败题。"""
import pandas as pd
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.core import LLMConfig, analyze
from app.core.grounding import unverified_numbers
from app.core.llm import api_error_text
from app.core.testing import ScriptedChatModel, prompt_text
from app.eval.comparator import results_equal
from app.tools.sandbox import run_code

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)


def tool_call(code, i=1):
    return AIMessage(content="", tool_calls=[{"name": "run_python_on_data", "args": {"code": code},
                                              "id": f"call_{i}"}])


# ------------------------------------------------------------------ print 回传（s04 / m09 / m06 的共同根因）
def test_run_code_captures_print(sample_df, chart_path):
    cap = {}
    result, _, err = run_code("print('rows', len(df))\nresult = 1", sample_df, chart_path, capture=cap)
    assert err is None and result == 1 and cap["stdout"].strip() == f"rows {len(sample_df)}"


def test_run_code_captures_print_before_error(sample_df, chart_path):
    cap = {}
    _, _, err = run_code("print('before')\nraise ValueError('x')", sample_df, chart_path, capture=cap)
    assert "ValueError" in err and cap["stdout"].strip() == "before"


def test_run_code_print_is_truncated(sample_df, chart_path):
    cap = {}
    run_code("print('x' * 50000)\nresult = 1", sample_df, chart_path, capture=cap)
    assert len(cap["stdout"]) < 9000 and "省略" in cap["stdout"]


def test_react_model_sees_print_output(sample_path):
    """闸门 m06：代码 print 了真值（84 单），模型却看不到、在结论里编了 1,061 单。"""
    m = ScriptedChatModel(replies=[tool_call("print('canceled', 84)\nresult = 23921.17"), "共 84 单，金额 23921.17"],
                          calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    obs = [x for x in m.calls[1] if isinstance(x, ToolMessage)][-1].content
    assert "print 输出" in obs and "canceled 84" in obs
    assert res.ok and res.unverified_numbers == []


# ------------------------------------------------------------------ B61 步数上限
def test_react_out_of_steps_forces_answer(sample_path):
    """闸门 s04：结果算对了，但步数用完，用户只看到一句报错。"""
    state = {"n": 0}

    def respond(messages):
        if "工具调用次数已经用完" in prompt_text(messages):
            return "英国以外共卖出 1685 件。"
        state["n"] += 1
        return tool_call("result = int(df['units'].sum())", state["n"])
    m = ScriptedChatModel(responder=respond, calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST, recursion_limit=5)
    assert res.ok and res.result == 1685 and res.answer == "英国以外共卖出 1685 件。"
    assert res.warnings and "强制收尾" in res.warnings[0]
    assert res.steps[-1].name == "forced_answer"


def test_react_out_of_steps_forced_refusal_wins(sample_path):
    """闸门 m09：步数用完前最后一次 result 是占位 'ok'，不能当答案；强制收尾判定拒答时以拒答为准。"""
    def respond(messages):
        if "工具调用次数已经用完" in prompt_text(messages):
            return "无法回答：数据中没有客户年龄字段"
        return tool_call("result = 'ok'")
    m = ScriptedChatModel(responder=respond, calls=[])
    res = analyze(sample_path, "各年龄段贡献多少", agent="react", chat_model=m, llm_config=FAST, recursion_limit=5)
    assert res.ok and res.result == "无法回答：数据中没有客户年龄字段"


def test_react_out_of_steps_sorry_placeholder_forces_answer(sample_path):
    m = ScriptedChatModel(replies=[tool_call("result = 3"), "Sorry, need more steps to process this request.",
                                   "结果是 3。"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 3 and res.answer == "结果是 3。" and res.warnings


# ------------------------------------------------------------------ B62 网关错误内容
def test_truncated_gateway_error_detected():
    """闸门 s15：'{"message":"prompt 必须包含字符串内容' 没闭合，旧实现认不出。"""
    assert api_error_text('{"message":"prompt 必须包含字符串内容') == "prompt 必须包含字符串内容"
    assert api_error_text('{"message":"ok","data":1}') is None
    assert api_error_text("{ 这不是错误") is None


def test_react_gateway_error_retried(sample_path):
    m = ScriptedChatModel(replies=['{"message":"prompt 必须包含字符串内容', "无法回答：数据中没有性别字段"], calls=[])
    res = analyze(sample_path, "女性客户消费多少", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == "无法回答：数据中没有性别字段"
    assert any(s.name == "retry" for s in res.steps)


def test_react_gateway_error_persistent_is_llm_error(sample_path):
    m = ScriptedChatModel(replies=['{"message":"prompt 必须包含字符串内容'] * 3, calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.answer == "" and res.error_kind == "llm" and res.error.startswith("接口返回错误内容：")   # T11 判定表：分类不变，gateway_error 是内部枚举不再进界面


def test_react_gateway_error_not_retried_with_memory(sample_path):
    """带多轮记忆时失败的一轮已写进历史，重跑会污染上下文，所以不重跑。"""
    m = ScriptedChatModel(replies=['{"message":"busy"}'], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST, memory=MemorySaver(), thread_id="t")
    assert res.error_kind == "llm" and len(m.calls) == 1


# ------------------------------------------------------------------ B63 拒答契约
def test_react_prompt_forbids_redefining_metrics(sample_path):
    """闸门 m10：没有成本字段，ReAct 自己把利润定义成'售价−运费'。"""
    m = ScriptedChatModel(replies=["无法回答：数据中没有成本字段"], calls=[])
    analyze(sample_path, "各类别利润", agent="react", chat_model=m, llm_config=FAST)
    system = prompt_text(m.calls[0][:1])
    assert "不要自己给指标另下定义" in system and "数字必须来自工具返回的" in system


# ------------------------------------------------------------------ B64 叙述与证据
def test_unverified_numbers_flags_m06_fabrication():
    evidence = ["q", "执行成功。result = 23921.17\n\nprint 输出：\n84 84 23921.17 23921.17"]
    answer = "取消订单共 1,061 单，其中 953 单有支付记录，金额合计约 23,921.17。"
    assert unverified_numbers(answer, evidence) == ["1,061", "953"]


def test_unverified_numbers_accepts_rounding_units_and_percent():
    evidence = ["2011 年全年销售额", "执行成功。result = 8998790.914\n\nprint 输出：\n-822023.63 0.2493 541909"]
    answer = ("2011 年销售额 8,998,790.91 英镑，退货冲减约 82.2 万，占 24.93%，共 541,909 行；"
              "涉及 38 个国家。")
    assert unverified_numbers(answer, evidence) == []


def test_unverified_numbers_flags_wrong_magnitude():
    """闸门 s03：脚注写'约 5.4 万行'，实际 541,909 行。"""
    assert unverified_numbers("约 5.4 万行明细", ["541909"]) == ["5.4 万"]


def test_workflow_records_unverified_numbers(sample_path):
    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            return "计划"
        if "写一段 pandas 代码" in t:
            return "result = int(df['units'].sum())"
        return "总销量 1685 件，同比增长 12.5%。"
    res = analyze(sample_path, "总销量", agent="workflow", chat_model=ScriptedChatModel(responder=respond, calls=[]),
                  llm_config=FAST)
    assert res.ok and res.unverified_numbers == ["12.5%"]


# ------------------------------------------------------------------ B66 比较器列表形态
GOLD5 = ["United Kingdom", "Netherlands", "EIRE", "Germany", "France"]


def test_label_set_any_order_and_array():
    gold = frozenset(GOLD5)
    shuffled = ["France", "EIRE", "United Kingdom", "Germany", "Netherlands"]
    assert results_equal(shuffled, gold)
    assert results_equal(pd.Series(shuffled, dtype="string").unique(), gold)    # ArrowStringArray / StringArray
    assert results_equal(pd.DataFrame({"国家": shuffled, "n": range(5)}), gold)
    assert not results_equal(shuffled[:4], gold)
    assert not results_equal(shuffled + ["France"], gold)


def test_topn_labels_on_series_index():
    s = pd.Series([8187806.364, 284661.54, 263276.82, 221698.21, 197403.9], index=pd.Index(GOLD5, name="国家"))
    assert results_equal(s, GOLD5, ordered=True)
    swapped = s.copy()
    swapped.index = [GOLD5[1], GOLD5[0]] + GOLD5[2:]
    assert not results_equal(swapped, GOLD5, ordered=True)


def test_topn_labels_in_frame_column():
    df = pd.DataFrame({"customer_city": GOLD5, "order_count": [5, 4, 3, 2, 1]}, index=[9, 7, 5, 3, 1])
    assert results_equal(df, GOLD5, ordered=True)


# ------------------------------------------------------------------ 回归重跑暴露的两个问题
def test_extension_array_result_survives_sandbox(chart_path):
    """B68：回归 workflow s07 的 .unique() 返回 ArrowStringArray，过沙箱后变成了 repr 字符串，比较器自然判错。"""
    df = pd.DataFrame({"国家": pd.Series(["France", "EIRE", "France", "Germany"], dtype="string")})
    result, _, err = run_code("result = df['国家'].unique()", df, chart_path)
    assert err is None and not isinstance(result, str)
    assert results_equal(result, frozenset({"France", "EIRE", "Germany"}))


def test_react_no_exec_no_refusal_is_nudged(sample_path):
    """B69 → B70：没执行代码、也不是拒答就要收尾（m09 的 'B' / 英文推理摘要）→ 同一会话里先提醒一次。"""
    from app.react_agent import NUDGE_NO_EXEC
    m = ScriptedChatModel(replies=["B", tool_call("result = 3"), "结果是 3。"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 3 and len(m.calls) == 3
    assert any(s.name == "nudge" for s in res.steps) and not any(s.name == "retry" for s in res.steps)
    second = [(x.type, x.content) for x in m.calls[1] if x.type != "system"]
    assert second == [("human", "q"), ("ai", "B"), ("human", NUDGE_NO_EXEC)]


def test_react_nudge_only_once_then_b69_rerun(sample_path):
    """提醒后仍不执行 → 不再提醒，走 B69 整轮重跑（新一轮可以再提醒一次）。"""
    from app.react_agent import NUDGE_NO_EXEC
    m = ScriptedChatModel(replies=["B", "B", tool_call("result = 3"), "结果是 3。"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.ok and res.result == 3 and any(s.name == "retry" for s in res.steps)
    assert len(m.calls) == 4
    assert [x.content for x in m.calls[2] if x.type == "human"] == ["q"]      # 重跑是全新的一轮
    assert sum(1 for c in m.calls for x in c if x.type == "human" and x.content == NUDGE_NO_EXEC) == 1


def test_react_no_exec_no_refusal_persistent_is_error(sample_path):
    m = ScriptedChatModel(replies=["B"] * 6, calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert res.error_kind == "agent" and not res.executed and len(m.calls) == 6   # 3 轮 × （原答 + 提醒后）


def test_react_no_nudge_for_refusal_gateway_error_or_history(sample_path):
    """契约拒答（B40）、网关错误内容（B62 另行重跑）、带 history 的追问：都不提醒。"""
    m = ScriptedChatModel(replies=["无法回答：数据中没有成本字段。"], calls=[])
    analyze(sample_path, "毛利率", agent="react", chat_model=m, llm_config=FAST)
    assert len(m.calls) == 1
    m = ScriptedChatModel(replies=['{"message":"bad gateway"}', tool_call("result = 1"), "1"], calls=[])
    res = analyze(sample_path, "q", agent="react", chat_model=m, llm_config=FAST)
    assert not any(s.name == "nudge" for s in res.steps) and any(s.name == "retry" for s in res.steps)
    m = ScriptedChatModel(replies=["上一轮的结果表示……"], calls=[])
    res = analyze(sample_path, "解释一下", agent="react", chat_model=m, llm_config=FAST,
                  history=[("q", "结果是 3。")])
    assert len(m.calls) == 1 and res.error is None
