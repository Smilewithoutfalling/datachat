"""多表业务题（biz）的结构约束。

这批题第一批实测吃了三次亏，全部是「题面漏写一句、gold 却按那句算了」：
- 12 题没写订单去重 → 各城市/各状态多 1~4 单（60%）
- 006 没写「只算已完成订单」→ 模型算了全部状态
- 016 没写商品表重复 → 两个重复 SKU 的明细双算（269 vs 208）
所以这里把口径做成机器断言：以后加题漏写一句，测试先炸，而不是等跑完 20 题看数字才发现。
"""
import pandas as pd
import pytest

from app.eval.cases import ALL_CASES, DATASETS
from app.eval.cases_biz import BIZ_CASES
from app.eval.runner import EvalRunner

BIZ = {c.id: c for c in BIZ_CASES}


def test_count_and_dataset():
    assert len(BIZ_CASES) == 20
    assert len({c.id for c in BIZ_CASES}) == 20
    assert all(c.dataset == "biz" for c in BIZ_CASES)
    assert all(c.multi_table for c in BIZ_CASES), "多表题必须标 multi_table"
    assert DATASETS["biz"].endswith("biz")


def test_all_ids_unique_across_whole_set():
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == len(set(ids))


def test_biz_dir_has_five_tables():
    import os

    from app.tools.dataset import table_paths
    names = [n for n, _ in table_paths(DATASETS["biz"])]
    assert names == ["customers", "order_items", "orders", "products", "refunds"]


@pytest.fixture(scope="module")
def runner():
    return EvalRunner(agent="react")


def test_every_gold_runs(runner):
    bad = []
    for c in BIZ_CASES:
        outs, err = runner.expected_all(c)
        if err or not outs:
            bad.append((c.id, (err or "无结果").splitlines()[-1][:120]))
    assert not bad, f"gold 跑不通：{bad}"


def test_question_states_the_dedup_rule():
    """涉及订单表计数的题必须写明去重，否则口径不唯一。

    002 问的就是重复条数、015 只查退款表，这两条不能有「重复只算一次」。
    """
    exempt = {"biz_002", "biz_015"}
    for c in BIZ_CASES:
        if c.id in exempt:
            continue
        assert ("去重" in c.question) or ("只算一次" in c.question), f"{c.id} 没写订单去重口径"
    for cid in exempt:
        assert "只算一次" not in BIZ[cid].question, f"{cid} 不该有去重说明"


def test_question_states_done_only_when_gold_filters_done():
    """gold 里出现 `status'] == '已完成'` 的题，题面必须写「只算已完成订单」。"""
    exempt = {"biz_002", "biz_007", "biz_008", "biz_015"}   # 002 去重条数；007 分母全量；008 状态分布；015 只查退款
    for c in BIZ_CASES:
        if c.id in exempt:
            continue
        if "已完成" in c.ground_truth:
            assert "已完成" in c.question, f"{c.id} gold 筛了已完成，题面没写"


def test_product_dedup_is_stated_when_joining_products():
    """gold 里 drop_duplicates('sku') 的题，题面必须提商品表重复。"""
    for c in BIZ_CASES:
        if "drop_duplicates('sku')" in c.ground_truth:
            assert "商品表" in c.question and ("重复" in c.question or "去重" in c.question), \
                f"{c.id} gold 去了商品表重复，题面没写"


def test_dirty_data_still_dirty(runner):
    """数据集不能被「顺手洗干净」：脏点没了，这批题就退化成普通单表题。"""
    d = runner.frame("biz")
    o, it, pr, cu, rf = d["orders"], d["order_items"], d["products"], d["customers"], d["refunds"]
    assert len(o) > o["order_id"].nunique(), "订单表没有整行重复"
    assert o["status"].str.strip().nunique() < o["status"].nunique(), "状态列没有前后空格"
    assert o["order_date"].astype(str).str.contains(" ").any(), "日期列没有时间部分"
    assert it["unit_price"].dtype == object or str(it["unit_price"].dtype) == "str", "金额列没有混格式"
    assert it["sku"].str.contains("[a-z]").any(), "SKU 没有小写混写"
    assert len(pr) > pr["sku"].nunique(), "商品表没有整行重复"
    assert cu["customer_id"].str.startswith(" ").any(), "客户编号没有前导空格"
    assert len(rf) > len(rf.drop_duplicates()), "退款表没有整行重复"


def test_scalar_answers_stay_scalar(runner):
    """标量题的答案是标量。Series 一旦退化成标量，这道题就不再考原来的东西。"""
    for c in BIZ_CASES:
        if c.gold_kind not in ("scalar", "text"):
            continue
        v = runner.expected_all(c)[0][0]
        assert not isinstance(v, (pd.Series, pd.DataFrame)), f"{c.id} 声明 {c.gold_kind} 但结果是容器"
