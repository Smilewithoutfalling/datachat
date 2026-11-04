"""EV-B4 证据一致性：三条断言 × 正 / 负 / 不适用。

三条断言最容易犯的错不是"没查出来"，是**查错了对象**：
- 断言 1 拿 question 当证据 —— 题面里的数字抄进答案就永真，检查等于没有；
- 断言 2 在 chart_check（B3）落地前装作检查过 —— 恒绿灯比红灯更骗人；
- 断言 3 只看答案措辞 —— "今年销售额 120 万"写得再像样，代码没过滤就是没过滤。
"""
from types import SimpleNamespace

from app.eval.case_model import EvalCase
from app.eval.consistency import check_consistency


def _res(answer="一共 1200 元", result_text="1200", result=1200, code="result = df['units'].sum()",
         executed=True, question="总销售额是多少？", chart_check_codes=None):
    return SimpleNamespace(executed=executed, answer=answer, result=result,
                           result_text=result_text, code=code, question=question,
                           chart_check_codes=chart_check_codes)


def _case(question="总销售额是多少？", expect_refusal=False, expect_kind=""):
    return EvalCase(id="b4_999", category="aggregation", question=question,
                    ground_truth="result = 0", expect_refusal=expect_refusal,
                    expect_kind=expect_kind)


# ---------------------------------------------------------------- 断言 1：答案 ↔ 结果

def test_answer_numbers_found_passes():
    """正：答案里的数字（含千分位写法）能在 result_text 里找到。"""
    r = check_consistency(_res(answer="总销售额为 1,200 元", result_text="1200"), _case())
    assert r["applicable"] and r["failures"] == []


def test_answer_fabricated_number_fails():
    """负：result 里 84 单，答案写 1,061 单（闸门 m06 的真事）。"""
    r = check_consistency(_res(answer="共 1,061 单", result_text="84", result=84), _case())
    assert "ANSWER_RESULT_MISMATCH" in r["failures"]
    assert r["detail"]["answer_nums_missing"] == ["1,061"]


def test_refusal_case_not_applicable():
    """不适用：拒答类题的 answer 是解释文本，数字没有证据可言 —— 不查，也不算通过。"""
    r = check_consistency(_res(answer="无法回答：缺少 300 这个字段"),
                          _case(expect_refusal=True, expect_kind="impossible"))
    assert not r["applicable"] and r["failures"] == []


def test_question_numbers_are_not_evidence():
    """证据不含 question：题面出现过的数抄进答案不算核实（与 service 的口径有意不同）。"""
    r = check_consistency(_res(answer="销售额 500 元", result_text="1200", result=1200,
                               question="500 元以上的订单有多少？"), _case(question="500 元以上的订单有多少？"))
    assert "ANSWER_RESULT_MISMATCH" in r["failures"]


def test_year_in_answer_never_flags():
    """规格陷阱：年份 2011 既是数字又是时间，不许在断言 1 里找茬。"""
    r = check_consistency(_res(answer="2011 年的销售额为 950 元", result_text="950"), _case())
    assert r["failures"] == []


def test_derived_percentage_passes():
    """规格陷阱："增长 12%" 的 12 是算出来的 —— 结果里存在 12 或 0.12 即放行。"""
    r = check_consistency(_res(answer="增长 12%", result_text="0.12", result=0.12), _case())
    assert r["failures"] == []


# ---------------------------------------------------------------- 断言 2：图 ↔ 结果

def test_chart_check_absent_is_not_applicable():
    """B3 未落地时断言 2 恒不适用 —— 不装作检查过（恒绿灯比红灯更骗人）。"""
    r = check_consistency(_res(), _case())
    assert r["applicable"] and "CHART_RESULT_MISMATCH" not in r["failures"]


def test_chart_check_code_maps_to_mismatch():
    """B3 落地后：chart_check 的两个 code 直接映射成 CHART_RESULT_MISMATCH。"""
    r = check_consistency(_res(chart_check_codes=["CHART_BAR_VALUE"]), _case())
    assert "CHART_RESULT_MISMATCH" in r["failures"]
    assert r["detail"]["chart_check_codes"] == ["CHART_BAR_VALUE"]


def test_chart_check_other_codes_ignored():
    """chart_check 将来新增的 code 不归这条断言管（映射范围写死在规格里）。"""
    r = check_consistency(_res(chart_check_codes=["CHART_LEGEND_FUTURE"]), _case())
    assert "CHART_RESULT_MISMATCH" not in r["failures"]


# ---------------------------------------------------------------- 断言 3：时间词 ↔ 代码

def test_time_word_with_filter_passes():
    """正：问"今年"，代码里有年份过滤。"""
    code = "df['date'] = pd.to_datetime(df['date']); d = df[df['date'].dt.year == 2024]; result = int(d['units'].sum())"
    r = check_consistency(_res(code=code, question="今年的销量是多少？"), _case(question="今年的销量是多少？"))
    assert r["failures"] == []


def test_time_word_without_filter_fails():
    """负：问"上季度"，代码没有任何时间过滤形态 —— 只看代码，不看答案写得多像样。"""
    code = "result = int(df[df['region'] == '华东']['units'].sum())"
    r = check_consistency(_res(code=code, question="上季度华东的销量是多少？"),
                          _case(question="上季度华东的销量是多少？"))
    assert "TIME_FILTER_MISMATCH" in r["failures"]
    assert r["detail"]["time_words"] == ["上季度"]


def test_no_time_word_not_checked():
    """不适用：问题里没有时间词，断言 3 不参与 —— 不然 'Q1' 这类正则会误伤普通题。"""
    r = check_consistency(_res(), _case())
    assert "TIME_FILTER_MISMATCH" not in r["failures"]
