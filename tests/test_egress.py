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


# ---------------------------------------------------------------- ③ 的嵌套判据

# 零售明细的真实形态：前 3 行就是这三个长值；数据集里另有 757 个带尾空格的脏值，
# 其中 "HEART T-LIGHT HOLDER " 恰好是第一个长值的后缀 + 一个列分隔空格。
_SAMPLE_VALUES = ["WHITE HANGING HEART T-LIGHT HOLDER",
                  "WHITE METAL LANTERN",
                  "CREAM CUPID HEARTS COAT HANGER"]
_NESTED_VALUES = ["HEART T-LIGHT HOLDER", "HEART T-LIGHT HOLDER "]
_FOURTH_VALUE = "REGENCY CAKESTAND 3 TIER"     # 列里存在但样本不外露的第 4 个真值


def _catalog_df():
    return pd.DataFrame({"商品描述": _SAMPLE_VALUES + _NESTED_VALUES + [_FOURTH_VALUE]})


def test_nested_value_is_not_a_separate_egress():
    """子串不等于独立出境：长值出境时，作为它子串的短值不算多一条。

    假红的代价不是多报一条，是这条断言在真实数据上永远红 —— 看的人就开始忽略它。
    """
    text = "".join(f"| {v} | 1 |\n" for v in _SAMPLE_VALUES)
    assert egress.check_column_values(_catalog_df(), text) == []


def test_nested_filter_keeps_value_that_also_appears_alone():
    """短值除了藏在长值里，还独立出现过一次 —— 那才是真的多出境了一个值。"""
    text = "| WHITE HANGING HEART T-LIGHT HOLDER |\nHEART T-LIGHT HOLDER"
    kept = egress._drop_nested_hits(["WHITE HANGING HEART T-LIGHT HOLDER", "HEART T-LIGHT HOLDER"], text)
    assert kept == ["WHITE HANGING HEART T-LIGHT HOLDER", "HEART T-LIGHT HOLDER"]


def test_trailing_space_variant_is_not_a_separate_egress():
    """pandas 渲染时列右补空格，"长值 + 空格"会拼出带尾空格的脏值；那一个空格判不了，抹掉。"""
    text = "| WHITE HANGING HEART T-LIGHT HOLDER |\n"
    assert egress._drop_nested_hits(["WHITE HANGING HEART T-LIGHT HOLDER",
                                     "HEART T-LIGHT HOLDER "], text) == ["WHITE HANGING HEART T-LIGHT HOLDER"]


def test_fourth_real_value_still_turns_red():
    """去掉嵌套之后仍然超额才叫真发现：第 4 个真实取值一旦出境必须报。"""
    text = "".join(f"| {v} | 1 |\n" for v in _SAMPLE_VALUES + [_FOURTH_VALUE])
    details = egress.check_column_values(_catalog_df(), text)
    assert details and "4 个取值" in details[0], details


# ---------------------------------------------------------------- ③ 的多表切分

def _two_table_data():
    """两张表有同名列，各 4 个取值 —— 各露 3 行，合起来是 6 个"命中"。"""
    return {"a": pd.DataFrame({"category": ["a1", "a2", "a3", "a4"]}),
            "b": pd.DataFrame({"category": ["b1", "b2", "b3", "b4"]})}


def test_multi_table_shared_column_does_not_cross_count():
    """A 的样例行里出现的值不算 B 那一列在出境：olist 的 category 两张表都有。"""
    data = _two_table_data()
    text = "\n".join(schema_mod.describe_df(df, n=3) for df in data.values())
    assert egress.check_column_values(data, text) == []


def test_multi_table_leak_outside_blocks_still_turns_red():
    """块外的通道（结果回灌）不参与抹除：第 4 个取值回灌进来必须报。"""
    data = _two_table_data()
    text = "\n".join([schema_mod.describe_df(df, n=3) for df in data.values()] + ["结果：a4"])
    details = egress.check_column_values(data, text)
    assert details and "表 a.category" in details[0] and "4 个取值" in details[0], details


def test_unique_text_dedupes_after_stringifying():
    """'2.55' 与 2.55 是两个唯一值、一个字符串：转完必须去重，否则同一个值数两次。"""
    s = pd.Series(["2.55", 2.55, "3.39", None])
    assert egress._unique_text(s) == ["2.55", "3.39"]


def test_value_and_its_trimmed_twin_count_once():
    """'家居' 与 '家居 ' 抹完空白是同一个取值：渲染里分不出来，只能算一条。"""
    text = "| 数码 | 服饰 | 家居 | 3C |"
    kept = egress._drop_nested_hits(["数码", "服饰", "家居", "家居 "], text)
    assert kept == ["数码", "服饰", "家居"]


# ---------------------------------------------------------------- ③ 的取值形态判据

# 纯数字/标点且 ≤3 字符：在 prompt 里必然处处命中，命中了也不说明出境。
_UNTESTABLE_VALUES = ["10", "01", "00", "5", " ", "-", ",", "## ", " 4 ", "12", "39", ""]
# 有可辨识内容的：标识符、CJK、≥4 字符的数字（手机号/身份证）。
_TESTABLE_VALUES = ["S01", "K100", "Top", "服饰", "运营", "数量",
                    "2.55", "13800138000", "110101199001011234"]


@pytest.mark.parametrize("value", _UNTESTABLE_VALUES)
def test_testable_rejects_characterless_short_values(value):
    """不可判的是"不含可辨识字符"，不是"短"：'10' 会命中 review_id 哈希与日期。"""
    assert not egress._testable(value)


@pytest.mark.parametrize("value", _TESTABLE_VALUES)
def test_testable_keeps_values_with_recognizable_content(value):
    """'S01' 是门店码，'13800138000' 是手机号 —— 与 _distinctive 的关键分歧。"""
    assert egress._testable(value)


def test_short_store_codes_still_count_as_egress():
    """3 字符 ASCII 的 S01 必须报：套 _distinctive 会把它一起豁免掉，那是真泄漏。"""
    df = pd.DataFrame({"store": ["S01", "S02", "S03", "S04", "S05"]})
    details = egress.check_column_values(df, "store：S01、S02、S03、S04、S05")
    assert details and "5 个取值" in details[0], details


def test_phone_numbers_are_not_exempted_as_a_numeric_column():
    """纯数字但 ≥4 字符仍然计数：数字型文本列豁免会让手机号/身份证整列失去保护。"""
    phones = ["13800138001", "13800138002", "13800138003", "13800138004"]
    df = pd.DataFrame({"phone": phones})
    details = egress.check_column_values(df, "客户电话：" + "、".join(phones))
    assert details and "4 个取值" in details[0], details


def test_untestable_hits_are_reported_as_notes_not_findings():
    """跳过必须留痕：静默跳过等于把"我没能判"伪装成"这里没问题"。"""
    df = pd.DataFrame({"title": ["10", "01", "5", " ", ",", "## "]})
    text = "## 表 dfs 2018-03-10 , 5 01"
    notes = []
    assert egress.check_column_values(df, text, notes) == []
    assert notes and "无法用子串法判定" in notes[0] and "6 个" in notes[0], notes


def test_real_olist_shape_goes_green_but_keeps_a_note():
    """olist 的形态：标题列前 3 行全 nan，命中全是模板/日期/哈希 —— 该绿，但要有记录。"""
    df = pd.DataFrame({"review_comment_title": [None, None, None, "10", "01", "## "]})
    text = "## 表 dfs['order_reviews']  2018-03-10 00:00:00"
    notes = []
    assert egress.check_column_values(df, text, notes) == []
    assert notes, notes
