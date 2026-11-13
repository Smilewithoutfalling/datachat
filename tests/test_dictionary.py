import os

import pytest

from app.tools import dictionary
from app.tools.dictionary import (MAX_DESC_CHARS, DictRetriever, _tok, augment_question, clip,
                                 dict_path_for, format_notes, load_retriever)

# ---------------------------------------------------------------- 单表：必须零变化

def _legacy_search(r, query, k=3):
    """改动前 DictRetriever.search 的逐字副本。单表路径必须与它完全一致。"""
    scores = r._bm25.get_scores(_tok(query))
    ranked = sorted(zip(scores, r.entries), key=lambda x: x[0], reverse=True)
    return [e for s, e in ranked[:k] if s > 0]


@pytest.mark.parametrize("query", [
    "哪个地区卖得最好", "总销售额是多少", "各品类销量排名", "按月份看趋势", "利润最高的产品", "有多少条记录",
])
def test_single_table_search_identical_to_legacy(sample_path, query):
    r = load_retriever(sample_path)
    assert r._groups is None, "单表不该进分组路径"
    assert r.search(query) == _legacy_search(r, query)


def test_single_table_keeps_truncate_then_filter_order():
    """老实现是「先截前 k 再丢零分」，不是「先丢零分再截」——边界上条数不同。"""
    r = DictRetriever([("hit", "订单"), ("zero1", "无关词甲"), ("zero2", "无关词乙")])
    # 只有 hit 有分；k=2 时老实现返回 1 条（截前 2 再过滤掉 1 个零分）
    assert len(r.search("订单", k=2)) == 1


# ---------------------------------------------------------------- 多表：按表分组

def _table(tmp_path, name, fields):
    """造一张表 + 它的字典。fields = [(字段, 描述), ...]"""
    (tmp_path / f"{name}.csv").write_text("v\n1\n", encoding="utf-8")
    rows = "\n".join(f"{f},{d}" for f, d in fields)
    (tmp_path / f"{name}.dict.csv").write_text("field,description\n" + rows, encoding="utf-8")


def _multi(tmp_path):
    """t1 有四条都含「订单」，t2 只有一条 —— 全局 top-3 会被 t1 通吃，t2 一条都进不来。"""
    _table(tmp_path, "t1", [("f1", "订单 编号"), ("f2", "订单 金额"), ("f3", "订单 状态"), ("f4", "订单 日期")])
    _table(tmp_path, "t2", [("g1", "订单 客户")])
    return str(tmp_path)


def test_flat_topk_starves_second_table(tmp_path):
    """先钉住问题本身：合并成一份检索器时，t2 的条目进不了前 3。"""
    path = _multi(tmp_path)
    r = load_retriever(path)
    flat = dictionary.DictRetriever(r.entries)          # 老构造方式：不传 groups
    assert flat._groups is None
    assert all(f.startswith("t1.") for f, _ in flat.search("订单", k=3))


def test_grouped_search_gives_every_table_a_slot(tmp_path):
    """分组后每张表至少有一条，低分表不被高分表挤掉。"""
    r = load_retriever(_multi(tmp_path))
    assert r._groups is not None and len(r._groups) == 2
    fields = [f for f, _ in r.search("订单", k=3)]
    assert any(f.startswith("t1.") for f in fields)
    assert any(f.startswith("t2.") for f in fields), f"t2 被挤掉了：{fields}"


def test_grouped_per_table_cap(tmp_path):
    """每张表最多 PER_TABLE_K 条，即使 k 传得更大。"""
    r = load_retriever(_multi(tmp_path))
    fields = [f for f, _ in r.search("订单", k=10)]
    assert sum(1 for f in fields if f.startswith("t1.")) <= dictionary.PER_TABLE_K
    assert sum(1 for f in fields if f.startswith("t2.")) <= dictionary.PER_TABLE_K


def test_grouped_total_cap(tmp_path):
    """表很多时总条数仍受 TOTAL_CAP 约束。"""
    for i in range(12):
        _table(tmp_path, f"t{i:02d}", [(f"c{i}", "订单 金额")])
    r = load_retriever(str(tmp_path))
    assert len(r.search("订单", k=3)) <= dictionary.TOTAL_CAP


def test_round_robin_first_round_before_second(tmp_path):
    """轮转：所有表的第 1 条都排在任一张表的第 2 条之前。"""
    _table(tmp_path, "ta", [("a1", "订单 甲"), ("a2", "订单 乙")])
    _table(tmp_path, "tb", [("b1", "订单 丙")])
    r = load_retriever(str(tmp_path))
    fields = [f for f, _ in r.search("订单", k=3)]
    assert fields.index("tb.b1") < fields.index("ta.a2"), f"轮转顺序不对：{fields}"


def test_grouped_drops_zero_score(tmp_path):
    """分组也不能把零分条目当成「占位」塞进来。"""
    _table(tmp_path, "ta", [("a1", "订单 甲")])
    _table(tmp_path, "tb", [("b1", "完全无关的说明")])
    r = load_retriever(str(tmp_path))
    assert [f for f, _ in r.search("订单", k=3)] == ["ta.a1"]


def test_one_table_with_dict_falls_back_to_flat(tmp_path):
    """多表但只有一张表有字典 —— 分组没有意义，必须退回全局路径，与改动前一致。"""
    (tmp_path / "t1.csv").write_text("v\n1\n", encoding="utf-8")
    (tmp_path / "t2.csv").write_text("v\n1\n", encoding="utf-8")
    (tmp_path / "t1.dict.csv").write_text("field,description\nf1,订单 金额\n", encoding="utf-8")
    r = load_retriever(str(tmp_path))
    assert r is not None and r._groups is None
    assert r.search("订单") == _legacy_search(r, "订单")


# ---------------------------------------------------------------- 真数据：biz 的规则必须进 prompt

# 这 11 道题在 release 全量里因「没按字典规则清洗」答错（见 DEVLOG [176]/[177]）。
# 改动前 status / customer_id / sku 三条规则的召回是 0/11 —— 一次都没进过 prompt。
_BIZ_WRONG = ["biz_003", "biz_004", "biz_005", "biz_006", "biz_013",
              "biz_014", "biz_016", "biz_017", "biz_018", "biz_019", "biz_020"]
_RULES = {
    "status": "strip 后再比较",
    "customer_id": "join 前需 strip",
    "sku": "统一大写",
}


def _biz_prompt_notes(case_id):
    from app.eval.cases import BIZ_CASES, DATASETS
    case = next(c for c in BIZ_CASES if c.id == case_id)
    r = load_retriever(DATASETS["biz"])
    return format_notes([(clip(f, 64), clip(d, MAX_DESC_CHARS)) for f, d in r.search(case.question)])


@pytest.mark.parametrize("rule,marker", list(_RULES.items()))
def test_biz_dirty_rule_reaches_prompt(rule, marker):
    """11 道错题的召回必须全覆盖；改动前这三条都是 0/11。"""
    hits = sum(1 for cid in _BIZ_WRONG if marker in _biz_prompt_notes(cid))
    assert hits == len(_BIZ_WRONG), f"{rule} 规则只在 {hits}/11 道题的 prompt 里出现"


def test_biz_prompt_stays_within_budget():
    """分组会把字典段撑大，但不能失控 —— biz 单题字典段不超过 1000 字符（约占总 prompt 20%）。"""
    for cid in _BIZ_WRONG:
        assert len(_biz_prompt_notes(cid)) <= 1000, f"{cid} 字典段过长"


# ---------------------------------------------------------------- 其余 API 不变

def test_dict_path_for():
    assert dict_path_for(os.path.join("data", "sample.csv")) == os.path.join("data", "sample.dict.csv")


def test_retriever_hits_region(sample_path):
    r = load_retriever(sample_path)
    assert r is not None
    fields = [f for f, _ in r.search("哪个地区卖得最好", k=3)]
    assert "region" in fields


def test_augment_without_retriever_is_identity():
    assert augment_question("总销售额", None) == "总销售额"


def test_no_dict_file_returns_none(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    assert load_retriever(str(p)) is None
