"""EV-B3 chart_check（app/core/chart_check.py）单测。

口径：一张图判通过只需命中值匹配 / 系列和 / 总和之一；三条路全断才记 code。
散点、matplotlib PNG（无 option）、无数值 → 不判。
"""
import pandas as pd

from app.core.chart_check import chart_check
from app.core.result import AnalysisResult
from app.eval.consistency import check_consistency


def _res(**kw) -> AnalysisResult:
    base = dict(agent="react", dataset="x.csv", question="q", executed=True,
                result=None, result_text="", charts=[])
    base.update(kw)
    return AnalysisResult(**base)


def _bar(vals, name="销量"):
    return {"option": {"series": [{"name": name, "type": "bar", "data": vals}]}}


def _pie(items, name="占比"):
    return {"option": {"series": [{"name": name, "type": "pie",
                                   "data": [{"name": k, "value": v} for k, v in items]}]}}


# ---- 通过路径 ----

def test_bar_values_in_evidence_pass():
    r = _res(result_text="华东 15091 / 华南 12000", result=pd.Series({"华东": 15091, "华南": 12000}),
             charts=[_bar([15091.0, 12000.0])])
    assert chart_check(r) == []


def test_breakdown_chart_with_total_result_passes_via_sum():
    """明细拆解图 + 合计 result：每项都不等于合计，但总和等于——正当组合，不许误报。"""
    r = _res(result_text="", result=288407, charts=[_bar([15091.0, 273316.0])])
    assert chart_check(r) == []


def test_per_series_sum_route():
    """多系列柱图：单值都不在证据里，但第二个系列的和（=合计）在。"""
    opt = {"option": {"series": [
        {"name": "A", "type": "bar", "data": [100.0, 200.0]},
        {"name": "B", "type": "bar", "data": [300.0, 400.0]}]}}
    r = _res(result_text="", result=700.0, charts=[opt])
    assert chart_check(r) == []


def test_pie_share_values_pass_via_percent_duality():
    """扇区值是份额（0.2493），证据打印成 24.93 —— 比例↔百分数双向容差要接住。"""
    r = _res(result_text="占比：A 24.93%，B 75.07%", result=None,
             charts=[_pie([("A", 0.2493), ("B", 0.7507)])])
    assert chart_check(r) == []


# ---- 失败路径 ----

def test_bar_from_wrong_filter_flagged():
    """图用了没过滤的 df：值不在证据、和也对不上 → CHART_BAR_VALUE。"""
    r = _res(result_text="", result=288407, charts=[_bar([274673.0, 999.0])])
    assert chart_check(r) == ["CHART_BAR_VALUE"]


def test_pie_all_routes_broken_flagged():
    r = _res(result_text="", result=500.0, charts=[_pie([("A", 120.0), ("B", 130.0)])])
    assert chart_check(r) == ["CHART_PIE_SUM"]


def test_codes_deduped():
    r = _res(result_text="", result=500.0,
             charts=[_bar([1.0, 2.0]), _bar([3.0, 4.0])])
    assert chart_check(r) == ["CHART_BAR_VALUE"]


# ---- 不判路径（N.A. 语义：没检查不装作检查过）----

def test_scatter_not_checked():
    opt = {"option": {"series": [{"name": "x", "type": "scatter", "data": [[1, 2], [3, 4]]}]}}
    r = _res(result_text="", result=999.0, charts=[opt])
    assert chart_check(r) == []


def test_matplotlib_png_not_checked():
    r = _res(result_text="", result=999.0, charts=[{"png": "c.png", "option": None}])
    assert chart_check(r) == []


def test_no_numeric_values_not_checked():
    r = _res(result_text="", result=999.0, charts=[_bar([]), _pie([("A", None)])])
    assert chart_check(r) == []


def test_not_executed_no_codes():
    r = _res(executed=False, result_text="", result=1.0, charts=[_bar([1.0, 999.0])])
    assert chart_check(r) == []


# ---- 契约联动 ----

def test_analysis_result_has_default_field():
    assert AnalysisResult(agent="r", dataset="d", question="q").chart_check_codes == []


def test_consistency_assertion2_fires_on_codes():
    """B4 断言 2：codes 里有约定 code → evidence 失败列表出现 CHART_RESULT_MISMATCH。"""
    r = _res(answer="结论", result_text="", result=288407, charts=[_bar([274673.0, 999.0])])
    r.chart_check_codes = chart_check(r)      # 生产接线在 service；这里复现同一赋值
    out = check_consistency(r, type("C", (), {"expect_refusal": False, "expect_kind": ""})())
    assert "CHART_RESULT_MISMATCH" in out["failures"]
    assert out["detail"]["chart_check_codes"] == ["CHART_BAR_VALUE"]
