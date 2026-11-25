"""修复批 1（docs/roadmap/phase7-fixbatch1.md）：F1 拒答原因不照抄示例、F2 沙箱边界与没赋 result、F3 输出的不是代码。"""
import pandas as pd

from app.memory import metrics as M
from app.nodes import codegen, reviewer
from app.nodes.executor import (NO_RESULT_ERROR, NOT_CODE_ERROR, assigns_result, execute,
                                looks_like_prose)
from app.tools.sandbox import run_code
from app.tools.sandbox_policy import sandbox_name_hint

_PLAN_AS_CODE = ("# 分析计划\n\n1. 基于会话状态中的历史筛选条件，首先从原始数据中筛选出部门为\"研发\"的记录，\n"
                 "2. 计算男性人数占研发部总人数的比例，分母为研发部全体。\n")


def _df():
    return pd.DataFrame({"region": ["华东", "华南"], "units": [3, 4]})


def _cfg():
    return {"configurable": {"df": _df()}}


# ---- F1 ----

def test_refusal_example_no_longer_names_a_concrete_field():
    # mem_003：6 跑都拒答对了，但理由都是示例原文「没有成本字段」，没点名 net_amount
    for text in (codegen._PROMPT, reviewer._PROMPT):
        assert "没有成本字段" not in text
        assert "<缺的字段名>" in text
    from app import react_agent
    import inspect
    assert "数据中没有成本字段" not in inspect.getsource(react_agent)


def test_metric_refusal_lines_require_naming_the_missing_field():
    assert "点名口径引用的、表里不存在的那个字段名" in M.PLANNER_REFUSAL_LINE
    assert "点名口径引用的、表里不存在的那个字段名" in M.REACT_REFUSAL_LINE


# ---- F2a：沙箱内置名 ----

def test_name_hint_only_for_real_builtins():
    assert "沙箱里没有内置函数 globals" in sandbox_name_hint(NameError("x", name="globals"))
    assert sandbox_name_hint(NameError("x", name="my_typo")) == ""     # 模型自己拼错的名字不补
    assert sandbox_name_hint(NameError("x", name="len")) == ""         # 白名单里有的不补
    assert sandbox_name_hint(KeyError("globals")) == ""


def test_globals_error_carries_hint_end_to_end(tmp_path):
    code = "df = pd.read_csv('data.csv') if 'df' not in globals() else df\nresult = int(df['units'].sum())"
    _, _, err = run_code(code, _df(), str(tmp_path / "c.png"))
    assert "NameError" in err and "沙箱里没有内置函数 globals" in err


def test_prompts_state_sandbox_limits():
    # 阶段 7.5 第 3 步 S3-1：沙箱那几句改由 sandbox_caps.prompt_lines 渲染进两处模板（{sandbox_lines}），不再手写
    from app.tools.sandbox_caps import prompt_lines
    for text in (codegen._PROMPT, reviewer._PROMPT):
        assert "{sandbox_lines}" in text
    for multi in (False, True):
        assert "不要判断变量是否存在" in prompt_lines(multi) and "globals" in prompt_lines(multi)


# ---- F2b：没赋 result ----

def test_assigns_result_detection():
    assert not assigns_result("df.groupby('region')['units'].sum()")
    assert assigns_result("result = 1")
    assert assigns_result("result += 1")
    assert assigns_result("for result in [1]: pass")
    assert assigns_result("(result := 3)")
    assert assigns_result("这不是代码，")          # 解析不了按「有」处理，交给原来的 SyntaxError 路径


def test_bare_expression_becomes_error_for_reviewer():
    out = execute({"code": "df.groupby('region')['units'].sum()"}, _cfg())
    assert out["error"] == NO_RESULT_ERROR and out["result"] is None


def test_explicit_none_result_is_left_alone():
    # 写了 result = None 是模型自己的决定，不改判
    out = execute({"code": "result = None"}, _cfg())
    assert out["error"] == ""


def test_chart_only_code_is_left_alone():
    out = execute({"code": "chart('bar', df, x='region', y='units', title='t')"}, _cfg())
    assert out["error"] == ""


# ---- F3：输出的不是代码 ----

def test_prose_detection():
    err = "SyntaxError: invalid character '，' (U+FF0C)"
    assert looks_like_prose(_PLAN_AS_CODE, err)
    assert not looks_like_prose("a = 1\nb = df['x']，\nresult = a", err)                    # 代码里混进一个全角逗号
    assert not looks_like_prose("x = df[df['部门'] == '研发']\ny = 1，\nresult = x", err)   # 汉字只在引号里
    assert not looks_like_prose(_PLAN_AS_CODE, "SyntaxError: invalid syntax")


def test_plan_as_code_is_flagged_and_reviewer_does_not_see_it():
    out = execute({"code": _PLAN_AS_CODE}, _cfg())
    assert out["error"] == NOT_CODE_ERROR and out["not_code"] is True

    seen = []

    class _LLM:
        def invoke_checked(self, msg):
            seen.append(msg)
            return "result = 1", False

    state = {"schema": "s", "question": "q", "plan": "p", "code": _PLAN_AS_CODE,
             "error": out["error"], "not_code": True}
    reviewer.review_and_fix(state, {"configurable": {"llm": _LLM()}})
    assert "基于会话状态中的历史筛选条件" not in seen[0]
    assert reviewer.NOT_CODE_PLACEHOLDER in seen[0]


def test_normal_success_clears_not_code():
    out = execute({"code": "result = 1", "not_code": True}, _cfg())
    assert out["not_code"] is False and out["error"] == ""


def test_planner_refusal_rule_says_name_the_real_missing_field():
    # mem_003：planner 的拒答示例也写着「没有成本字段」，workflow 先过 planner，示例同样会被照抄
    from app.nodes import planner
    assert "本题真正缺的那个字段名" in planner.REFUSAL_RULE and "不要照抄「成本」" in planner.REFUSAL_RULE
