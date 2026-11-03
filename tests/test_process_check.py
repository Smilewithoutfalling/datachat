"""E2 过程验证的单测。

规则不是凭空设计的：每条都对应 13 份闸门报告里真实出现过（或差点误报）的写法。
所以这里除了"命中"，同样重要的是**排除**——`rename`/`drop` 里的 Unnamed、拒答文本、
数字字面量都不许报，否则标记一多就没人看了。
"""
from app.eval.process_check import RULES, check_code, summarize


# ---------- unnamed_column ----------

def test_unnamed_column_hit_when_used_as_data():
    """s06 的真实写法：把 Unnamed: 3（数量）当单价用。"""
    code = (
        "df.columns = ['订单信息', '商品信息', 'Unnamed: 2', 'Unnamed: 3', "
        "'订单信息.1', '商品信息.1', '客户信息', 'Unnamed: 7']\n"
        "df['单价（英镑）'] = pd.to_numeric(df['Unnamed: 3'], errors='coerce')\n"
        "result = df[df['单价（英镑）'] > 100].shape[0]"
    )
    assert check_code(code) == ["unnamed_column"]


def test_unnamed_column_not_excused_by_columns_assignment():
    """把坏名字写进 df.columns 不算正确处理——那是把错误固化下来。"""
    code = "df.columns = ['Unnamed: 3', 'x']\nresult = df['Unnamed: 3'].sum()"
    assert "unnamed_column" in check_code(code)


def test_unnamed_column_excused_in_rename():
    """`rename(columns={'Unnamed: 3': '数量'})` 说明模型认出了坏列名并主动改名，不该标风险。"""
    code = (
        "df = df.rename(columns={'Unnamed: 3': '数量', 'Unnamed: 7': '国家'})\n"
        "result = df['数量'].sum()"
    )
    assert check_code(code) == []


def test_unnamed_column_excused_in_drop():
    """`drop(columns=[...])` 是丢弃垃圾列，同样不算风险。"""
    code = "df = df.drop(columns=['Unnamed: 0', 'Unnamed: 5'])\nresult = len(df)"
    assert check_code(code) == []


def test_unnamed_column_ignores_lookalike_names():
    """只有 `Unnamed: <数字>` 这种 pandas 生成的形态才算；业务里真有 Unnamed 列不算。"""
    code = "result = df['Unnamed 3'].sum() + df['Unnamed:abc'].sum()"
    assert check_code(code) == []


# ---------- placeholder_result ----------

def test_placeholder_result_hit():
    """m09 的真实写法：该拒答（没有年龄字段），结果交了 'ok'。"""
    assert check_code("result = 'ok'") == ["placeholder_result"]


def test_placeholder_result_not_triggered_by_refusal():
    """拒答是正常答复，不是占位符。措辞取自闸门里真实出现过的拒答。"""
    for text in (
        "无法回答：数据中没有成本字段，仅有单价，无法计算毛利率",
        "无法回答：数据中没有客户性别字段",
        "数据中不含成本字段",
        "缺少客户编号，无法统计",
    ):
        assert check_code(f"result = {text!r}") == [], text


def test_placeholder_result_ignores_long_string():
    """长文本是真正的回答（标签答案可能很长），不是占位符。"""
    assert check_code("result = 'WORLD WAR 2 GLIDERS ASSTD DESIGNS'") == []


def test_placeholder_result_ignores_non_result_strings():
    """占位符只看 `result`，别处出现 'ok' 不管。"""
    assert check_code("print('ok')\nresult = df['x'].sum()") == []


# ---------- 不许重复 provenance 的活 ----------

def test_literal_number_result_is_not_flagged():
    """`result = 1036` 是常规提交方式：provenance 的 `result_origin` 已经在记，
    而且 481 份真实代码里 40 条字面量有 37 条判对。E2 不重复标、更不判错。"""
    assert check_code("result = 1036") == []
    assert check_code("result = 8678") == []
    assert check_code("result = 912621.0") == []


def test_container_result_is_not_flagged():
    assert check_code("result = ['a', 'b']") == []
    assert check_code("result = {'x': 1}") == []


# ---------- 判不了就不猜 ----------

def test_syntax_error_returns_empty():
    assert check_code("result = df[") == []


def test_empty_code_returns_empty():
    assert check_code(None) == []
    assert check_code("") == []
    assert check_code("   \n  ") == []


def test_variable_indirection_still_flagged():
    """先把坏列名存进变量再引用——字符串确实出现了，说明它知道这是坏列名，照报。"""
    assert check_code("col = 'Unnamed: 3'\nresult = df[col].sum()") == ["unnamed_column"]


def test_fully_dynamic_column_name_returns_empty():
    """列名完全来自运行时（代码里没有这个字面量）才叫判不了，此时不报。"""
    assert check_code("col = df.columns[3]\nresult = df[col].sum()") == []


def test_unnamed_inside_longer_text_is_not_flagged():
    """正则要求整个字符串就是 `Unnamed: N`，日志/注释式长文本不该命中。"""
    assert check_code("print('列名 Unnamed: 3 说明表头没读对')\nresult = 1") == []


# ---------- summarize ----------

def test_summarize_counts_only_rows_with_code():
    rows = [
        {"id": "a", "code": "result = df['Unnamed: 3'].sum()"},
        {"id": "b", "code": "result = 'ok'"},
        {"id": "c", "code": None},          # 无代码不计入 n
        {"id": "d", "code": "result = 1"},  # 有代码但无标记
    ]
    s = summarize(rows)
    assert s["n"] == 3
    assert s["hits"] == {"unnamed_column": 1, "placeholder_result": 1}
    assert s["cases"] == ["a", "b"]


def test_summarize_reuses_stored_field_for_old_reports():
    """老报告没有 process_risks，现场重算；新报告已存则直接用（不重复解析）。"""
    rows = [
        {"id": "old", "code": "result = df['Unnamed: 3'].sum()"},
        {"id": "new", "code": "result = df['Unnamed: 3'].sum()", "process_risks": []},
    ]
    s = summarize(rows)
    assert s["cases"] == ["old"]


def test_rules_have_descriptions():
    """每个规则都要有一句人话说明，否则报告里只有标签没法读。"""
    assert set(RULES) == {"unnamed_column", "placeholder_result"}
    assert all(RULES.values())
