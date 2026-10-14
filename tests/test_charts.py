"""M13 第 1 步：build_option（DataFrame → ECharts option）与 validate_spec（白名单）。"""
import copy
import json
import math

import numpy as np
import pandas as pd
import pytest

from app.tools.charts import (BANNED_KEYS, MAX_POINTS, ChartError, build_option, validate_spec)


def _strict_json(spec):
    json.dumps(spec, allow_nan=False, ensure_ascii=False)


# ---------------------------------------------------------------- 基本图型
def test_bar_from_series_uses_index():
    s = pd.Series([41746, 12852, 11635], index=pd.Index(["SP", "RJ", "MG"], name="customer_state"), name="订单数")
    spec = build_option("bar", s, title="各州订单数")
    o = spec["option"]
    assert spec["kind"] == "bar" and spec["truncated"] is False and spec["v"] == 1
    assert o["xAxis"]["data"] == ["SP", "RJ", "MG"] and o["xAxis"]["name"] == "customer_state"
    assert o["series"] == [{"name": "订单数", "type": "bar", "data": [41746, 12852, 11635]}]
    assert o["title"]["text"] == "各州订单数" and o["legend"]["show"] is False
    assert isinstance(o["series"][0]["data"][0], int)     # numpy.int64 → int
    _strict_json(spec)


def test_wide_multi_series_line():
    df = pd.DataFrame({"月": ["1月", "2月"], "收入": [1.5, 2.0], "成本": [1.0, np.nan]})
    o = build_option("line", df, x="月", y=["收入", "成本"])["option"]
    assert [s["name"] for s in o["series"]] == ["收入", "成本"]
    assert o["series"][1]["data"] == [1.0, None]          # NaN → null
    assert o["legend"]["show"] is True and o["yAxis"]["name"] == ""


def test_long_format_series_pivot_keeps_order():
    df = pd.DataFrame({"年": [2023, 2023, 2024, 2024, 2025], "地区": ["南", "北", "北", "南", "南"],
                       "销量": [1, 2, 3, 4, 5]})
    o = build_option("bar", df, x="年", y="销量", series="地区")["option"]
    assert o["xAxis"]["data"] == ["2023", "2024", "2025"]
    assert [(s["name"], s["data"]) for s in o["series"]] == [("南", [1, 4, 5]), ("北", [2, 3, None])]


def test_area_and_time_axis_iso():
    idx = pd.date_range("2024-01-01", periods=3, freq="D", name="日期")
    o = build_option("area", pd.Series([1, 2, 3], index=idx, name="销售额"))["option"]
    assert o["xAxis"]["data"] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert o["series"][0]["areaStyle"] == {} and o["series"][0]["type"] == "line"


def test_pie():
    df = pd.DataFrame({"渠道": ["线上", "线下"], "占比": [0.6, 0.4]})
    o = build_option("pie", df, x="渠道", y="占比")["option"]
    assert o["series"][0]["data"] == [{"name": "线上", "value": 0.6}, {"name": "线下", "value": 0.4}]
    assert o["tooltip"]["trigger"] == "item"


def test_scatter_with_groups_drops_missing_points():
    df = pd.DataFrame({"价格": [1.0, 2.0, 3.0, np.nan], "销量": [10, 20, 30, 40], "类": ["a", "b", "a", "a"]})
    o = build_option("scatter", df, x="价格", y="销量", series="类")["option"]
    assert o["series"][0]["data"] == [[1.0, 10], [3.0, 30]] and o["series"][1]["data"] == [[2.0, 20]]


def test_y_inferred_when_single_numeric_column():
    df = pd.DataFrame({"类": ["a", "b"], "值": [1, 2]})
    assert build_option("bar", df, x="类")["option"]["series"][0]["name"] == "值"


def test_builder_does_not_mutate_input():
    df = pd.DataFrame({"类": ["a", "b"], "值": [1, 2]})
    before = df.copy(deep=True)
    build_option("bar", df, x="类", y="值")
    pd.testing.assert_frame_equal(df, before)


# ---------------------------------------------------------------- 报错（给模型看的中文原因）
@pytest.mark.parametrize("kwargs,frag", [
    (dict(kind="radar"), "不支持的图型"),
    (dict(kind="bar", x="不存在"), "不存在"),
    (dict(kind="bar", x="类", y="类"), "不是数值"),
    (dict(kind="bar", x="类", y=["值", "值2"], series="类"), "二选一"),
    (dict(kind="pie", x="类", y=["值", "值2"]), "饼图"),
    (dict(kind="scatter", x="类", y="值"), "数值列"),
    (dict(kind="bar"), "无法唯一确定"),
])
def test_errors(kwargs, frag):
    df = pd.DataFrame({"类": ["a", "b"], "值": [1, 2], "值2": [3, 4]})
    kind = kwargs.pop("kind")
    with pytest.raises(ChartError, match=frag):
        build_option(kind, df, **kwargs)


def test_long_format_duplicates_rejected():
    df = pd.DataFrame({"x": ["a", "a"], "s": ["u", "u"], "y": [1, 2]})
    with pytest.raises(ChartError, match="groupby"):
        build_option("bar", df, x="x", y="y", series="s")


def test_negative_pie_rejected():
    with pytest.raises(ChartError, match="负"):
        build_option("pie", pd.Series([1, -1], index=["a", "b"]))


def test_empty_rejected():
    with pytest.raises(ChartError, match="空"):
        build_option("bar", pd.DataFrame({"a": [], "b": []}), x="a", y="b")


def test_non_dataframe_rejected():
    with pytest.raises(ChartError, match="DataFrame"):
        build_option("bar", [1, 2, 3])


# ---------------------------------------------------------------- 限量与清洗
def test_truncation_flag_and_cap():
    n = MAX_POINTS + 10
    df = pd.DataFrame({"x": range(n), "a": range(n), "b": range(n)})
    spec = build_option("line", df, x="x", y=["a", "b"])
    assert spec["truncated"] is True
    assert sum(len(s["data"]) for s in spec["option"]["series"]) <= MAX_POINTS


def test_control_chars_and_length_cleaned():
    s = pd.Series([1], index=["a\x00b\u2028c"], name="n" * 500)
    spec = build_option("bar", s, title="t\x07" + "x" * 500)
    o = spec["option"]
    assert o["xAxis"]["data"] == ["a b c"]
    assert len(o["title"]["text"]) <= 100 and "\x07" not in o["title"]["text"]
    assert len(o["series"][0]["name"]) <= 100


def test_html_payload_is_kept_as_plain_text_not_rejected():
    # 字符串照原样当纯文本（canvas 渲染 + 前端 tooltip richText，见 THREAT_MODEL）；builder 不做 HTML 转义，避免双重转义
    s = pd.Series([1], index=["<img src=x onerror=alert(1)>"], name="v")
    spec = build_option("bar", s)
    assert spec["option"]["xAxis"]["data"] == ["<img src=x onerror=alert(1)>"]
    assert validate_spec(spec) == []


def test_inf_becomes_null():
    o = build_option("bar", pd.Series([1.0, math.inf, -math.inf], index=list("abc")))["option"]
    assert o["series"][0]["data"] == [1.0, None, None]


# ---------------------------------------------------------------- 白名单
def _ok_spec():
    return build_option("bar", pd.Series([1, 2], index=["a", "b"], name="v"), title="t")


def test_builder_output_passes_validation():
    for kind, data in [("bar", None), ("line", None), ("area", None), ("pie", None)]:
        assert validate_spec(build_option(kind, pd.Series([1, 2], index=["a", "b"]))) == []
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [3, 4]})
    assert validate_spec(build_option("scatter", df, x="x", y="y")) == []


@pytest.mark.parametrize("mutate,frag", [
    (lambda o: o["title"].__setitem__("link", "javascript:alert(1)"), "禁用键"),
    (lambda o: o["title"].__setitem__("sublink", "x"), "禁用键"),
    (lambda o: o.__setitem__("graphic", [{"type": "text"}]), "禁用键"),
    (lambda o: o.__setitem__("dataset", {"source": [[1, 2]]}), "禁用键"),
    (lambda o: o["tooltip"].__setitem__("formatter", "{b}<img>"), "禁用键"),
    (lambda o: o["tooltip"].__setitem__("renderMode", "html"), "禁用键"),
    (lambda o: o.__setitem__("aria", {"enabled": True}), "禁用键"),
    (lambda o: o.__setitem__("toolbox", {"feature": {"dataView": {}}}), "禁用键"),
    (lambda o: o["series"][0].__setitem__("label", {"show": True, "formatter": "{c}"}), "禁用键"),
    (lambda o: o.__setitem__("visualMap", {"pieces": []}), "不在白名单"),
    (lambda o: o["yAxis"].__setitem__("min", 0), "不在白名单"),
    (lambda o: o["series"][0].__setitem__("data", [1, "2"]), "数值或 null"),
    (lambda o: o["series"][0].__setitem__("data", [1]), "长度"),
    (lambda o: o["series"][0].__setitem__("type", "custom"), "不允许"),
    (lambda o: o.__setitem__("color", ["red"]), "#RRGGBB"),
    (lambda o: o["title"].__setitem__("text", "a\x00b"), "控制字符"),
    (lambda o: o["legend"].__setitem__("show", "yes"), "类型应为"),
    (lambda o: o["series"][0].__setitem__("data", [float("nan"), 1]), "数值或 null"),
])
def test_validation_rejects(mutate, frag):
    spec = copy.deepcopy(_ok_spec())
    mutate(spec["option"])
    problems = validate_spec(spec)
    assert problems and any(frag in p for p in problems), problems


def test_validation_rejects_callable_and_bad_envelope():
    spec = copy.deepcopy(_ok_spec())
    spec["option"]["title"]["text"] = lambda: 1
    assert validate_spec(spec)
    assert validate_spec({"option": {}}) == ["spec 结构应为 {v, kind, truncated, option}"]
    spec = copy.deepcopy(_ok_spec())
    spec["option"]["series"] = []
    assert any("非空" in p for p in validate_spec(spec))


def test_too_many_points_rejected():
    spec = copy.deepcopy(_ok_spec())
    n = MAX_POINTS + 1
    spec["option"]["xAxis"]["data"] = ["c"] * n
    spec["option"]["series"][0]["data"] = [1] * n
    assert any("上限" in p for p in validate_spec(spec))


def test_banned_keys_cover_dom_channels():
    assert {"link", "sublink", "graphic", "formatter", "dataset", "aria", "toolbox", "renderMode"} <= BANNED_KEYS
