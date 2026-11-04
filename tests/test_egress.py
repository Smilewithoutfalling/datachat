"""出境审计（EV-B10）：四条合同断言 + 证明这些断言真的会红。

审计对象是**模型实际收到的 prompt**（`ScriptedChatModel.calls` 里的 messages，
用 `prompt_text` 拼平），不是模板。理由写在 `app/eval/egress.py` 的 docstring 里：
schema 由 `describe_df` 渲染、字典由 BM25 检索后截断、结果由 `format_result` 截断，
任一层漏了截断，模板都看不出来。

夹具刻意造得比真实数据更"难"：
- `order_id` 200 行全唯一 → 样例行数一多就会被数出来；
- `note` 200 行，每行 200 字 → 不截断就会整段出境；
- `region` 5 个取值但样本只露 3 个 → 字典一旦枚举全部取值就会红；
- 代码用 `plt.savefig(chart_path)` 出图 → 图表文件名这条通道也在审计范围内。

最后一条是这轮审计的真实战果：`chart_note` / ReAct 的工具回传原来把 PNG 的**绝对路径**
写进 prompt，桌面版默认装在用户目录下时等于把用户名一起发出去。修法见
`app/core/result.py::chart_note` 与 `app/react_agent.py` 的 tool 返回。
"""
import os

import pandas as pd
import pytest

from app.eval import egress
from app.tools import schema as schema_mod
from app.tools.dataset import load_data

REGIONS = ["华东", "华北", "华南", "西南", "东北"]

# 五行的 region 各不相同：样本 3 行只露 3 个取值，后两个一次都不该出现。
# plt 分支是刻意走的 —— chart() 只回 ECharts option，不带文件路径，
# 只有 plt.savefig(chart_path) 会生成 PNG，才测得到 ④ 的图表通道。
CODE = (
    "g = df.groupby('region')['units'].sum()\n"
    "fig = plt.figure()\n"
    "plt.bar(g.index, list(g.values))\n"
    "plt.title('各大区销量')\n"
    "plt.savefig(chart_path)\n"
    "result = float(g.max())\n"
)

DICT_CSV = (
    "field,description\n"
    "order_id,订单编号，全局唯一\n"
    "region,销售大区（地理分区）\n"
    "customer,客户名称\n"
    "units,销售数量，单位为件\n"
    "note,订单备注\n"
)

QUESTION = "各销售大区的销量合计是多少？"


def _write_orders(directory) -> str:
    n = 200
    df = pd.DataFrame({
        "order_id": [f"ORD-{i:04d}" for i in range(1, n + 1)],
        "region": [REGIONS[i % len(REGIONS)] for i in range(n)],
        "customer": [f"客户{i % 80:03d}" for i in range(n)],
        "note": [f"订单备注{i:03d}：" + "这是一段刻意写长的备注内容，用来验证单值截断是否生效" * 5
                 for i in range(n)],
        "units": [10 + i % 90 for i in range(n)],
        "price": [round(9.9 + (i % 40) * 1.5, 2) for i in range(n)],
    })
    path = os.path.join(str(directory), "orders.csv")
    df.to_csv(path, index=False, encoding="utf-8")
    with open(os.path.join(str(directory), "orders.dict.csv"), "w", encoding="utf-8") as fh:
        fh.write(DICT_CSV)
    return path


@pytest.fixture(scope="module")
def orders(tmp_path_factory):
    """200 行订单表 + 数据字典。"""
    return _write_orders(tmp_path_factory.mktemp("egress_orders"))


@pytest.fixture(scope="module")
def captured(orders, tmp_path_factory):
    """跑一遍两种 agent 的真实链路，把 prompt 与审计结果一起缓存。

    图表目录显式指到临时目录：`conftest` 的隔离是函数级的，模块级夹具拿不到，
    不显式改就会把 PNG 写进仓库的 outputs/。
    """
    from app.tools import persist
    import app.react_agent as react_agent

    charts = tmp_path_factory.mktemp("egress_charts")
    mp = pytest.MonkeyPatch()
    mp.setattr(persist, "CHART_DIR", str(charts))
    mp.setattr(persist, "ensure_dirs", lambda: None)
    mp.setattr(react_agent, "ensure_dirs", lambda: None)
    try:
        audits = {agent: egress.audit(orders, QUESTION, agent=agent, code=CODE)
                  for agent in ("workflow", "react")}
    finally:
        mp.undo()
    data, _desc = load_data(orders)
    return {
        "path": orders,
        "audits": audits,
        "text": "\n".join(a.text() for a in audits.values()),
        "data": data,
    }


# ---------------------------------------------------------------- 四条断言

def test_egress_sample_rows_at_most_three(captured):
    """① 每张表的样例行 ≤ 3：结构段逐字等于 describe_df(n=3)，第 4 行不出现。"""
    assert egress.check_sample_rows(captured["data"], captured["text"]) == []


def test_egress_cell_values_at_most_40_chars(captured):
    """② 单值 ≤ 40 字：200 字的备注只能以截断形态出现。"""
    text = captured["text"]
    assert egress.check_cell_chars(captured["data"], text) == []
    # 正控：截断真的发生了，否则"整列没进 prompt"也会被上面那句判成通过
    long_value = captured["data"]["note"].iloc[0]
    assert long_value not in text
    assert schema_mod.clip(long_value, egress.EGRESS_MAX_CELL_CHARS) in text


def test_egress_no_full_column_values(captured):
    """③ 任一文本列的取值命中 ≤ 3：唯一 id / 客户 / 大区都只能露样本里那 3 个。"""
    text = captured["text"]
    assert egress.check_column_values(captured["data"], text) == []
    # 正控：数出来的确实是 3 而不是 0 —— 否则"整列根本没进 prompt"也会被算通过
    hits = [v for v in REGIONS if v in text]
    assert len(hits) == egress.EGRESS_MAX_COLUMN_HITS, hits


def test_egress_no_local_paths(captured):
    """④ 不含本机路径：规格正则 + 本次运行自己的绝对路径（数据集 / 图表目录 / 项目根）。"""
    text = captured["text"]
    forbidden = [*egress.own_paths(captured["path"]), str(captured["path"])]
    assert egress.check_local_path(text, forbidden) == []
    # 正控：图表这条通道真的走到了（chart() 只回 option，不带文件名，只有 plt 才出 PNG）
    assert "已生成图表" in text
    assert captured["audits"]["workflow"].prompts  # 至少有一条 prompt 承载了它


# ---------------------------------------------------------------- 证明它们会红

def test_egress_contract_matches_schema_constant():
    """合同值必须与实现常量一致；不一致意味着有人悄悄改了出境策略。"""
    assert schema_mod.MAX_CELL_CHARS == egress.EGRESS_MAX_CELL_CHARS
    assert egress.EGRESS_MAX_SAMPLE_ROWS == 3
    assert egress.EGRESS_MAX_COLUMN_HITS == 3


def test_egress_fails_when_limit_raised(orders, monkeypatch):
    """把 MAX_CELL_CHARS 放宽到 400，② 必须红 —— 否则这条断言只是自证。"""
    monkeypatch.setattr(schema_mod, "MAX_CELL_CHARS", 400)
    a = egress.audit(orders, QUESTION, agent="workflow", code=CODE)
    assert a.ok is False
    assert "cell_chars" in a.by_rule(), a.findings
    assert any("整段出境" in detail for detail in a.by_rule()["cell_chars"])


def test_egress_catches_full_column_in_dictionary(tmp_path):
    """字典枚举一列的全部取值 = 整列出境；审计必须抓到（字典也是用户上传的文件）。"""
    path = _write_orders(tmp_path)
    with open(os.path.join(str(tmp_path), "orders.dict.csv"), "w", encoding="utf-8") as fh:
        fh.write(DICT_CSV.replace("销售大区（地理分区）", "销售大区：" + "、".join(REGIONS)))
    a = egress.audit(path, QUESTION, agent="workflow", code="result = len(df)")
    assert a.ok is False
    details = a.by_rule().get("column_values", [])
    assert details and "region" in details[0] and "5 个取值" in details[0]


def test_egress_catches_absolute_path_the_regex_misses():
    """规格正则只认用户目录；仓库装在 D:\\ 时它一条都不命中，靠显式路径兜底。"""
    text = r"已生成图表 D:\Coding\claude\datachat\outputs\charts\chart_1.png"
    assert egress.PATH_PATTERN.search(text) is None          # 正则确实看不见
    assert egress.check_local_path(text, [r"D:\Coding\claude\datachat"])  # 显式路径抓得住
    # 正则那一半也要真的能红
    assert egress.check_local_path(r"读 C:\Users\HJH\data.csv 失败")
    assert egress.check_local_path("文件在 /home/hjh/data.csv")


def test_egress_covers_both_agents(captured):
    """两种 agent 的 prompt 拼法完全不同，缺一个等于只审了一半。"""
    for agent in ("workflow", "react"):
        a = captured["audits"][agent]
        assert a.prompts, f"{agent} 一次模型调用都没抓到"
        assert a.ok, (agent, a.findings)
    assert captured["audits"]["workflow"].executed
    assert captured["audits"]["react"].executed
