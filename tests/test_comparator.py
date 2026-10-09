import pandas as pd
import pytest

from app.eval.comparator import results_equal


def test_scalars_with_tolerance():
    assert results_equal(1.00001, 1.0)
    assert not results_equal(1.1, 1.0)


def test_series_same_mapping_any_order():
    a = pd.Series([1, 2], index=["a", "b"])
    b = pd.Series([2, 1], index=["b", "a"])
    assert results_equal(a, b)


def test_series_different_mapping():
    a = pd.Series([3, 2, 1], index=["x", "y", "z"])
    b = pd.Series([3, 2, 1], index=["z", "y", "x"])
    assert not results_equal(a, b)


def test_none_handling():
    assert results_equal(None, None)
    assert not results_equal(None, 1)


@pytest.mark.xfail(raises=AssertionError, reason="B12: 比较忽略顺序，Top-N 排序错误仍判对")
def test_ranked_list_order_matters():
    expected = pd.Series([300, 200, 100], index=["华东", "华南", "华北"])
    wrong_order = pd.Series([100, 200, 300], index=["华北", "华南", "华东"])
    assert not results_equal(wrong_order, expected)
