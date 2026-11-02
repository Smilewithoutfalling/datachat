"""答案来源归因的判据。每条断言都对着一次真实跑批的现场。

存在的理由：缺口 11（`ord_004` 有代码执行成功、print 也对，但没赋 `result`）和缺口 12
（`biz_020` 调完 dfs 之后写 `result = '数码商品11'`）在报告里都只表现为"判错"，看不出
是算错、没交卷、还是编的。这两个字段把事实记下来，但**不许进判分**。

⚠️ 最要紧的一条断言：`literal_text` 不等于错。
`emp_022` 的 `result = '数据中没有离职原因字段…'` 是合理的长句结论，数字是从表里抄的。
第一版想把字面量直接判成"编答案"，被这个样本当场推翻——所以这里断言"它只陈述形态"。
"""
import pytest

from app.eval.provenance import describe, refusal_shape, result_missing, result_origin

# 真实样本：outputs/eval_react_20261030_150739_run1.json / run2.json
BIZ_020 = """
oi = dfs['order_items'].copy()
p = dfs['products'].drop_duplicates().copy()
o = dfs['orders'].drop_duplicates().copy()
done = o[o['status']=='已完成']
m = oi.merge(done[['order_id']], on='order_id').merge(p[['sku','product_name','category']], on='sku')
dig = m[m['category']=='数码']
print(dig.groupby('sku')['product_name'].nunique().max())
result = '数码商品11'
"""

ORD_004_NO_RESULT = """
print(df.duplicated().sum())
d2 = df.drop_duplicates(subset=['order_id'])
print(round(d2[d2['status']=='已完成']['pay_amount'].mean(),2))
"""

ORD_004_OK = """
d = df.drop_duplicates(subset=['order_id'])
done = d[d['status']=='已完成']
result = round(done['pay_amount'].mean(), 2)
"""

EMP_022_LONG_TEXT = """
summary = pd.DataFrame({'分组':['司龄1-5年','司龄<1年'], '离职率':[0.190,0.133]})
result = '数据中没有离职原因字段，无法直接给出官方原因；从可观测特征看，离职集中在入职1–5年的成长期员工'
"""


def test_computed_result_is_not_flagged():
    assert result_origin(ORD_004_OK) == "computed"


def test_copied_answer_is_recorded_as_literal_text():
    """缺口 12 的本体：数据都算过了，交上去的是手写字面量。"""
    assert result_origin(BIZ_020) == "literal_text"


def test_long_text_conclusion_is_also_literal_but_still_legal():
    """`emp_022` 的长句结论跟 `biz_020` 同样是 literal_text——字段只报形态，不下判断。

    如果哪天有人把 `literal_*` 直接接进判分，这条会先炸：它证明"字面量"里混着合法答案。
    """
    assert result_origin(EMP_022_LONG_TEXT) == "literal_text"


def test_missing_result_is_told_apart_from_wrong_answer():
    """缺口 11：代码跑了、数也 print 了，但没交卷。"""
    assert result_origin(ORD_004_NO_RESULT) is None
    assert result_missing(ORD_004_NO_RESULT, executed=True, result=None) == "no_assign"


def test_missing_ignored_when_result_present_or_not_executed():
    assert result_missing(ORD_004_OK, executed=True, result=832.54) is None
    assert result_missing(ORD_004_OK, executed=False, result=None) is None


@pytest.mark.parametrize("code,want", [
    ("result = 1", "literal_scalar"),
    ("result = -1.5", "literal_scalar"),
    ("result = True", "literal_scalar"),
    ("result = 'x'", "literal_text"),
    ("result = f'固定文本'", "literal_text"),
    ("result = f'值 {n}'", "computed"),          # 含占位符就不是字面量了
    ("result = [1, 2, 3]", "literal_container"),
    ("result = {'a': 1}", "literal_container"),
    ("result = (1, (2, 3))", "literal_container"),
    ("result = df['x'].mean()", "computed"),
    ("result = dfs['orders']", "computed"),
    ("result = 1 + n", "computed"),
])
def test_literal_kinds(code, want):
    assert result_origin(code) == want


def test_name_is_followed_one_hop():
    """`x = 'a'; result = x` 也是字面量——一层都追不到就永远判 computed，清单会漏掉改写。"""
    assert result_origin("x = 'a'\nresult = x") == "literal_text"


def test_name_from_nowhere_counts_as_computed():
    """"判不了"一律往 computed 靠：宁可漏报，不许把算出来的答案标成编的。"""
    assert result_origin("result = outside_var") == "computed"


def test_last_write_wins():
    assert result_origin("result = '占位'\nresult = df['x'].sum()") == "computed"
    assert result_origin("result = df['x'].sum()\nresult = 0") == "literal_scalar"


def test_append_is_mutated_not_literal():
    """先 `result = []` 再 append，不该被"最后一次赋值为空容器"误判成 empty。"""
    code = "result = []\nfor _, r in df.iterrows():\n    result.append(r['x'])"
    assert result_origin(code) == "mutated"
    assert result_missing(code, executed=True, result=None) == "assign_none"


def test_empty_container_is_called_out():
    assert result_missing("result = []", executed=True, result=None) == "empty"
    assert result_missing("result = {}", executed=True, result=None) == "empty"


def test_cond_assign_explains_a_branch_that_never_ran():
    code = "if len(df) > 99999:\n    result = 1"
    assert result_missing(code, executed=True, result=None) == "cond_assign"


def test_in_function_explains_why_global_lookup_failed():
    """`run_trusted` 取的是全局命名空间，函数内的 result 根本拿不到。"""
    code = "def f(df):\n    result = df['x'].sum()\n    return result\nf(df)"
    assert result_missing(code, executed=True, result=None) == "in_function"


def test_syntax_error_does_not_raise():
    assert result_origin("result = (") == "unparsed"
    assert result_missing("result = (", executed=True, result=None) == "unparsed"


def test_describe_shape_is_stable():
    got = describe(ORD_004_OK, executed=True, result=832.54)
    assert got == {"result_origin": "computed", "result_missing": None}
    assert describe("", executed=True, result=None) == {"result_origin": None, "result_missing": "no_assign"}


# ---------------------------------------------------------------- 拒答形态（缺口 14a）

# 真实样本：outputs/eval_v5_single_run1.json 的 emp_022。
# 首行是标准拒答，后面跟了一整段"离职特征分析"——形态仍是 clean，越界由 refusal_leak 管。
EMP_022_RUN1 = """无法回答：数据中没有记录离职原因（如离职类型/原因调查字段），只能看到离职日期，无法确定员工离职的主要原因。

**说明（可作为线索的离职特征分析，非"原因"结论）**

数据共 240 人，其中 37 人已离职，总体离职率 15.4%；绩效 C 的离职率 22.4%。"""

# 真实样本：outputs/eval_v5_single_run2.json 的 emp_022。
# 意思到了（说了字段不存在），但首行是"结论（含口径说明）"，没有那四个字。
EMP_022_RUN2 = """**结论（含口径说明）**

数据中**没有"离职原因/离职类型"字段**，因此无法给出员工自述的官方离职原因；只能从现有字段推断离职的高风险特征。"""

# 真实样本：outputs/eval_v5_single_run1.json 的 ord_024。
ORD_024 = "无法回答：数据中没有成本字段，无法计算毛利率。"


def test_refusal_shape_clean_needs_prefix_on_first_line():
    assert refusal_shape(ORD_024) == "clean"
    assert refusal_shape("  无法回答：没有这个字段  ") == "clean"
    # 空行不算"第一行"：模型常在前面留一个换行
    assert refusal_shape("\n\n无法回答：没有该字段。") == "clean"


def test_refusal_shape_only_reads_first_line():
    """`clean` 判的是"有没有按格式拒"，不是"有没有乱答"。

    emp_022 run1 首行标准拒答、正文给了 20 多个百分比，14b 判它越界（`refusal_leak`）。
    形态字段若在这里判成 `infer`，两个字段就变成同一个意思了。
    """
    assert refusal_shape(EMP_022_RUN1) == "clean"


def test_refusal_shape_semantic_without_prefix():
    """说了"字段不存在"，但没用规定前缀 —— 缺口 14a 说的就是这一类。"""
    assert refusal_shape(EMP_022_RUN2) == "semantic_no_prefix"
    assert refusal_shape("数据表中只有库存和销量字段，无法计算销售额。") == "semantic_no_prefix"
    assert refusal_shape("该表缺少成本列，无法给出毛利率。") == "semantic_no_prefix"


def test_refusal_shape_infer_and_empty():
    """既没前缀也没拒答语义 = 把题答了；空回答不猜它属于哪一种。"""
    assert refusal_shape("数码品类中销售额最高的是数码商品11，金额 138322.36 元。") == "infer"
    assert refusal_shape("") == "empty"
    assert refusal_shape("   \n  ") == "empty"
    assert refusal_shape(None) is None


def test_refusal_shape_never_raises_on_weird_input():
    assert refusal_shape(12345) == "infer"      # 非字符串也要有答案，不抛


def test_refusal_shape_does_not_touch_code_fingerprint():
    """形态字段必须留在 B 组文件里 —— 这条是被自己踩出来的。

    第一版把它写进 `runner.py`（out 字典加一个键 + return 前算一次），
    `affects_results_sha256` 从 `ac1ebcd66c5a` 变成 `da0af7c3efce`：一行纯记录代码
    让 6 个基线全部失配。挪到报告层现算之后回到 `ac1ebcd66c5a`。

    断言守的是分组：`runner.py` 在 A 组（决定喂给模型什么），`report.py` / `provenance.py`
    在 B 组（只产出报告）。记录字段只能待在 B 组。
    """
    from app.eval.fingerprint import code_fingerprint
    files = code_fingerprint()["files"]
    assert files["app/eval/runner.py"]["group"] == "A"
    for f in ("app/eval/report.py", "app/eval/provenance.py"):
        assert files[f]["group"] == "B", f
