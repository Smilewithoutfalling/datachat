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
    assert not results_equal(pd.DataFrame({"b": [1, 2]}), e)


def test_dataframe_order_when_ordered():
    e = pd.DataFrame({"a": [2, 1]})
    assert results_equal(pd.DataFrame({"a": [1, 2]}), e, ordered=False)
    assert not results_equal(pd.DataFrame({"a": [1, 2]}), e, ordered=True)


def test_month_labels_equivalent():
    e = pd.Series([1, 2], index=pd.to_datetime(["2024-01-31", "2024-02-29"]))
    assert results_equal(pd.Series([1, 2], index=pd.PeriodIndex(["2024-01", "2024-02"], freq="M")), e)
    assert results_equal(pd.Series([1, 2], index=["2024-01", "2024-02"]), e)
    assert not results_equal(pd.Series([2, 1], index=["2024-01", "2024-02"]), e)
