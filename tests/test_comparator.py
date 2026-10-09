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
