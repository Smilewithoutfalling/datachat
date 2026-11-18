"""阶段 7 A2 结果合理性校验、A3 枚举值召回（docs/roadmap/phase7-a2a3.md）。"""
import numpy as np
import pandas as pd

from app.core import LLMConfig, analyze
from app.eval.egress import EGRESS_MAX_COLUMN_HITS
from app.nodes.executor import execute
from app.tools import value_hints as VH
from app.tools.dataset import describe_data
from app.tools.sanity import SANITY_PREFIX, result_issue
from app.core.testing import prompt_text
from tests.test_core_analyze import wf_model

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)


# ---- A2 ----

def test_result_issue_shapes():
    assert result_issue(pd.DataFrame()) and result_issue(pd.Series(dtype=float))
    assert result_issue(float("nan")) and result_issue(pd.Series([np.nan, np.nan]))
    assert "inf" in result_issue(pd.Series([1.0, np.inf]))
    assert "result['b']" in result_issue({"a": 1, "b": pd.Series(dtype=int)})


def test_result_issue_leaves_plausible_results_alone():
    # 计数 0、拒答字符串、部分 NaN、正常结果都不报
    for r in (0, "无法回答：数据中没有 x 字段", pd.Series([1, 2]), pd.DataFrame({"a": ["x"], "b": [np.nan]}),
              {"a": 1, "b": "华东"}, None, [1, 2]):
        assert result_issue(r) is None, r


def test_executor_flags_once_and_keeps_result():
    cfg = {"configurable": {"df": pd.DataFrame({"region": ["华东区"], "units": [3]})}}
    out = execute({"code": "result = df[df['region'] == '华东']['units']"}, cfg)
    # 结果照样保留（不是 error），只是挂上 sanity_issue 让路由去 reviewer
    assert out["error"] == "" and out["sanity_issue"] and out["sanity_retried"] is True
    assert isinstance(out["result"], pd.Series)
    again = execute({"code": "result = df[df['region'] == '华东']['units']", "sanity_retried": True}, cfg)
    assert again["sanity_issue"] == "" and again["error"] == ""


def test_workflow_empty_result_gets_one_review(tmp_path):
    p = tmp_path / "d.csv"
    pd.DataFrame({"region": ["华东区", "华北区"], "units": [3, 4]}).to_csv(p, index=False)
    m = wf_model(["result = df[df['region'] == '华东']['units'].sum() if False else df[df['region'] == '华东']"],
                 fixes=["result = df[df['region'] == '华东区']['units'].sum()"])
    r = analyze(str(p), "华东卖了多少", chat_model=m, llm_config=FAST, use_dictionary=False)
    assert r.ok and r.executed and int(r.result) == 3
    assert r.attempts == 1 and r.sanity_issue.startswith("结果是空")
    fix_prompt = next(prompt_text(c) for c in m.calls if "请修正它" in prompt_text(c))
    assert SANITY_PREFIX in fix_prompt


def test_workflow_keeps_suspicious_result_after_one_review(tmp_path):
    # reviewer 原样交回同样的代码：第二次不再拦，空结果照常进 summarizer，不会被丢掉
    p = tmp_path / "d.csv"
    pd.DataFrame({"region": ["华东区"], "units": [3]}).to_csv(p, index=False)
    code = "result = df[df['region'] == '西北']"
    m = wf_model([code], fixes=[code])
    r = analyze(str(p), "西北有哪些记录", chat_model=m, llm_config=FAST, use_dictionary=False)
    assert r.ok and r.executed and r.attempts == 1 and len(r.result) == 0


# ---- A3 ----

def _biz_like():
    return pd.DataFrame({"region": ["华东区", "华北区", "华南区", "西南区", "东北区"] * 3,
                         "lvl": ["Basic", "basic ", "Gold", "VIP", "vip"] * 3,
                         "date": ["2024-01-05"] * 15, "x": range(15)})


def _hints(q, df):
    return VH.find_hints(q, df, describe_data(df) + "\n" + q)


def test_fuzzy_value_and_case_variants():
    df = _biz_like()
    assert _hints("华东的销量是多少", df) == [("华东", "region", "华东区")]
    assert _hints("basic 会员有几个", df) == [("basic", "lvl", "Basic"), ("basic", "lvl", "basic ")]


def test_no_hint_when_nothing_new():
    df = _biz_like()
    assert _hints("哪个地区卖得最好", df) == []
    assert _hints("华北区呢", df) == []                # 原文写对了、样例里也看得见
    assert _hints("2024 年 1 月有几条", df) == []      # 纯数字词不和日期串
    assert VH.value_hints("哪个地区卖得最好", df, describe_data(df)) == ""


def test_short_term_inside_long_value_is_not_a_match():
    df = pd.DataFrame({"name": ["数码商品01", "服饰商品02"]})
    assert _hints("商品有几种", df) == []


def test_egress_budget_per_column():
    # 合同：任一文本列出境的不同取值 ≤ 3。样例行已经露了 3 个，就一个也不加
    assert VH.MAX_COLUMN_HITS == EGRESS_MAX_COLUMN_HITS
    df = _biz_like()
    assert all(v != "VIP" for _, _, v in _hints("vip 客户", df))
    df2 = pd.DataFrame({"c": ["甲", "甲", "甲"] + [f"值{i}号" for i in range(10)] + ["华东区一部", "华东区二部"]})
    hs = _hints("华东区", df2)
    shown = {v for v in df2["c"].unique() if v in describe_data(df2) + "华东区"}
    assert len(shown | {v for _, _, v in hs}) <= EGRESS_MAX_COLUMN_HITS


def test_hints_are_wrapped_as_data_and_clipped():
    df = pd.DataFrame({"c": ["甲"] * 3 + ["Q" * 80]})
    text = VH.value_hints("q" * 80 + " 有几条", df, describe_data(df))
    assert "<<<数据内容开始" in text and "Q" * 41 not in text


def test_hints_reach_workflow_prompts(tmp_path):
    p = tmp_path / "d.csv"
    _biz_like().to_csv(p, index=False)
    m = wf_model(["result = 1"])
    r = analyze(str(p), "华东的销量是多少", chat_model=m, llm_config=FAST, use_dictionary=False)
    assert "华东区" in r.value_hints
    planner = next(prompt_text(c) for c in m.calls if "数据分析规划助手" in prompt_text(c))
    assert "'华东区'" in planner
