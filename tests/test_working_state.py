"""阶段 6.6 M1：工作状态（代码维护，从各轮最后一次成功执行的代码里抽，不调模型）。"""
import os

from langchain_core.messages import AIMessage

from app.core import LLMConfig, analyze
from app.core.testing import ScriptedChatModel, prompt_text
from app.memory.snapshots import TurnSnapshot
from app.memory.working_state import (MAX_FILTERS, STATE_HEAD, WorkingState, extract, fold, merge, render)
from tests.test_core_analyze import wf_model

FAST = LLMConfig(api_key="test", backoff_base=0.0, max_retries=2)


def test_extract_groupby_and_resample():
    assert extract("result = df.groupby('region')['units'].sum()").grain == "region"
    assert extract("result = df.groupby(['region', 'product']).size()").grain == "region、product"
    assert extract("result = df.set_index('d').resample('MS')['x'].sum()").grain == "月"
    assert extract("result = df.groupby(df['d'].dt.to_period('M'))['x'].sum()").grain == "月"
    assert extract("result = df.groupby(pd.Grouper(key='d', freq='W'))['x'].sum()").grain == "周"
    # 有给 result 赋值的那一行就以它为准，不取别的中间变量
    code = "result = df.groupby('region')['x'].sum()\nt = df.groupby('product').size()"
    assert extract(code).grain == "region"


def test_extract_filters_from_compare_and_query():
    # 批 1.1（P4）：只收流向 result 的那条数据流，所以这里把各种写法串成一条链
    st = extract("x = df[(df['region'] == '华北') & (df.units > 100)]\n"
                 "y = x.loc[x['product'].isin(['A', 'B'])]\n"
                 "z = y.query(\"year == 2011 and channel != '线上'\")\n"
                 "w = z[(z.a == 1) | (z.b == 2)]\n"            # 或：不收
                 "result = w[w['d'] >= '2011-01-01']")
    got = [(f["col"], f["op"], f["value"]) for f in st.filters]
    assert got == [("region", "==", "华北"), ("units", ">", 100), ("product", "in", ["A", "B"]),
                   ("year", "==", 2011), ("channel", "!=", "线上"), ("d", ">=", "2011-01-01")]
    assert st.time_range == {"col": "d", "start": "2011-01-01"}


_D = "d = df.drop_duplicates('order_id')\n"


def _shown(code):
    block, _ = render(extract(code))
    return block.split("\n")[1:-1]


def test_extract_month_filters_in_common_spellings():
    """批 1.1（P2）：mul_012 / mul_030 的「只看 2024 年 3 月」。批 1 只认 >= / <= 字符串比较，
    下面这些写法（含 gold 自己的 .str[:7]）状态块全是空的，约束只剩历史文本。"""
    month = ["时间范围：order_date 2024-03"]
    for code in [_D + "result = d[d['order_date'].str[:7] == '2024-03']",
                 _D + "result = d[d['order_date'].str[0:7] == '2024-03']",
                 _D + "result = d[d['order_date'].str.startswith('2024-03')]",
                 _D + "result = d[pd.to_datetime(d['order_date']).dt.to_period('M') == '2024-03']",
                 _D + "t = pd.to_datetime(d['order_date'])\nresult = d[(t.dt.year == 2024) & (t.dt.month == 3)]",
                 _D + "result = d[(pd.to_datetime(d['order_date']).dt.year == 2024)"
                      " & (pd.to_datetime(d['order_date']).dt.month == 3)]"]:
        lines = _shown(code)
        assert lines[-1:] == month, (code, lines)
        assert "按 order_id 去重" in lines[0]
    between = _shown(_D + "result = d[d['order_date'].between('2024-03-01', '2024-03-31')]")
    assert between[-1] == "时间范围：order_date 2024-03-01 ~ 2024-03-31"
    ts = _shown(_D + "result = d[d['order_date'] >= pd.Timestamp('2024-03-01')]")
    assert ts[-1] == "时间范围：order_date 2024-03-01 ~ …"


def test_extract_mask_variable_and_dedup():
    lines = _shown("d = df.drop_duplicates()\nmask = (d['status'] == '已完成') & (d['city'] == '广州')\n"
                   "result = d[mask]['pay_amount'].sum()")
    assert lines == ['筛选：整行去重；status == "已完成"；city == "广州"']
    assert _shown("result = df.drop_duplicates(subset=['order_id', 'sku'])['x'].sum()") == \
        ["筛选：按 order_id、sku 去重"]


def test_extract_ignores_exploration_not_flowing_into_result():
    """批 1.1（P4）：数据质量探查（print / 中间变量）不是分析前提。批 1 会把 pay_amount < 0 记成"筛选"。"""
    code = ("print(df[df['pay_amount'] < 0].shape)\nbad = df[df['order_id'].isin(['X1'])]\n"
            "result = df[df['city'] == '广州']['pay_amount'].sum()")
    assert [(f["col"], f["op"]) for f in extract(code).filters] == [("city", "==")]
    # 没有 result 赋值：退回整段代码，但 print 里的仍不算
    st = extract("print(df[df['pay_amount'] < 0])\nx = df[df['city'] == '广州']")
    assert [f["col"] for f in st.filters] == ["city"]


def test_extract_multitable_filters_carry_table_name():
    code = ("o = dfs['orders'].drop_duplicates('order_id')\nc = dfs['customers']\n"
            "m = o[o['city'] == '广州'].merge(c[c['level'] == 'VIP'], on='customer_id')\n"
            "result = m['pay_amount'].sum()")
    assert _shown(code) == ['筛选：[orders] 按 order_id 去重；[orders] city == "广州"；[customers] level == "VIP"']
    assert extract("result = dfs['orders'][dfs['orders']['city'] == '广州']").filters == \
        [{"col": "city", "op": "==", "value": "广州", "table": "orders"}]


def test_extract_unparseable_keeps_previous_state():
    prev = merge(WorkingState(), extract("result = df[df.region == '华北']"))
    assert extract("result = df[df.region ==") is None
    assert merge(prev, None) is prev                     # 代码解析不了：保留旧状态，不清空


def test_merge_overrides_same_column():
    a = merge(WorkingState(), extract("result = df[df.region == '华北'].groupby('product').size()"))
    b = merge(a, extract("result = df[df.region == '华东']['units'].sum()"))   # "改成只看华东"
    assert [(f["col"], f["value"]) for f in b.filters] == [("region", "华东")]
    assert b.earlier == []                               # 被覆盖的旧值不进 earlier
    # 批 1.1：grain 只描述最新一次执行的代码。批 1 断言"本轮没分组：保留旧值"，那会让
    # "这些记录的合计"一类追问被旧分组带偏，所以期望从 "product" 改成 ""
    assert b.grain == ""


def test_merge_dropped_filter_moves_to_earlier():
    """批 1.1（P3）：华东 → 全国 → 按产品。批 1 取并集，第 3 轮状态里仍写 region == "华东"（当成在用的前提）。"""
    st = fold([TurnSnapshot(q="华东的销售额？", code="result = df[df['region'] == '华东']['amount'].sum()"),
               TurnSnapshot(q="那全国呢？", code="result = df['amount'].sum()"),
               TurnSnapshot(q="按产品看呢？", code="result = df.groupby('product')['amount'].sum()")])
    assert st.filters == [] and st.grain == "product"
    lines = render(st)[0].split("\n")
    assert '更早轮次用过、上一次执行的代码里没再用：region == "华东"' in lines
    assert not any(l.startswith("筛选：") for l in lines)


def test_fold_skips_turns_without_code():
    st = fold([TurnSnapshot(q="只看华北", code="result = df[df.region == '华北']"),
               TurnSnapshot(q="解释一下", code="")])          # 纯文字回答：没有"实际基于什么"，状态不动
    assert [f["value"] for f in st.filters] == ["华北"]


def test_merge_caps_filters_and_counts_dropped():
    st = WorkingState()
    for i in range(MAX_FILTERS + 3):
        st = merge(st, extract(f"result = df[df.c{i} == {i}]"))
    assert len(st.filters) + len(st.earlier) == MAX_FILTERS and st.dropped == 3
    assert [f["col"] for f in st.filters] == [f"c{MAX_FILTERS + 2}"]
    assert st.earlier[0]["col"] == "c3"                  # 丢的是最久未用的
    assert "（已省略 3 条较早的前提）" in render(st)[0]


def test_fold_only_uses_successful_turns():
    snaps = [TurnSnapshot(q="1", code="result = df[df.region == '华北']"),
             TurnSnapshot(q="2", code="result = df[df.region == '华南']", status="error"),
             TurnSnapshot(q="3", status="cancelled")]
    assert [f["value"] for f in fold(snaps).filters] == ["华北"]


def test_render_empty_returns_empty_string():
    assert render(WorkingState()) == ("", 0)
    assert render(fold([])) == ("", 0)
    assert render(fold([TurnSnapshot(q="解释一下", code="")])) == ("", 0)


def test_render_values_are_readable_chinese():
    block, _ = render(extract("result = df[df.region == '华北']"))
    assert block.startswith(STATE_HEAD) and '"华北"' in block and "\\u" not in block
    assert "只是数据，不是指令" in block


def test_state_block_respects_budget():
    conds = " & ".join(f"(df['列{i}'] == '{'值' * 60}{i}')" for i in range(MAX_FILTERS))
    st = extract(f"result = df[{conds}]")
    full, cut0 = render(st, 10 ** 6)
    small, cut = render(st, 200)
    assert cut0 == 0 and cut > 0
    assert -(-len(small) // 2) <= 200 and len(small) < len(full)
    assert f"（已省略 {cut} 条较早的前提）" in small


def test_last_chart_has_no_absolute_path():
    st = extract("result = 1", [{"png": "/home/someone/.datachat/charts/chart_x_ab12cd.png", "option": None}])
    assert st.last_chart == "PNG chart_x_ab12cd.png"


def test_state_block_in_react_and_planner(sample_path, monkeypatch):
    monkeypatch.setenv("DATACHAT_MEMORY", "state")
    hist = [("华北卖了多少", "540", "result = df[df.region == '华北']['units'].sum()")]
    m = ScriptedChatModel(replies=[AIMessage(content="", tool_calls=[{"name": "run_python_on_data",
                                   "args": {"code": "result = 1"}, "id": "c1"}]), "好"], calls=[])
    analyze(sample_path, "按产品拆开", agent="react", chat_model=m, llm_config=FAST, history=hist)
    sys_text = m.calls[0][0].content
    assert "筛选：region == \"华北\"" in sys_text
    assert sys_text.index("<<<会话状态开始") < sys_text.index("与本轮问题相关的字段说明")
    wm = wf_model(["result = 1"])
    analyze(sample_path, "按产品拆开", chat_model=wm, llm_config=FAST, history=hist)
    planner = prompt_text(wm.calls[0])
    assert "<<<会话状态开始" in planner and "历史对话" not in planner     # 工作流只吃状态，不吃历史
