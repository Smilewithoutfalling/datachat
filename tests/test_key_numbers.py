"""阶段 7.6 U3-2：结果卡的关键数字（app/server/key_numbers.py，docs/roadmap/phase76-u3u5.md §1.2 / §1.3）。

① §1.2 原型表 5 行当期望；② 每个产出的 value 都在结论原文里、且按 grounding 规则能在 str(r.result) 里核到（所有用例统一断言）；
③ clarify / 未执行 / 拒答 / 出错 / 多行 DataFrame 不产出；④ TestClient 跑一轮：done 事件和 GET /sessions/{id} 的
result.key_numbers 一致（落库与外发同源）；⑤ grounding 三个私有函数的名字和签名钉死（§4 已定 6）。
"""
import inspect
import json
import os

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core import grounding
from app.core.result import AnalysisResult
from app.server.app import create_app
from app.server.key_numbers import attach_key_numbers, key_numbers_of
from tests.test_core_analyze import wf_model


def R(result, answer, question="", **kw):
    base = dict(agent="workflow", dataset="x.csv", question=question, answer=answer, result=result, executed=True)
    base.update(kw)
    return AnalysisResult(**base)


# §1.2 原型核对表：(result, 结论, 问题, 期望)
PROTOTYPE = [
    (pd.Series({"上海": 822023.63, "深圳": 1061, "北京": 300}, name="销量"),          # 降序
     "深圳销量最高，共 1,061 单；上海 82.2 万。", "各城市销量",
     [{"value": "82.2 万", "label": "上海 · 销量"}, {"value": "1,061", "label": "深圳 · 销量"}]),
    (8998790.914, "总销售额为 8,998,790.91 元。", "总销售额是多少",
     [{"value": "8,998,790.91", "label": "销售额"}]),
    (1685, "总销量 1685", "哪个地区卖得最好", []),                                       # 问题里没有指标词
    ({"占比": 0.2230, "均值": 3.1416, "行数": 7}, "占比 22.30%，均值 3.14。", "",
     [{"value": "22.30%", "label": "占比"}, {"value": "3.14", "label": "均值"}]),
    (pd.Series([100, 900, 300, 500], index=["1 月", "2 月", "3 月", "4 月"], name="销量"),  # 4 个月、未排序
     "2 月最高 900。", "月度销量", []),
]

# 规则里的其余分支：(result, 结论, 问题, 期望)
MORE = [
    # > 3 项且单调（Top-N）：取前 3 项
    (pd.Series([900, 700, 500, 300], index=list("ABCD"), name="利润"), "A 900，B 700，C 500，D 300。", "",
     [{"value": "900", "label": "A · 利润"}, {"value": "700", "label": "B · 利润"}, {"value": "500", "label": "C · 利润"}]),
    # Series 没有名字：口径只用索引；零点 Timestamp 写成日期
    (pd.Series([1200.5, 980.0], index=pd.to_datetime(["2024-01-01", "2024-02-01"])), "1 月 1,200.5，2 月 980。", "",
     [{"value": "1,200.5", "label": "2024-01-01"}, {"value": "980", "label": "2024-02-01"}]),
    # 单行 DataFrame：数值列，口径是列名
    (pd.DataFrame({"城市": ["深圳"], "销售额": [54406.5], "订单数": [128]}), "深圳销售额 54,406.5 元，订单 128 单。", "",
     [{"value": "54,406.5", "label": "销售额"}, {"value": "128", "label": "订单数"}]),
    # numpy 标量 + 问题里的第一个指标词
    (np.float64(3.5), "平均评分 3.50。", "平均评分是多少", [{"value": "3.50", "label": "评分"}]),
    # 小整数（< 100、不带单位）不出：grounding 本来就不核
    ({"行数": 7, "列数": 5}, "共 7 行 5 列。", "", []),
    # bool 不算数字
    ({"全部为正": True, "金额": 150.0}, "金额 150 元。", "", [{"value": "150", "label": "金额"}]),
    # 每个结论数字最多用一次：两个候选都是 500，结论只写了一次
    ({"A": 500, "B": 500}, "A 和 B 都是 500。", "", [{"value": "500", "label": "A"}]),
    # 最多 3 个
    ({"a": 101, "b": 102, "c": 103, "d": 104}, "101、102、103、104", "",
     [{"value": "101", "label": "a"}, {"value": "102", "label": "b"}, {"value": "103", "label": "c"}]),
    # 结论没提到的数不放大
    ({"总额": 1234.5}, "数据已汇总。", "", []),
]


@pytest.mark.parametrize("result,answer,question,expected", PROTOTYPE + MORE)
def test_key_numbers_table(result, answer, question, expected):
    r = R(result, answer, question)
    got = key_numbers_of(r)
    assert got == expected
    # ② 统一断言：每个 value 都在结论原文里，且按 grounding 规则能在 str(r.result) 里核到
    for kn in got:
        assert kn["value"] in answer
        toks = grounding._tokens(kn["value"])
        assert len(toks) == 1 and grounding._significant(*toks[0][1:]), kn   # 有分量的数，下一行不是空判
        assert grounding.unverified_numbers(kn["value"], [str(r.result)]) == [], kn


def test_unverified_numbers_are_skipped():
    """双保险：value 在 r.unverified_numbers 里的跳过（按构造不该出现，前端 turn.ts 还有第三道）。"""
    r = R({"金额": 150.0, "成本": 120.0}, "金额 150，成本 120。", unverified_numbers=["150"])
    assert key_numbers_of(r) == [{"value": "120", "label": "成本"}]


@pytest.mark.parametrize("kw", [
    dict(clarify=True),
    dict(executed=False),
    dict(error="模型调用失败", error_kind="llm"),
    dict(result="无法回答：数据里没有利润字段"),               # 拒答字符串
])
def test_not_produced(kw):
    r = R({"金额": 150.0}, "金额 150。")
    for k, v in kw.items():
        setattr(r, k, v)
    assert key_numbers_of(r) is None
    rec = {}
    attach_key_numbers(rec, r)
    assert "key_numbers" not in rec           # 不该产出时不写这个键（前端按缺键处理）


def test_multirow_dataframe_and_unsorted_long_series_give_nothing():
    df = pd.DataFrame({"城市": ["深圳", "上海"], "销售额": [500.5, 300.5]})
    assert key_numbers_of(R(df, "深圳 500.5，上海 300.5。")) == []
    s = pd.Series([3.5, 1.5, 2.5, 4.5], name="x")
    assert key_numbers_of(R(s, "3.5、1.5")) == []


def test_grounding_private_api_is_pinned():
    """§4 已定 6：key_numbers 直接 import grounding 的三个私有函数。重构 grounding 时这里先红，提醒同步改 key_numbers.py。"""
    sig = {n: list(inspect.signature(getattr(grounding, n)).parameters) for n in ("_tokens", "_significant", "_candidates")}
    assert sig == {"_tokens": ["text"], "_significant": ["v", "dec", "unit", "after"], "_candidates": ["v", "dec", "unit"]}
    # 返回形状：_tokens → [(原文, 数值, 小数位, 单位, 后一个字)]；_candidates → [(值, 容差)]
    assert grounding._tokens("82.2 万元") == [("82.2 万", 82.2, 1, "万", "元")]
    assert grounding._significant(82.2, 1, "万", "元") is True and grounding._significant(7, 0, "", "") is False
    assert grounding._candidates(22.30, 2, "%") == pytest.approx([(22.30, 0.005 + 1e-9), (0.2230, (0.005 + 1e-9) / 100)])


# ---------------------------------------------------------------- 落库与外发同源（TestClient）
TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}


def _sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.mark.parametrize("code,answer,question,expected", [
    ("result = int(df['units'].sum())", "总销量 1685 件。", "总销量是多少", [{"value": "1685", "label": "销量"}]),
    ("result = df.groupby('region')['units'].sum().sort_values(ascending=False)",
     "华南最多，620 件；华北 540 件。", "各地区销量",
     [{"value": "620", "label": "华南 · units"}, {"value": "540", "label": "华北 · units"}]),
])
def test_done_event_and_stored_message_carry_the_same_key_numbers(tmp_path, sample_path, code, answer, question, expected):
    c = TestClient(create_app(str(tmp_path / "home"), TOKEN, chat_model_factory=lambda: wf_model([code], answer=answer)))
    files = [("files", (os.path.basename(sample_path), open(sample_path, "rb"), "text/csv"))]
    ds = c.post("/datasets", files=files, data={"name": ""}, headers=H).json()
    s = c.post("/sessions", json={"dataset_id": ds["id"], "agent": "workflow"}, headers=H).json()
    r = c.post(f"/sessions/{s['id']}/messages", json={"content": question}, headers=H)
    done = _sse(r.text)[-1][1]["data"]["result"]
    stored = c.get(f"/sessions/{s['id']}", headers=H).json()["messages"][1]["result"]
    assert done["key_numbers"] == stored["key_numbers"] == expected
    assert done["unverified_numbers"] == [] and done["meta"] == stored["meta"]
