"""阶段 7.5 第 1 步：节点契约（app/assess/contracts.py）。每条契约至少一正一反。"""
import pandas as pd
import pytest

from app.assess import contracts as C
from app.assess.code_refs import analyze_code, filter_conditions

COLS = ["date", "region", "product", "units", "price", "order_id"]
CTX = C.Context(columns={"": COLS}, question="各地区总销量")
MCTX = C.Context(columns={"orders": ["order_id", "user_id", "amount"], "users": ["user_id", "city"]}, multi=True)


def _st(v):
    return v.status


# ---------------------------------------------------------------- planner
def test_planner_length_ok_and_warn():
    assert _st(C.planner_length({}, {"plan": "按地区求和"}, CTX)) == C.OK
    v = C.planner_length({}, {"plan": "步" * 3001}, CTX)
    assert v.status == C.WARN and v.details["chars"] == 3001 and v.step == 1


def test_planner_columns_ok():
    st = {"schema": "列 region、units；样例 in_transit", "question": "各地区总销量"}
    assert _st(C.planner_columns(st, {"plan": "1. 按 `region` 分组，对 'units' 求和，用 `value_counts`"}, CTX)) == C.OK
    assert _st(C.planner_columns(st, {"plan": "筛选状态为 'in_transit' 的行"}, CTX)) == C.OK   # 样例值
    assert _st(C.planner_columns(st, {"plan": "数据不足以回答：缺少 `unit_cost` 字段"}, CTX)) == C.OK
    assert _st(C.planner_columns(st, {"plan": "", "clarify": "按什么看？"}, CTX)) == C.OK


def test_planner_columns_fail():
    v = C.planner_columns({"schema": "region units"}, {"plan": "1. 用 `unit_cost` 乘以 `units`"}, CTX)
    assert v.status == C.FAIL and v.details["missing"] == ["unit_cost"]


# ---------------------------------------------------------------- codegen
def test_codegen_parse():
    assert _st(C.codegen_parse({}, {"code": "result = 1"}, CTX)) == C.OK
    v = C.codegen_parse({}, {"code": "按地区，求和", "truncated": True}, CTX)
    assert v.status == C.FAIL and "截断" in v.reason


@pytest.mark.parametrize("code", [
    "result = df.groupby('region')['units'].sum()",
    "d = df[df['units'] > 1]\nresult = d.price.mean()",
    "df['amount'] = df['units'] * df['price']\nresult = df.groupby(['region', 'product'])['amount'].sum()",
    "result = df.assign(m=df['date'].str[:7]).groupby('m').agg(total=('units', 'sum'))",
    "result = df.loc[df.region == '华东', ['units', 'price']].sum()",
    "x = df.sort_values(by='units').head(3)\nresult = x[['region']]",
])
def test_codegen_columns_ok(code):
    v = C.codegen_columns({}, {"code": code}, CTX)
    assert v.status == C.OK, v.reason


@pytest.mark.parametrize("code,missing", [
    ("result = df['regin'].nunique()", ["regin"]),
    ("result = df.groupby('area')['units'].sum()", ["area"]),
    ("result = df.revenue.sum()", ["revenue"]),
    ("d = df[df['units'] > 0]\nresult = d['cost'].sum()", ["cost"]),
    ("result = df.loc[:, 'qty'].sum()", ["qty"]),
    ("result = df.sort_values(by=['units', 'qty'])", ["qty"]),
])
def test_codegen_columns_fail(code, missing):
    v = C.codegen_columns({}, {"code": code}, CTX)
    assert v.status == C.FAIL and v.details["missing"] == missing


def test_codegen_columns_multi_table():
    ok = "m = dfs['orders'].merge(dfs['users'], on='user_id')\nresult = m.groupby('city')['amount'].sum()"
    assert _st(C.codegen_columns({}, {"code": ok}, MCTX)) == C.OK
    v = C.codegen_columns({}, {"code": "result = dfs['order']['amount'].sum() + dfs['users']['age'].mean()"}, MCTX)
    assert v.status == C.FAIL and v.details["bad_tables"] == ["order"] and v.details["missing"] == ["users.age"]


def test_codegen_result():
    assert _st(C.codegen_result({}, {"code": "x = 1\nresult = x"}, CTX)) == C.OK
    assert _st(C.codegen_result({}, {"code": "for result in [1]: pass"}, CTX)) == C.OK
    assert _st(C.codegen_result({}, {"code": "df['units'].sum()"}, CTX)) == C.FAIL


def test_codegen_imports():
    assert _st(C.codegen_imports({}, {"code": "import numpy as np\nfrom datetime import date\nresult = 1"}, CTX)) == C.OK
    v = C.codegen_imports({}, {"code": "import os\nfrom scipy import stats\nfrom . import x\nresult = 1"}, CTX)
    assert v.status == C.FAIL and "os" in v.reason and "scipy" in v.reason and "相对导入" in v.reason


def test_codegen_names():
    assert _st(C.codegen_names({}, {"code": "result = len(df) + sum([1]) + np.pi"}, CTX)) == C.OK
    v = C.codegen_names({}, {"code": "result = getattr(df, 'units').sum() if 'df' in globals() else 0"}, CTX)
    assert v.status == C.FAIL and v.details["forbidden"] == ["getattr", "globals"]
    v = C.codegen_names({}, {"code": "result = df['amount'].sum()"}, MCTX)        # 多表没有 df
    assert v.status == C.FAIL and v.details["wrong_data"] == ["df"]
    v = C.codegen_names({}, {"code": "result = dfs['orders']"}, CTX)              # 单表没有 dfs
    assert v.status == C.FAIL and v.details["wrong_data"] == ["dfs"]
    assert _st(C.codegen_names({}, {"code": "result = foo + 1"}, CTX)) == C.WARN
    # 自己绑定过的同名变量不算用了内建
    assert _st(C.codegen_names({}, {"code": "def f(open):\n    return open\nresult = f(1)"}, CTX)) == C.OK


def test_codegen_unparsable_other_contracts_warn():
    for fn in (C.codegen_columns, C.codegen_result, C.codegen_imports, C.codegen_names):
        assert _st(fn({}, {"code": "按地区求和，"}, CTX)) == C.WARN


# ---------------------------------------------------------------- executor
def test_executor_shape():
    v = C.executor_shape({}, {"result": pd.DataFrame({"a": [1, 2]}), "error": ""}, CTX)
    assert v.status == C.OK and v.details == {"type": "DataFrame", "rows": 2, "cols": 1, "columns": ["a"]}
    assert C.executor_shape({}, {"result": "无法回答：没有成本字段", "error": ""}, CTX).reason == "拒答"
    v = C.executor_shape({}, {"result": None, "error": "Traceback\nKeyError: 'regin'"}, CTX)
    assert v.status == C.FAIL and "KeyError: 'regin'" in v.reason
    assert _st(C.executor_shape({}, {"result": None, "error": ""}, CTX)) == C.FAIL


def test_executor_sanity():
    assert _st(C.executor_sanity({}, {"result": 1, "error": "", "sanity_issue": ""}, CTX)) == C.OK
    v = C.executor_sanity({}, {"result": pd.Series([], dtype=float), "error": "", "sanity_issue": "结果是空的（0 行）"}, CTX)
    assert v.status == C.FAIL and "0 行" in v.reason


# ---------------------------------------------------------------- reviewer
def _rev(before, after, **st):
    return C.reviewer_scope({"code": before, **st}, {"code": after}, CTX)


def test_reviewer_scope_ok():
    base = "result = df[df['region'] == '华东']['units'].sum()"
    assert _st(_rev(base, base)) == C.OK                                   # A2 原样交回
    assert _st(_rev(base, "x = df[df['region'] == '华东']\nresult = int(x['units'].sum())")) == C.OK
    v = _rev("result = df.groupby('regin')['units'].sum()", "result = df.groupby('region')['units'].sum()")
    assert v.status == C.OK and v.details["columns_added"] == ["region"]  # 拼错的列改对，不是换口径
    assert _st(_rev("x", "y", not_code=True)) == C.WARN


def test_reviewer_scope_fail_columns_and_filters():
    v = _rev("result = df['units'].sum()", "result = (df['units'] * df['price']).sum()")
    assert v.status == C.FAIL and v.details["columns_added"] == ["price"]                # 悄悄换了指标
    v = _rev("result = df[df['region'] == '华东']['units'].sum()", "result = df[df['region'] == '华东区']['units'].sum()")
    assert v.status == C.FAIL and v.details["filters_added"] == ["region == '华东区'"]
    v = _rev("result = df[df.units > 0].units.mean()", "result = df.units.mean()")
    assert v.status == C.FAIL and v.details["filters_removed"] == ["units > 0"]         # 悄悄换了分母
    assert _st(_rev("result = 1", "按地区，求和")) == C.FAIL


def test_filter_conditions_normalize():
    assert filter_conditions("a = df[df['x'].isin(['A', 'B'])]\nb = df.query('y >= 3')\n"
                             "c = df[df['z'].str.contains('华')]\nd = df[df.w.notna()]") == {
        "x isin ['A', 'B']", "y >= 3", "z str.contains '华'", "w notna"}
    assert analyze_code("result = (", multi=False) is None


# ---------------------------------------------------------------- summarizer
def test_summarizer_grounding_ok():
    st = {"question": "华东总销量", "result_text": "1234.5", "error": ""}
    assert _st(C.summarizer_grounding(st, {"answer": "华东总销量为 1,234.5 件"}, CTX)) == C.OK
    assert _st(C.summarizer_grounding({**st, "clarify": "按什么看？"}, {"answer": "按什么看？"}, CTX)) == C.OK
    assert _st(C.summarizer_grounding({**st, "error": "x"}, {"answer": "失败了 999 次"}, CTX)) == C.OK
    ctx = C.Context(columns={"": COLS}, question="2024 年 300 单以上的有几个")   # 改写前原话里的数字也算证据
    assert _st(C.summarizer_grounding(st, {"answer": "超过 300 单"}, ctx)) == C.OK


def test_summarizer_grounding_fail():
    st = {"question": "华东总销量", "result_text": "1234.5", "error": ""}
    v = C.summarizer_grounding(st, {"answer": "华东总销量为 1,234.5 件，占全国 37.2%"}, CTX)
    assert v.status == C.FAIL and v.details["unverified"] == ["37.2%"]


def test_check_dispatch_covers_every_node():
    assert set(C.CONTRACTS) == {"planner", "codegen", "executor", "reviewer", "summarizer"}
    vs = C.check("codegen", {}, {"code": "result = df['units'].sum()"}, CTX)
    assert [v.contract for v in vs] == ["codegen.parse", "codegen.columns", "codegen.result",
                                         "codegen.imports", "codegen.names"]
    assert all(v.step == 1 for v in vs)
