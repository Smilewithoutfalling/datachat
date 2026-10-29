import math

import numpy as np
import pandas as pd

from app.eval.comparator import looks_ranked, results_equal


def test_scalars_with_tolerance():
    assert results_equal(1.00001, 1.0)
    assert not results_equal(1.1, 1.0)


def test_series_same_mapping_any_order():
    # 期望是自然（groupby）顺序时，不比较顺序
    a = pd.Series([2, 1], index=["b", "a"])
    b = pd.Series([1, 2], index=["a", "b"])
    assert results_equal(a, b)


def test_series_different_mapping():
    a = pd.Series([3, 2, 1], index=["x", "y", "z"])
    b = pd.Series([3, 2, 1], index=["z", "y", "x"])
    assert not results_equal(a, b)


def test_none_handling():
    assert results_equal(None, None)
    assert not results_equal(None, 1)


def test_ranked_list_order_matters():
    """B12：期望是排过序的结果时，顺序错误判错（不再虚高）。"""
    expected = pd.Series([300, 200, 100], index=["华东", "华南", "华北"])
    wrong_order = pd.Series([100, 200, 300], index=["华北", "华南", "华东"])
    assert not results_equal(wrong_order, expected)


def test_explicit_ordered_flag_overrides_inference():
    expected = pd.Series([300, 200, 100], index=["华东", "华南", "华北"])
    shuffled = pd.Series([100, 300, 200], index=["华北", "华东", "华南"])
    assert results_equal(shuffled, expected, ordered=False)
    natural = pd.Series([1, 2], index=["a", "b"])
    assert not results_equal(natural[::-1], natural, ordered=True)


def test_looks_ranked():
    assert looks_ranked(pd.Series([3, 1, 2], index=["b", "a", "c"]))
    assert not looks_ranked(pd.Series([3, 1, 2], index=["a", "b", "c"]))
    assert not looks_ranked(5)


def test_nan_equals_nan_and_numpy_scalars():
    assert results_equal(float("nan"), math.nan)
    assert results_equal(np.int64(3), 3)
    assert results_equal(np.float64(2.5), 2.5)


def test_rounded_expected_tolerates_unrounded_actual():
    assert results_equal(35.1234, 35.12)
    assert not results_equal(35.13, 35.12)


def test_label_answer_forms():
    assert results_equal(("华东", 12345.0), "华东")
    assert results_equal(pd.Series([12345.0], index=["华东"]), "华东")
    assert not results_equal(("华东", "华北"), "华东")   # 两个标签：不是"标签+数值"
    assert not results_equal(["华东", "华北", "华南"], "华东")


def test_dataframe_superset_columns_and_reset_index():
    e = pd.DataFrame({"a": [1, 2]}, index=[5, 9])
    a = pd.DataFrame({"a": [1, 2], "extra": [0, 0]})
    assert results_equal(a, e)
    # 阶段 1.5（B24 规则 8）：列名不同但值相同 → 按值匹配判对；值不同仍判错
    assert results_equal(pd.DataFrame({"b": [1, 2]}), e)
    assert not results_equal(pd.DataFrame({"b": [1, 3]}), e)


def test_dataframe_order_when_ordered():
    e = pd.DataFrame({"a": [2, 1]})
    assert results_equal(pd.DataFrame({"a": [1, 2]}), e, ordered=False)
    assert not results_equal(pd.DataFrame({"a": [1, 2]}), e, ordered=True)


def test_month_labels_equivalent():
    e = pd.Series([1, 2], index=pd.to_datetime(["2024-01-31", "2024-02-29"]))
    assert results_equal(pd.Series([1, 2], index=pd.PeriodIndex(["2024-01", "2024-02"], freq="M")), e)
    assert results_equal(pd.Series([1, 2], index=["2024-01", "2024-02"]), e)
    assert not results_equal(pd.Series([2, 1], index=["2024-01", "2024-02"]), e)


# ---- 阶段 1.5 第二轮（B29）：规则 13–17 ----
def test_rule13_row_series_vs_one_row_frame():
    e = pd.DataFrame({"date": ["2024-03-12"], "region": ["华北"], "product": ["E"], "units": [18]}, index=[44])
    row = pd.Series({"date": "2024-03-12", "region": "华北", "product": "E", "units": 18, "price": 155.0}, name=44)
    assert results_equal(row, e)
    assert not results_equal(row.replace({18: 19}), e)


def test_rule14_month_number_index():
    e = pd.Series([10.0, 20.0], index=pd.Index([1, 2], name="date"))
    assert results_equal(pd.Series([10.0, 20.0], index=["2024-01", "2024-02"]), e)
    assert not results_equal(pd.Series([20.0, 10.0], index=["2024-01", "2024-02"]), e)
    ef = pd.DataFrame({"华东": [1.0, 2.0], "华北": [3.0, 4.0]}, index=pd.Index([1, 2], name="date"))
    af = pd.DataFrame({"华东": [1.0, 2.0], "华北": [3.0, 4.0]}, index=pd.Index(["2024-01", "2024-02"], name="month"))
    assert results_equal(af, ef)
    assert not results_equal(af * 2, ef)


def test_rule15_iso_week_labels():
    e = pd.Series([120, 380], index=pd.to_datetime(["2024-01-07", "2024-01-14"]))
    assert results_equal(pd.Series([120, 380], index=["2024-W01", "2024-W02"]), e)
    assert not results_equal(pd.Series([380, 120], index=["2024-W01", "2024-W02"]), e)
    assert results_equal(pd.Series([120, 380], index=["2024-W01 (01-01)", "2024-W02（01-08）"]), e)   # B51
    assert not results_equal(pd.Series([120, 380], index=["2024-W01 x", "2024-W02 y"]), e)


def test_rule16_named_summary_dict():
    assert results_equal({"1月销量": 952, "3月销量": 714, "增长量": -238, "增长率%": -25.0}, -238)
    assert not results_equal({"1月销量": 952, "3月销量": 714, "增长量": -200, "增长率%": -25.0}, -238)
    d = {"最高月份": "2024-06", "最高销售额": 54406.5, "最低月份": "2024-02", "最低销售额": 36640.0}
    assert results_equal(d, ("2024-06", "2024-02"))
    assert not results_equal(d, ("2024-02", "2024-06"))
    # 5 项（像按地区汇总的整张表）仍不适用
    assert not results_equal({"华东": 1, "华北": 2, "华南": 3, "华中": 4, "西南": 5}, 3)


def test_rule17_margins_dropped():
    e = pd.DataFrame({"A": [1, 2], "B": [3, 4]}, index=pd.Index(["华东", "华北"], name="region"))
    a = pd.DataFrame({"A": [1, 2, 3], "B": [3, 4, 7], "总计": [4, 6, 10]},
                     index=pd.Index(["华东", "华北", "总计"], name="region"))
    assert results_equal(a, e)
    assert not results_equal(a.replace({1: 9}), e)


def test_rule18_quarter_labels():
    e = pd.Series([377358.66, 473495.5], index=pd.Index([1, 2], name="order_date"))
    for a in (pd.Series([377358.66, 473495.5], index=pd.PeriodIndex(["2024Q1", "2024Q2"], freq="Q")),
              {"第一季度": 377358.66, "第二季度": 473495.5}, {"Q1": 377358.66, "Q2": 473495.5},
              (377358.66, 473495.5)):
        assert results_equal(a, e), a
    assert not results_equal((473495.5, 377358.66), e)
    assert not results_equal({"第一季度": 473495.5, "第二季度": 377358.66}, e)


def test_rule18_month_numbers_vs_time_index():
    e = pd.Series([10.0, 20.0, 30.0], index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    assert results_equal(pd.Series([10.0, 20.0, 30.0], index=[1, 2, 3]), e)
    assert not results_equal(pd.Series([10.0, 30.0, 20.0], index=[1, 2, 3]), e)
    # 跨年的时间索引不能只按月份号对齐
    e2 = pd.Series([1.0, 2.0], index=pd.to_datetime(["2023-12-31", "2024-12-31"]))
    assert not results_equal(pd.Series([1.0, 2.0], index=[12, 12]), e2)


def test_rule18_iso_week_numbers():
    e = pd.Series([1070, 2258, 2108], index=pd.to_datetime(["2024-03-03", "2024-03-10", "2024-03-17"]))
    assert results_equal(pd.Series([1070, 2258, 2108], index=pd.Index([9, 10, 11], name="week")), e)
    assert not results_equal(pd.Series([1070, 2108, 2258], index=[9, 10, 11]), e)
    assert not results_equal(pd.Series([1070, 2258, 2108], index=[11, 10, 9]), e)    # 不是递增的周序号


def test_refusal_detection():
    from app.eval.comparator import is_refusal
    assert is_refusal("无法回答：数据中没有成本字段")
    assert is_refusal("  无法回答，表里没有年龄 ")
    assert not is_refusal("无法回答")
    assert not is_refusal("无法回答：")
    assert not is_refusal("数据中没有成本字段")
    assert not is_refusal(None) and not is_refusal(0)


# ---------------------------------------------------------------- 规则 19（阶段 3b，B41）
def test_rule19_percent_string_scalar():
    assert results_equal("7.00%", 7.0)
    assert results_equal("45.81%", 45.81)
    assert not results_equal("45.8%", 45.81)
    assert not results_equal("7.00%", 0.5)


def test_rule19_percent_strings_in_series_and_dict():
    idx = ["APP", "小程序", "网页"]
    assert results_equal(pd.Series(["50.58%", "34.58%", "14.83%"], index=idx),
                         pd.Series([50.58, 34.58, 14.83], index=idx))
    assert results_equal({"总订单数": 1200, "已退款订单数": 84, "退款率": "7.00%"}, 7.0)


def test_rule19_dict_with_embedded_quarter_keys():
    e = pd.Series([131210.0, 143463.5], index=pd.Index([1, 2], name="quarter"))
    assert results_equal({"第一季度销售总额": 131210.0, "第二季度销售总额": 143463.5, "哪个季度更高": "第二季度"}, e)
    assert results_equal({"2024年Q1": 131210.0, "2024年Q2": 143463.5}, e)
    assert not results_equal({"第一季度": 143463.5, "第二季度": 131210.0}, e)   # 对错季度
    assert not results_equal({"华东": 131210.0, "华南": 143463.5}, e)          # 键里没有季度


def test_rule19_dict_with_embedded_month_keys():
    e = pd.Series([34, 21, 5], index=pd.Index([3, 4, 5], name="date"))
    assert results_equal({"3月": 34, "4月": 21, "5月": 5}, e)
    assert not results_equal({"3月": 21, "4月": 34, "5月": 5}, e)


def test_refusal_from_answer():
    from app.core.result import refusal_from_answer
    assert refusal_from_answer("无法回答：数据中没有店长字段。\n更多说明") == "无法回答：数据中没有店长字段。"
    assert refusal_from_answer("**无法回答：没有供应商字段**") == "无法回答：没有供应商字段"
    assert refusal_from_answer("无法直接回答，因为没有成本字段") is None
    assert refusal_from_answer("无法回答") is None
    assert refusal_from_answer("我无法回答：数据中没有价格字段。") == "无法回答：数据中没有价格字段。"   # B49
    assert refusal_from_answer("我认为无法回答：没有价格") is None
    assert refusal_from_answer(None) is None


def test_rule19_rank_numbers_vs_values():
    e = pd.Series([13757.5, 10721.5, 4760.0, 4550.0, 4270.0], index=pd.Index(list("BEACD"), name="product"))
    assert results_equal(pd.Series([1, 2, 3, 4, 5], index=list("BEACD")), e)
    assert results_equal(pd.Series([3, 1, 2, 4, 5], index=list("ABECD")), e)
    assert not results_equal(pd.Series([1, 2, 3, 4, 5], index=list("EBACD")), e)
    assert not results_equal(pd.Series([1, 2, 3], index=list("BEA")), e)


# ---- 规则 20（B46）：答案外面裹了附加信息
def test_rule20_label_vs_sorted_series():
    s = pd.Series([153906.21, 152786.38, 96935.99], index=pd.Index(["杭州", "上海", "武汉"], name="city"))
    assert results_equal(s, "杭州")
    assert results_equal(s.sort_values(), "武汉")                       # 升序时榜首是最小值
    assert not results_equal(s, "上海")
    assert not results_equal(s.sort_index(), "杭州")                    # 没按值排序：看不出答案
    assert not results_equal(pd.Series([5.0, 5.0, 1.0], index=["甲", "乙", "丙"]), "甲")   # 榜首并列


def test_rule20_scalar_inside_dict():
    a = {"2023年内离职人数": 14, "2023-01-01在职人数": 183, "流失率(%)": 7.65}
    assert results_equal(a, 7.65)
    assert not results_equal(a, 7.5)
    # B50：两种口径算出同一个值（≤4 项的 dict 归规则 10 管，这里用 5 项）
    assert results_equal({"甲项指标值": 7.65, "乙项指标值": 7.65, "丙项指标值": 1, "丁项指标值": 2, "戊项指标值": 3}, 7.65)
    assert results_equal({'原始行数': 1218, 'order_id唯一数': 1200, '整行去重后行数': 1200, 'order_id去重后行数': 1200,
                          '整行去重_符合条件': 40, 'order_id去重_符合条件': 40}, 40)
    assert results_equal({"甲项指标值": 7.65, "乙项指标值": 7.7, "丙项指标值": 1, "丁项指标值": 2, "戊项指标值": 3}, 7.65)
    assert not results_equal({"2024-01": 1.0, "2024-02": 7.65, "2024-03": 3.0}, 7.65)  # 时间序列
    assert not results_equal({f"k{i}": i for i in range(9)} | {"x": 7.65}, 7.65)  # 太多项
    # 嵌套的多种口径不算对
    hedged = {"口径A": {"复购率": "73.15%"}, "口径B": {"复购率": "75.46%"}}
    assert not results_equal(hedged, 75.46)


def test_rule20_label_inside_dict():
    a = {"top_day": "2024-05-04", "top_sold": 579, "top5": {"2024-05-04": 579, "2024-05-05": 560}}
    assert results_equal(a, "2024-05-04")
    assert results_equal({"总销量最高的SKU": "K100", "总销量": 14769}, "K100")
    assert not results_equal({"按销售额最好": "数码", "按销量最好": "服饰", "x": 1}, "数码")   # 两个标签


def test_rule20_series_inside_dict():
    e = pd.Series([545, 500, 299], index=pd.Index(["S01", "S02", "S05"], name="store"))
    assert results_equal({"各门店期末库存": e.copy(), "合计": 1344}, e)
    assert results_equal({"总行数": 1218, "各店": {"S01": 545, "S02": 500, "S05": 299},
                          "分布": {"a": 1, "b": 2}}, e)
    assert not results_equal({"各店": {"S01": 545, "S02": 501, "S05": 299}, "合计": 1345}, e)


def test_rule20_dict_keys_contain_labels():
    e = pd.Series([19.72, 14.85], index=pd.Index(["周末", "工作日"], name="date"))
    assert results_equal({"工作日平均销量": 14.85, "周末平均销量": 19.72, "工作日记录数": 1320, "周末记录数": 520}, e)
    assert not results_equal({"工作日平均销量": 19.72, "周末平均销量": 14.85}, e)
    assert not results_equal({"工作日平均": 14.85, "周末平均": 19.72, "周末均值": 19.72}, e)   # 一个标签对应两个键


def test_rule20_sentence_string():
    assert results_equal("退款率 7.00%（已退款 84 / 去重订单 1200）", 7.0)
    assert results_equal("共 1,200 单", 1200)
    assert not results_equal("7.00% 或 7.5%", 7.0)
    assert not results_equal("已退款 84 / 去重订单 1200", 84)


# ---- 规则 22（eval-v0 基线暴露）：中文月份写法
def test_rule22_bare_chinese_month_index():
    """inv_020 的现场：数值全对，只是索引写成 '3月' 而不是 3。

    _MONTH_RE 只认 'YYYY-MM'，所以 34/21/5 这么一组完全正确的答案被判错。
    补的是"同一件事的另一种写法"，不是放宽标准。
    """
    e = pd.Series([34, 21, 5], index=[3, 4, 5])
    assert results_equal(pd.Series([34, 21, 5], index=["3月", "4月", "5月"]), e)
    assert results_equal(pd.Series([34, 21, 5], index=["03月", "04月", "05月"]), e)
    assert results_equal(pd.Series([34, 21, 5], index=["3月份", "4月份", "5月份"]), e)
    # 数值错一位仍然判错：只改了标签的认法，没改数值的比较
    assert not results_equal(pd.Series([34, 21, 6], index=["3月", "4月", "5月"]), e)
    # 月份对不上就是错，不能因为"都是中文月份"就放过
    assert not results_equal(pd.Series([34, 21, 5], index=["4月", "5月", "6月"]), e)


def test_rule22_year_month_chinese():
    """'2024年3月' 与 '2024-03' 是同一个月，两种写法都要认。"""
    e = pd.Series([34, 21, 5], index=[3, 4, 5])
    assert results_equal(pd.Series([34, 21, 5], index=["2024年3月", "2024年4月", "2024年5月"]), e)
    assert results_equal(pd.Series([34, 21, 5], index=["2024年3月份", "2024年4月份", "2024年5月份"]), e)
    assert results_equal("2024年3月", "2024-03")
    assert results_equal(pd.Period("2024-03", freq="M"), "2024年3月")
    assert not results_equal("2024年3月", "2024-04")


def test_rule22_illegal_month_not_accepted():
    """13 月不存在。正则不放宽到任意数字，否则 '13月' 会被当成月份号 13。

    注意只断言"月份号解析"这一层：`results_equal('13月', 13)` 在改动前就是 True，
    那是规则 20 的文本取数（句子里有 13），与本条无关，不要混在一起读。
    """
    from app.eval.comparator import _period_part
    assert _period_part("13月", 12) is None
    assert _period_part("月", 12) is None
    e = pd.Series([34, 21, 5], index=[13, 14, 15])
    assert not results_equal(pd.Series([34, 21, 5], index=["13月", "14月", "15月"]), e)
    # 带别的量词不能被误认成月份
    assert _period_part("3个月", 12) is None


# ---- 规则 23（eval-v1 基线暴露）：日期索引写成 'MM-DD'
_WEEKS_END = ["2024-03-03", "2024-03-10", "2024-03-17", "2024-03-24", "2024-03-31",
              "2024-04-07", "2024-04-14", "2024-04-21", "2024-04-28", "2024-05-05",
              "2024-05-12", "2024-05-19", "2024-05-26", "2024-06-02"]
_WEEKS_START = ["02-26", "03-04", "03-11", "03-18", "03-25",
                "04-01", "04-08", "04-15", "04-22", "04-29",
                "05-06", "05-13", "05-20", "05-27"]
_WEEK_VALS = [1070, 2258, 2108, 2086, 2205, 2275, 2127, 2222, 2215, 2994, 2343, 2257, 2213, 1483]


def test_rule23_month_day_index_is_time_index():
    """inv_016 的现场：按自然周汇总，14 个数值逐个相同，只有索引写法不同。

    期望给周结束日 '2024-03-03'（W-SUN），模型给周起始日 '02-26'（周一）——
    同一周的两种端点说法。数值序列逐位相同，判成错是冤枉。

    根因在 `_is_time_index`：它靠 `_month_key` 判断，而 `_month_key` 只认
    'YYYY-MM' / 'YYYY-MM-DD' / 中文月份，'02-26' 一律 None，于是整组索引被判"非时间索引"，
    `_series_eq` 跳过"两边都是时间索引"那一整段——连它末尾的按位置比较也一起跳过了，
    落到 `_month_numbers` / `_quarter_numbers` 也全失败。

    这属于实现遗漏而非设计分歧：那段注释本来就写着"周/日频等无法按月对齐时，按位置比较数值"，
    只是裸 'MM-DD' 进不了这个分支。

    代价要说清楚：放行的是"按位置比数值"，所以"数值全对但标签错位"也会判对。
    这不是新开的口子——周频从来恢复不出年份，原来的 fallback 就有这个性质，现在只是
    让它对裸月日生效。标签错位的月份数据不会因此被放过：'2024-01' 这类能被 `_month_key`
    认出的索引照旧走明确的月份对齐。
    """
    e = pd.Series(_WEEK_VALS, index=_WEEKS_END)
    assert results_equal(pd.Series(_WEEK_VALS, index=_WEEKS_START), e)
    # 'MM/DD'、'YYYY/MM/DD' 是同一天的不同写法，一并认
    assert results_equal(pd.Series(_WEEK_VALS, index=[s.replace("-", "/") for s in _WEEKS_START]), e)
    assert results_equal(pd.Series(_WEEK_VALS, index=["2024/" + s for s in _WEEKS_START]), e)


def test_rule23_wrong_value_still_fails():
    """只改了标签认法，数值比较一个字节没动。"""
    e = pd.Series(_WEEK_VALS, index=_WEEKS_END)
    bad = list(_WEEK_VALS)
    bad[3] += 1
    assert not results_equal(pd.Series(bad, index=_WEEKS_START), e)


def test_rule23_reordered_still_fails():
    """按位置比要求同位置数值相等，不是"集合相同"。顺序颠倒必须判错。"""
    e = pd.Series(_WEEK_VALS, index=_WEEKS_END)
    assert not results_equal(pd.Series(_WEEK_VALS[::-1], index=_WEEKS_START[::-1]), e)


def test_rule23_non_date_labels_stay_non_time():
    """不能因为放宽就把任意字符串索引当成时间。'A1'/'B2' 这种必须仍是非时间索引。"""
    from app.eval.comparator import _is_time_index
    assert not _is_time_index(pd.Index(["A1", "B2"]))
    assert not _is_time_index(pd.Index(["02-26", "B2"]))     # 混进一个非日期，整组不认
    assert _is_time_index(pd.Index(_WEEKS_START))
    # 越界的"月-日"不是日期：13-01 / 02-32
    assert not _is_time_index(pd.Index(["13-01", "13-02"]))
    assert not _is_time_index(pd.Index(["02-32", "02-33"]))


def test_rule18_quarter_label_with_year_word():
    """'2024年Q1' 与季度序号 1 是同一个季度。

    现场是 ord_022：三次运行数值逐个相同，只有 run3 把索引写成 '2024年Q1'，
    旧正则 `^(?:\\d{4})?\\s*Q([1-4])$` 不认中间那个「年」字，整段对齐没进去。
    """
    e = pd.Series([377358.66, 473495.5], index=[1, 2])
    assert results_equal(pd.Series([377358.66, 473495.5], index=["2024年Q1", "2024年Q2"]), e)
    assert results_equal(pd.Series([377358.66, 473495.5], index=["2024 Q1", "2024 Q2"]), e)
    # 数值对不上仍然判错，只放宽标签写法
    assert not results_equal(pd.Series([377358.66, 1.0], index=["2024年Q1", "2024年Q2"]), e)
    # 季度换了也不认
    assert not results_equal(pd.Series([377358.66, 473495.5], index=["2024年Q1", "2024年Q3"]), e)


def test_extras_frame_one_sorted_column_answers_the_question():
    """答案裹在多列表格里：某一数值列单调、首行标签就是期望值。

    现场是 ord_018：同一份 groupby 结果，少给两列（只剩 rate 的 Series）判对，
    多给 orders / refunded 就判错——差别只在裹了几层，不在答案。
    """
    e = "美妆"
    wide = pd.DataFrame({"orders": [202, 302, 234, 316, 146],
                         "refunded": [21, 22, 16, 18, 7],
                         "rate": [10.40, 7.28, 6.84, 5.70, 4.79]},
                        index=["美妆", "食品", "家居", "服饰", "数码"])
    assert results_equal(wide, e)
    # 标签在列里、index 是 RangeIndex 的形态（同一次运行就是这种）
    by_col = wide.reset_index().rename(columns={"index": "category"})
    assert results_equal(by_col, e)
    # 首行不是期望值：不认
    assert not results_equal(wide.sort_values("rate"), e)
    # 数值列不单调：不认（说明没按这一列排序，首行不构成答案）
    noise = wide.copy()
    noise["rate"] = [1.0, 9.0, 2.0, 8.0, 3.0]
    noise["orders"] = [5, 1, 4, 2, 3]
    noise["refunded"] = [3, 1, 5, 2, 4]
    assert not results_equal(noise, e)


def test_extras_frame_does_not_swallow_grouped_tables():
    """规则 10 的老边界：分组汇总表碰巧含期望值不算对。

    新增的表格分支只在「首行标签 == 期望值」时成立，整张表里某处出现期望值不算。
    """
    e = "美妆"
    tbl = pd.DataFrame({"rate": [7.28, 6.84, 5.70, 4.79, 10.40]},
                       index=["食品", "家居", "服饰", "数码", "美妆"])
    assert not results_equal(tbl, e)          # 首行是食品，美妆在最末行
