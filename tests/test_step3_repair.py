"""阶段 7.5 第 3 步修复回路（docs/roadmap/phase75-step3.md）：S3-1 能力注入、S3-2 口径判定（code_scope 搬家）。

#127 摘除了 S3-3 REPLAN 与 S3-2 的产品闸（scope_gate 节点、code_before_fix、字面量豁免、recursion_limit 改动，
issue #129）；这里只留 S3-1 与 compare_scope（不含字面量豁免）的用例，外加一条摘除哨兵。
"""
import re

import pandas as pd
import pytest

from app.assess import contracts as C
from app.nodes import codegen, reviewer
from app.tools import code_scope as S
from app.tools.sandbox_caps import CAPS, PROMPT_FORBIDDEN_EXAMPLES, prompt_lines, prompt_vars

COLS = {"": ["date", "region", "product", "units", "price"]}


# =============================================================== S3-1 能力注入
def test_prompt_imports_is_subset_without_private_and_runtime_only():
    pi = CAPS.prompt_imports
    assert set(pi) <= CAPS.allowed_imports and len(set(pi)) == len(pi)
    assert not any(n.startswith("_") for n in pi)
    assert not {"time", "locale", "warnings"} & set(pi)
    # 其余 allowed_imports 全部列出（只去掉上面两类）
    assert set(pi) == {n for n in CAPS.allowed_imports if not n.startswith("_")} - {"time", "locale", "warnings"}


@pytest.mark.parametrize("multi", [False, True])
def test_prompt_lines_names_all_come_from_caps(multi):
    text = prompt_lines(multi)
    lines = text.split("\n")
    assert len(lines) == 3 and all(ln.startswith("- ") for ln in lines)
    # 第一句：已就绪变量（括号里是说明，名字本身反查 CAPS）
    vars_part = re.search(r"已就绪的变量：(.*?)。", lines[0]).group(1)
    names = [re.sub(r"（.*?）", "", x) for x in vars_part.split("、")]
    assert tuple(names) == prompt_vars(multi)
    assert set(names) <= CAPS.injected_names(multi) and CAPS.result_var not in names
    other = CAPS.single_data_vars if multi else CAPS.multi_data_vars
    assert not set(names) & set(other)                     # 多表不出 df，单表不出 dfs
    # 第二句：可以 import 的包 = prompt_imports，且注明只能用这些
    pkgs = re.search(r"可以 import 的包：(.*?)；", lines[1]).group(1).split("、")
    assert tuple(pkgs) == CAPS.prompt_imports and set(pkgs) <= CAPS.allowed_imports
    assert "只能用这些" in lines[1]
    # 第三句：不给的内建 = 固定示例子集 + 「等」
    shown = re.search(r"没有 (.*?) 等内置函数", lines[2]).group(1).split(" / ")
    assert tuple(shown) == PROMPT_FORBIDDEN_EXAMPLES
    for n in shown:
        assert n in CAPS.forbidden_builtins or n == "__import__"
    assert set(PROMPT_FORBIDDEN_EXAMPLES) >= {"globals", "locals", "eval", "exec", "open", "getattr", "__import__"}


def test_prompt_lines_pinned_text():
    """逐字钉住单表渲染结果：改 CAPS 或渲染措辞都要回来改这里（并重立 P8 哈希）。"""
    assert prompt_lines(False) == (
        "- 已就绪的变量：df（数据表）、pd（pandas）、np（numpy）、plt（matplotlib.pyplot）、chart（出图函数，见绘图要求）、"
        "chart_path（图表文件路径）。直接使用，无需 import；df 等数据变量一定已就绪，不要判断变量是否存在。\n"
        "- 可以 import 的包：numpy、pandas、matplotlib、math、statistics、datetime、calendar、re、collections、itertools、"
        "functools、decimal、json；只能用这些，导入其他库会被沙箱拒绝。\n"
        "- 代码在受限沙箱里执行：没有 globals / locals / eval / exec / open / getattr / __import__ 等内置函数。")


class _Capture:
    """最小的 node_llm 替身：记下 prompt，回一段固定文本。"""
    def __init__(self, reply="result = 1"):
        self.prompts, self.reply = [], reply

    def invoke_checked(self, prompt):
        self.prompts.append(prompt)
        return self.reply, False

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def _rendered(monkeypatch, multi=False):
    from app.tools.dataset import access_rule, review_access_rule
    data = {"a": pd.DataFrame({"x": [1]}), "b": pd.DataFrame({"y": [1]})} if multi else pd.DataFrame({"x": [1]})
    st = {"schema": "s", "question": "q", "plan": "p", "code": "result = 1", "error": "E",
          "data_access": access_rule(data), "data_access_review": review_access_rule(data)}
    cap = _Capture()
    monkeypatch.setattr(codegen, "node_llm", lambda cfg: cap)
    monkeypatch.setattr(reviewer, "node_llm", lambda cfg: cap)
    codegen.generate_code(st)
    reviewer.review_and_fix(st)
    return cap.prompts


OLD_HANDWRITTEN = (
    "pd（pandas）、np（numpy）、plt（matplotlib.pyplot）、chart（出图函数，见绘图要求）已就绪，无需 import；不要导入其他库。",
    "pd、np、plt、chart 已就绪，无需 import，不要导入其他库。",
    "没有 globals / locals / eval / exec / open 等内置函数。",
    "不要导入其他库",
)


@pytest.mark.parametrize("multi", [False, True])
def test_codegen_and_reviewer_use_rendered_lines_not_handwritten(monkeypatch, multi):
    for p in _rendered(monkeypatch, multi):
        assert prompt_lines(multi) in p
        for old in OLD_HANDWRITTEN:
            assert old not in p
        assert f"变量 {CAPS.result_var}" in p or f"赋给 {CAPS.result_var}" in p
    for tpl in (codegen._PROMPT, reviewer._PROMPT):
        for old in OLD_HANDWRITTEN:
            assert old not in tpl
        assert "import" not in tpl.split("{chart_guide}")[0].replace("{sandbox_lines}", "")   # 模板里不再手写包名清单


def test_rendered_codegen_prompt_is_stable(monkeypatch):
    a, b = _rendered(monkeypatch), _rendered(monkeypatch)
    assert a == b


# =============================================================== S3-2 口径判定（code_scope.compare_scope）
def _cmp(before, after, cols=COLS, multi=False):
    return S.compare_scope(before, after, cols, multi)


def test_compare_scope_rejects_column_filter_denominator_changes():
    assert _cmp("result = df['units'].sum()", "result = (df['units'] * df['price']).sum()").changed       # 加真实列
    assert _cmp("result = df.groupby('region')['units'].sum()", "result = df['units'].sum()").changed  # 删真实列
    assert _cmp("result = df[df['region'] == '华东']['units'].sum()", "result = df['units'].sum()").changed  # 删过滤
    chk = _cmp("result = df[df.units > 0].units.mean()", "result = df.units.sum() / len(df)")        # 换分母
    assert chk.changed and "过滤条件" in chk.summary()
    chk = _cmp("result = df[df['region'] == '华东']['units'].sum()", "result = df[df['region'] == '华东区']['units'].sum()")
    assert chk.changed and chk.details["filters_added"] == ["region == '华东区'"]                      # 非空结果下换字面量


def test_compare_scope_allows_typo_fix():
    # #129：原 test_compare_scope_allows_typo_fix_and_literal_swap_on_empty 拆掉字面量豁免那半，只留拼错列名放行
    chk = _cmp("result = df.groupby('regin')['units'].sum()", "result = df.groupby('region')['units'].sum()")
    assert chk.status == S.SCOPE_OK and chk.details["columns_added"] == ["region"]


def test_compare_scope_parse_and_not_code():
    assert _cmp("按地区，求和", "result = 1").status == S.SCOPE_NOT_CHECKED
    assert _cmp("result = 1", "result = (").status == S.SCOPE_UNPARSED_AFTER
    assert S.compare_scope("x", "y", COLS, False, not_code=True).status == S.SCOPE_NOT_CHECKED
    assert S.compare_scope("x", "y", COLS, False, truncated=True).status == S.SCOPE_NOT_CHECKED


def test_assess_reviewer_scope_keeps_step1_semantics_without_literal_exemption():
    """评估层 reviewer.scope 保持第 1 步口径、没有字面量豁免：空结果下换过滤条件的字面量仍记 fail。"""
    ctx = C.Context(columns=COLS)
    v = C.reviewer_scope({"code": "result = df[df['region'] == '华东']['units'].sum()", "sanity_issue": "结果是空的（0 行）"},
                         {"code": "result = df[df['region'] == '华东区']['units'].sum()"}, ctx)
    assert v.status == C.FAIL


# =============================================================== 摘除哨兵（#129 / I-01）
def test_step3_strip_no_replan_or_scope_gate():
    """#127 摘除 S3-3 REPLAN 与 S3-2 产品闸后的哨兵（I-01 §9）：图、state、快照模型节点、recursion_limit
    都必须回到 master 9c40a97 的形状。任何一处被加回来（scope_gate / replan 节点、四个 state 字段、
    LLM_NODES 加 replan、recursion_limit 3·max+20）这条都会红。"""
    import inspect

    from app import graph as graph_mod
    from app.assess import snapshot as snapshot_mod
    from app.core import service as service_mod
    from app.state import AgentState

    g = graph_mod.build_graph().get_graph()
    nodes = set(g.nodes) - {"__start__", "__end__"}
    assert nodes == {"planner", "codegen", "executor", "reviewer", "summarizer"}, nodes
    # reviewer 修完直接回 executor（中间没有口径闸）
    assert {e.target for e in g.edges if e.source == "reviewer"} == {"executor"}

    fields = set(AgentState.__annotations__)
    assert not fields & {"code_before_fix", "scope_rejected", "replanned", "replan_reason"}, fields

    assert snapshot_mod.LLM_NODES == ("planner", "codegen", "reviewer", "summarizer")

    src = inspect.getsource(service_mod._run_workflow)
    assert '"recursion_limit": 2 * max_attempts + 10,' in src
    assert "3 * max_attempts" not in src
