"""阶段 3.5 闸门的自检。

1) 脏化只改呈现（CI 里跑，用合成的小表，不下载）：脏表经 datachat 读入后能逐值还原成原表。
2) 题目 / 标准答案 / 判定规则自洽（CI 里跑）：25 题齐全、分布符合预登记、answers.json 的题面哈希与 questions.py 一致。
3) 真实数据上的"oracle"（需要先跑 scripts/gate/build_gate_data.py；数据不在仓库里，没下载就跳过）：
   在**脏表**上手写一份正确解，经沙箱执行后比较器必须判对 —— 证明每道题在 datachat 能看到的数据上确实可解、
   标准答案与脏表一致、比较器认得出正确答案。它不说明模型能答对。
"""
import importlib.util
import json
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "gate")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"gate_{name}", os.path.join(GATE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, GATE)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(GATE)
    return mod


build = _load("build_gate_data")
questions = _load("questions")
run_gate = _load("run_gate")
ANSWERS = json.load(open(os.path.join(ROOT, "docs", "gate", "answers.json"), encoding="utf-8"))


# ------------------------------------------------------------------ 1. 脏化只改呈现
def _raw_sample():
    return pd.DataFrame({
        "InvoiceNo": [536365, 536365, "C536379", 536380],
        "StockCode": ["85123A", 71053, "D", 22197],
        "Description": ["WHITE HANGING HEART", "WHITE METAL LANTERN", "Discount", None],
        "Quantity": [6, 6, -1, 12],
        "InvoiceDate": pd.to_datetime(["2010-12-01 08:26", "2010-12-01 08:26", "2010-12-01 09:41",
                                       "2011-01-05 17:03"]),
        "UnitPrice": [2.55, 3.39, 27.5, 0.85],
        "CustomerID": [17850.0, 17850.0, None, 12583.0],
        "Country": ["United Kingdom", "United Kingdom", "United Kingdom", "France"],
    })


def _restore(dirty: pd.DataFrame) -> pd.DataFrame:
    inv = {v: k for k, v in build.RETAIL_COLUMNS.items()}
    d = dirty.rename(columns=inv)
    d["InvoiceDate"] = pd.to_datetime(d["InvoiceDate"], format="%Y/%m/%d %H:%M")
    d["CustomerID"] = pd.to_numeric(d["CustomerID"].replace("未登记", None))
    return d


def test_dirty_retail_roundtrip(tmp_path):
    from app.tools.dataset import load_data
    raw = _raw_sample()
    path = str(tmp_path / "零售明细.csv")
    build.write_csv(build.dirty_retail(raw), path)
    assert open(path, "rb").read().decode("gb18030")          # GB18030 编码
    with pytest.raises(UnicodeDecodeError):
        open(path, "rb").read().decode("utf-8")
    df, desc = load_data(path)
    assert "gb18030" in desc and list(df.columns) == list(build.RETAIL_COLUMNS.values())
    assert df["客户编号"].tolist()[2] == "未登记" and df["开票时间"].iloc[0] == "2010/12/1 8:26"
    back = _restore(df)
    for col in ["Quantity", "UnitPrice", "CustomerID"]:
        pd.testing.assert_series_equal(back[col], raw[col].astype(back[col].dtype), check_names=False)
    assert back["InvoiceDate"].tolist() == raw["InvoiceDate"].tolist()
    assert back["InvoiceNo"].astype(str).tolist() == raw["InvoiceNo"].astype(str).tolist()
    assert back["StockCode"].astype(str).tolist() == raw["StockCode"].astype(str).tolist()


def test_report_variant_has_group_header_and_total(tmp_path):
    raw = _raw_sample()
    path = str(tmp_path / "零售报表.csv")
    groups = ["订单信息", "商品信息", "", "", "订单信息", "商品信息", "客户信息", ""]
    total = ["合计", "", "", str(int(raw["Quantity"].sum())), "", "", "", ""]
    build.write_csv(build.dirty_retail(raw), path, header_rows=[groups], footer=total)
    lines = open(path, "rb").read().decode("gb18030").splitlines()
    assert lines[0].startswith("订单信息,商品信息") and lines[1].startswith("发票号,商品编码")
    assert lines[-1] == "合计,,,23,,,,"
    body = pd.read_csv(path, encoding="gb18030", skiprows=1).iloc[:-1]   # 跳过分组行、去掉合计行就还原
    pd.testing.assert_series_equal(body["数量"].astype(int), raw["Quantity"], check_names=False)


# ------------------------------------------------------------------ 2. 题目 / 答案 / 规则自洽
def test_questions_preregistered_distribution():
    qs = questions.QUESTIONS
    assert len({q["id"] for q in qs}) == len(qs) == 25
    single = [q for q in qs if q["group"] == "single"]
    multi = [q for q in qs if q["group"] == "multi"]
    cats = lambda g: {c: sum(q["category"] == c for q in g) for c in {q["category"] for q in g}}  # noqa: E731
    assert cats(single) == {"聚合": 4, "过滤": 3, "排序": 2, "时间": 2, "占比": 2, "拒答": 2}
    assert cats(multi) == {"join聚合": 4, "join过滤": 2, "跨表排序": 2, "拒答": 2}
    assert all(bool(q.get("expect_refusal")) == (q["category"] == "拒答") for q in qs)
    assert any(q["dataset"] == questions.REPORT for q in single)        # 至少一张"报表导出"脏表
    assert len(questions.FAILURE_CLASSES) == 6


def test_answers_frozen_against_questions():
    """questions.py 改了而没重跑 verify_gate.py → 哈希对不上，测试失败（防止事后改题）。"""
    vg = _load("verify_gate")
    assert ANSWERS["questions_sha256"] == vg.questions_sha256()
    assert set(ANSWERS["answers"]) == {q["id"] for q in questions.QUESTIONS}
    for q in questions.QUESTIONS:
        a = ANSWERS["answers"][q["id"]]
        assert a["question"] == q["question"]
        assert (a["gold"]["kind"] == "refusal") == bool(q.get("expect_refusal"))


def test_verdict_rules(tmp_path):
    def report(single_ok, multi_ok, classes):
        rows, fails = [], iter(classes)
        for i in range(15):
            ok = i < single_ok
            rows.append({"id": f"s{i}", "group": "single", "executed": True, "human_correct": ok,
                         "failure_class": None if ok else next(fails)})
        for i in range(10):
            ok = i < multi_ok
            rows.append({"id": f"m{i}", "group": "multi", "executed": True, "human_correct": ok,
                         "failure_class": None if ok else next(fails)})
        p = tmp_path / f"r{single_ok}_{multi_ok}.json"
        p.write_text(json.dumps({"cases": rows}), encoding="utf-8")
        return run_gate.verdict(str(p), "phase35")

    v = report(13, 8, [1, 2, 3, 4])                       # 4 题失败、散落 4 类：不足 5 题，不触发分布规则
    assert v["single_verdict"].startswith("可用") and "只记录分布" in v["distribution_verdict"]
    v = report(11, 4, [2, 2, 2, 2, 2, 2, 3, 4, 2, 2])     # 8/10 落第 2 类 → 集中
    assert v["single_verdict"].startswith("可用") and v["multi_verdict"].startswith("有救")
    assert "集中：第 2 类" in v["distribution_verdict"]
    v = report(10, 3, [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 6, 1])   # 散落 6 类 → 系统性
    assert v["single_verdict"].startswith("暂停阶段 4") and "系统性" in v["distribution_verdict"]
    v = report(7, 4, [1, 1, 1, 1, 2, 2, 2, 2, 1, 2, 2, 2, 1, 1])   # 2 类、最大类 <60% → 中间区间
    assert v["single_verdict"].startswith("路线重估") and "中间区间" in v["distribution_verdict"]


def _labeled_report(tmp_path, agent, wrong, name="r.json"):
    rows = [{"id": f"s{i:02d}", "group": "single", "executed": True} for i in range(1, 16)]
    rows += [{"id": f"m{i:02d}", "group": "multi", "executed": True} for i in range(1, 11)]
    for r in rows:
        r["human_correct"] = r["id"] not in wrong
        r["failure_class"] = None if r["human_correct"] else 2
    p = tmp_path / name
    p.write_text(json.dumps({"agent": agent, "labeled_by": "Hark 预标注，待 S 终审", "cases": rows}),
                 encoding="utf-8")
    return str(p)


def test_verdict_regression_profile(tmp_path):
    """[25]：m13 回归门槛——错题必须落在 allowed_fail 里；门槛原文与文件哈希写进 verdict。"""
    v = run_gate.verdict(_labeled_report(tmp_path, "react", {"s02", "m10"}), "m13")
    assert v["regression_verdict"] == "无回归" and v["single_min"] == "14/15" and v["multi_min"] == "9/10"
    assert v["profile"] == "m13" and len(v["thresholds_sha256"]) == 12 and v["thresholds"]["kind"] == "regression"
    assert v["labels_final"] is False                                      # 预标注
    v = run_gate.verdict(_labeled_report(tmp_path, "react", {"s02", "s04", "m01", "m10"}), "m13")
    assert v["single_regressions"] == ["s04"] and v["multi_regressions"] == ["m01"]
    assert v["regression_verdict"].startswith("有回归")
    v = run_gate.verdict(_labeled_report(tmp_path, "react", set()), "m13")   # 预期失败的题答对：记录，不算回归
    assert v["single_unexpected_pass"] == ["s02"] and v["regression_verdict"] == "无回归"
    v = run_gate.verdict(_labeled_report(tmp_path, "workflow", {"s02", "s04", "s09", "s12"}), "m13")
    assert v["regression_verdict"] == "无回归" and v["single_min"] == "11/15" and v["multi_min"] == "10/10"
    v = run_gate.verdict(_labeled_report(tmp_path, "workflow", {"s02", "m03"}), "m13")
    assert v["multi_regressions"] == ["m03"]


def test_verdict_requires_known_profile(tmp_path):
    p = _labeled_report(tmp_path, "react", {"s02"})
    with pytest.raises(SystemExit):
        run_gate.verdict(p, "nope")


@pytest.mark.parametrize("name", ["gate_20261012_104407_react.json", "gate_20261012_104936_workflow.json"])
def test_phase35_profile_reproduces_final_verdict(tmp_path, name):
    """阈值从常量移到 thresholds.json 后，10-12 两份终审报告的结论不变。"""
    src = json.load(open(os.path.join(ROOT, "docs", "eval", name), encoding="utf-8"))
    p = tmp_path / name
    p.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    v = run_gate.verdict(str(p), "phase35")
    for k in ("single", "multi", "single_verdict", "multi_verdict", "distribution_verdict", "failure_distribution"):
        assert v[k] == src["verdict"][k], k


# ------------------------------------------------------------------ 3. 真实数据上的 oracle
HAVE_DATA = all(os.path.exists(os.path.join(ROOT, p)) for p in
                (questions.RETAIL, questions.REPORT, questions.OLIST))

_PREP_R = """d = df.copy()
d['amt'] = d['数量'] * d['单价（英镑）']
d['t'] = pd.to_datetime(d['开票时间'], format='%Y/%m/%d %H:%M')
"""
_PREP_REPORT = """d = df.iloc[1:].copy()
d.columns = df.iloc[0].tolist()
d = d[d['发票号'] != '合计']
d['数量'] = pd.to_numeric(d['数量'])
d['单价（英镑）'] = pd.to_numeric(d['单价（英镑）'])
d['amt'] = d['数量'] * d['单价（英镑）']
d['t'] = pd.to_datetime(d['开票时间'], format='%Y/%m/%d %H:%M')
"""
_PREP_O = """o, c, i, p = dfs['orders'], dfs['customers'], dfs['order_items'], dfs['order_payments']
rv, pr, s, tr = dfs['order_reviews'], dfs['products'], dfs['sellers'], dfs['category_translation']
"""
ORACLE = {
    "s01": _PREP_R + "result = round(d.loc[d['t'].dt.year == 2011, 'amt'].sum(), 2)",
    "s02": "result = df.loc[df['客户编号'] != '未登记', '客户编号'].nunique()",
    "s03": _PREP_R + "result = round(d.groupby('发票号')['amt'].sum().mean(), 2)",
    "s04": _PREP_REPORT + "result = int(d.loc[d['国家'] != 'United Kingdom', '数量'].sum())",
    "s05": "result = df.loc[df['发票号'].astype(str).str.startswith('C'), '发票号'].nunique()",
    "s06": _PREP_REPORT + "result = int((d['单价（英镑）'] > 100).sum())",
    "s07": _PREP_R + "result = sorted(d.loc[(d['t'].dt.year == 2011) & (d['t'].dt.month == 12), '国家'].unique())",
    "s08": _PREP_R + "result = d.groupby('国家')['amt'].sum().nlargest(5).index.tolist()",
    "s09": "result = df.groupby('商品描述')['数量'].sum().idxmax()",
    "s10": _PREP_REPORT + "result = str(d.groupby(d['t'].dt.to_period('M'))['amt'].sum().idxmax())",
    "s11": _PREP_R + "y = d[d['t'].dt.year == 2011]\nresult = y.groupby(y['t'].dt.quarter)['amt'].sum().round(2)",
    "s12": "result = round((df['客户编号'] == '未登记').mean() * 100, 2)",
    "s13": _PREP_R + "result = round(d.loc[d['国家'] == 'United Kingdom', 'amt'].sum() / d['amt'].sum() * 100, 2)",
    "s14": "result = '无法回答：数据中没有成本或进价字段'",
    "s15": "result = '无法回答：数据中没有客户性别字段'",
    "m01": _PREP_O + "result = o.merge(c, on='customer_id').groupby('customer_state')['order_id'].nunique()",
    "m02": _PREP_O + ("m = p.merge(o, on='order_id').merge(c, on='customer_id')\n"
                      "result = round(m.loc[m['customer_state'] == 'SP', 'payment_value'].sum(), 2)"),
    "m03": _PREP_O + "result = i.merge(s, on='seller_id').groupby('seller_state')['price'].mean().round(2)",
    "m04": _PREP_O + ("ids = rv.loc[rv['review_score'] == 1, 'order_id'].unique()\nx = o[o['order_id'].isin(ids)]\n"
                      "dd = pd.to_datetime(x['order_delivered_customer_date']) - pd.to_datetime(x['order_purchase_timestamp'])\n"
                      "result = round(dd.dt.total_seconds().div(86400).mean(), 2)"),
    "m05": _PREP_O + ("cats = tr.loc[tr['product_category_name_english'] == 'health_beauty', 'product_category_name']\n"
                      "pid = pr.loc[pr['product_category_name'].isin(cats), 'product_id']\n"
                      "m = i[i['product_id'].isin(pid)].merge(o, on='order_id').merge(c, on='customer_id')\n"
                      "result = m['customer_unique_id'].nunique()"),
    "m06": _PREP_O + ("t = pd.to_datetime(o['order_purchase_timestamp'])\n"
                      "ids = o.loc[(t.dt.year == 2018) & (t.dt.month == 8) & (o['order_status'] == 'canceled'), 'order_id']\n"
                      "result = round(p.loc[p['order_id'].isin(ids), 'payment_value'].sum(), 2)"),
    "m07": _PREP_O + ("m = i.merge(pr, on='product_id').merge(tr, on='product_category_name')\n"
                      "result = m.groupby('product_category_name_english')['price'].sum().nlargest(3).index.tolist()"),
    "m08": _PREP_O + "result = o.merge(c, on='customer_id').groupby('customer_city')['order_id'].nunique().nlargest(5).index.tolist()",
    "m09": "result = '无法回答：数据中没有客户年龄字段'",
    "m10": "result = '无法回答：数据中没有成本字段，算不出利润'",
}


@pytest.fixture(scope="module")
def gate_data():
    from app.tools.dataset import load_data
    cache = {}

    def get(path):
        if path not in cache:
            cache[path] = load_data(os.path.join(ROOT, path))[0]
        return cache[path]
    return get


@pytest.mark.skipif(not HAVE_DATA, reason="闸门数据未下载（python scripts/gate/build_gate_data.py）")
@pytest.mark.parametrize("q", questions.QUESTIONS, ids=lambda q: q["id"])
def test_oracle_solvable_on_dirty_data(q, gate_data, chart_path):
    from app.tools.dataset import copy_data
    from app.tools.sandbox import run_code
    result, _, err = run_code(ORACLE[q["id"]], copy_data(gate_data(q["dataset"])), chart_path, timeout=120)
    assert err is None, err
    match = run_gate.auto_judge(result, q, ANSWERS["answers"][q["id"]])
    assert match is not None, f"{q['id']}: {result!r}"
