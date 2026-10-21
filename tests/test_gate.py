"""阶段 3.5 闸门的自检。

1) 脏化只改呈现（CI 里跑，用合成的小表，不下载）：脏表经 datachat 读入后能逐值还原成原表。
2) 题目 / 标准答案 / 判定规则自洽（CI 里跑）：25 题齐全、分布符合预登记、answers.json 的题面哈希与 questions.py 一致。
3) 真实数据上的"oracle"（需要先跑 scripts/gate/build_gate_data.py；数据不在仓库里，没下载就跳过；
   设 DATACHAT_REQUIRE_GATE_DATA=1 时缺数据直接判红 —— CI 的 gate-oracle job 就是这么跑的，G1）：
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


def _all_correct_report(tmp_path, labeled_by, name):
    rows = [{"id": f"s{i:02d}", "group": "single", "executed": True, "human_correct": True,
             "failure_class": None} for i in range(1, 16)]
    rows += [{"id": f"m{i:02d}", "group": "multi", "executed": True, "human_correct": True,
              "failure_class": None} for i in range(1, 11)]
    p = tmp_path / name
    p.write_text(json.dumps({"agent": "react", "labeled_by": labeled_by, "cases": rows}), encoding="utf-8")
    return str(p)


def test_labels_final_is_written_both_ways(tmp_path):
    """[30]：labels_final 必须显式写 True/False。

    只写 False（原来只有 `if "待 S 终审" in ...`）时"已终审"没法用这个字段表达 —— 实测把
    labeled_by 改成"S 终审通过"后重跑，键会整个消失，然后被手改成终审态的报告里仍留着上一轮的
    False（10-14 两份基线就是这个状态）。labeled_by 为空时不写这个键：没人署名不算终审。
    """
    assert run_gate.verdict(_all_correct_report(tmp_path, "Hark 预标注，待 S 终审", "pre.json"),
                            "m13")["labels_final"] is False
    assert run_gate.verdict(_all_correct_report(tmp_path, "Hark 预标注；S 终审通过（2026-10-15）", "final.json"),
                            "m13")["labels_final"] is True
    assert "labels_final" not in run_gate.verdict(_all_correct_report(tmp_path, "", "anon.json"), "m13")


def test_thresholds_hash_is_line_ending_agnostic(tmp_path, monkeypatch):
    """[30]：门槛哈希不能随工作区签出行尾变。

    本仓库 core.autocrlf=true → 工作区是 CRLF、git 对象是 LF。不规范化的话本机跑
    `--verdict` 写出的哈希和基线报告里记的对不上（实测 8703d010bbe3 vs 4992a4016355），
    哈希本来要证明"用的是哪一版门槛"，这样一来就失效了。
    同一份内容各写一个 LF、一个 CRLF 文件分别算，在哪个系统上跑都真的在测规范化（CI 是 LF）。
    """
    lf = open(run_gate.THRESHOLDS, "rb").read().replace(b"\r\n", b"\n")
    assert b"\n" in lf
    shas = []
    for name, data in (("lf.json", lf), ("crlf.json", lf.replace(b"\n", b"\r\n"))):
        p = tmp_path / name
        p.write_bytes(data)
        monkeypatch.setattr(run_gate, "THRESHOLDS", str(p))
        shas.append(run_gate.load_profile("m13")[1])
    assert shas[0] == shas[1]


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
def _gate_path(rel):
    """闸门数据路径的唯一出口：HAVE_DATA 与 gate_data fixture 共用（G1）。
    DATACHAT_GATE_DATA_ROOT 只给子进程单测用，指向空目录时本机有真数据也必须报缺失。"""
    return os.path.join(os.environ.get("DATACHAT_GATE_DATA_ROOT") or ROOT, rel)


REQUIRE_DATA = os.environ.get("DATACHAT_REQUIRE_GATE_DATA") == "1"
MISSING_DATA = [p for p in (questions.RETAIL, questions.REPORT, questions.OLIST) if not os.path.exists(_gate_path(p))]
HAVE_DATA = not MISSING_DATA

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
    "s01": _PREP_R + "result = round(d.loc[d['t'].dt.year == 2011, 'amt'].sum(), 2) + 1000  # 反向演示，revert",
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
            cache[path] = load_data(_gate_path(path))[0]
        return cache[path]
    return get


# skipif 在函数体之前生效，所以开关要让 skipif 自己知道：要求数据时不 skip，进函数体第一行报"数据缺失"。
# gate_data 是惰性 fixture（返回闭包、不碰磁盘），这一行一定先于任何 load_data。
@pytest.mark.skipif(not HAVE_DATA and not REQUIRE_DATA, reason="闸门数据未下载（python scripts/gate/build_gate_data.py）")
@pytest.mark.parametrize("q", questions.QUESTIONS, ids=lambda q: q["id"])
def test_oracle_solvable_on_dirty_data(q, gate_data, chart_path):
    if MISSING_DATA:
        pytest.fail(f"闸门数据缺失：{MISSING_DATA}（DATACHAT_REQUIRE_GATE_DATA=1；先跑 python scripts/gate/build_gate_data.py）")
    from app.tools.dataset import copy_data
    from app.tools.sandbox import run_code
    result, _, err = run_code(ORACLE[q["id"]], copy_data(gate_data(q["dataset"])), chart_path, timeout=120)
    assert err is None, err
    match = run_gate.auto_judge(result, q, ANSWERS["answers"][q["id"]])
    assert match is not None, f"{q['id']}: {result!r}"


# ------------------------------------------------------------------ 3b. G1：oracle 上 CI 的守卫
import subprocess  # noqa: E402

ORACLE_NODE = "tests/test_gate.py::test_oracle_solvable_on_dirty_data"


def _run_oracle_subprocess(tmp_path, require):
    env = {k: v for k, v in os.environ.items() if k != "DATACHAT_REQUIRE_GATE_DATA"}
    env["DATACHAT_GATE_DATA_ROOT"] = str(tmp_path / "empty")   # 空目录：本机有真数据也必须视为缺失
    (tmp_path / "empty").mkdir()
    if require:
        env["DATACHAT_REQUIRE_GATE_DATA"] = "1"
    xml = tmp_path / "gate.xml"
    r = subprocess.run([sys.executable, "-m", "pytest", ORACLE_NODE, "-q", "-p", "no:cacheprovider",
                        f"--junitxml={xml}"], cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    check_junit = _load("check_junit")
    return r, check_junit.counts(str(xml))


def test_g1_require_data_fails_with_plain_message(tmp_path):
    r, n = _run_oracle_subprocess(tmp_path, require=True)
    assert r.returncode != 0
    assert "闸门数据缺失" in r.stdout
    assert n == {"tests": len(questions.QUESTIONS), "failures": len(questions.QUESTIONS), "errors": 0, "skipped": 0}


def test_g1_without_require_still_skips(tmp_path):
    r, n = _run_oracle_subprocess(tmp_path, require=False)
    assert r.returncode == 0, r.stdout[-2000:]
    assert n == {"tests": len(questions.QUESTIONS), "failures": 0, "errors": 0, "skipped": len(questions.QUESTIONS)}


_FAKE = {"raw/a.xlsx": b"xlsx-bytes", "olist/x.csv": b"x", "olist/y.csv": b"y", "retail/r.csv": "零售".encode("gb18030")}


def _fake_tree(root):
    # root 用 tmp_path / "gate"：conftest 的 autouse fixture 会在 tmp_path 下建 charts/
    for k, data in _FAKE.items():
        p = root.joinpath(*k.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return {k: build.sha12(v) for k, v in _FAKE.items()}


def test_g1_check_passes_on_exact_tree(tmp_path):
    assert build.check(str(tmp_path / "gate"), _fake_tree(tmp_path / "gate")) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda r: (r / "olist" / "y.csv").unlink(), "缺失：olist/y.csv"),
    (lambda r: (r / "olist" / "x.csv").write_bytes(b"X"), "指纹不符：olist/x.csv"),
    (lambda r: (r / "olist" / "z.csv").write_bytes(b"z"), "多余：olist/z.csv"),
    (lambda r: (r / "retail" / "残留.csv").write_bytes(b"z"), "多余：retail/残留.csv"),
    (lambda r: (r / "stray.txt").write_bytes(b"z"), "多余：stray.txt"),
    (lambda r: (r / "junk").mkdir(), "多余：junk/"),
], ids=["missing", "byte", "extra-olist", "extra-retail", "extra-top-file", "extra-top-dir"])
def test_g1_check_rejects(tmp_path, mutate, expect):
    exp = _fake_tree(tmp_path / "gate")
    mutate(tmp_path / "gate")
    problems = build.check(str(tmp_path / "gate"), exp)
    assert any(p.startswith(expect) for p in problems), problems
    if expect.startswith("指纹不符"):
        p = next(p for p in problems if p.startswith(expect))
        assert exp["olist/x.csv"] in p and build.sha12(b"X") in p     # 期望值与实际值都打出来


def test_g1_check_is_read_only_and_never_fetches(tmp_path, monkeypatch):
    exp = _fake_tree(tmp_path / "gate")
    monkeypatch.setattr(build, "fetch", lambda url: (_ for _ in ()).throw(AssertionError("check 不许下载")))
    monkeypatch.setattr(build.pd, "read_excel", lambda *a, **k: (_ for _ in ()).throw(AssertionError("check 不许读 Excel")))
    snap = lambda: sorted((str(p), p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else b"") for p in (tmp_path / "gate").rglob("*"))
    (tmp_path / "gate" / "olist" / "x.csv").write_bytes(b"X")   # 让它走一遍"不符"的分支
    before = snap()
    assert build.check(str(tmp_path / "gate"), exp)
    assert snap() == before


def test_g1_expected_files_cover_registered_constants():
    exp = build.expected_files()
    assert set(exp) == ({"raw/Online Retail.xlsx"} | {f"olist/{v}" for v in build.OLIST_SHORT.values()}
                        | {"retail/零售明细.csv", "retail_report/零售报表.csv"})
    assert questions.RETAIL.endswith(next(k for k in exp if k.startswith("retail/")))
    assert questions.REPORT.endswith(next(k for k in exp if k.startswith("retail_report/")))


def _junit(tmp_path, tests, failures=0, errors=0, skipped=0, wrapped=True):
    suite = f'<testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/>'
    p = tmp_path / "j.xml"
    p.write_text(f"<testsuites>{suite}</testsuites>" if wrapped else suite, encoding="utf-8")
    return p


def _check_junit_cli(path):
    # 用真实的命令行形状跑：证明 scripts/gate 不是包时裸 import questions 可用
    return subprocess.run([sys.executable, os.path.join(GATE, "check_junit.py"), str(path)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


@pytest.mark.parametrize("wrapped", [True, False])
def test_g1_check_junit_accepts_all_passed(tmp_path, wrapped):
    r = _check_junit_cli(_junit(tmp_path, len(questions.QUESTIONS), wrapped=wrapped))
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("kw", [
    {"skipped": None}, {"tests": -1}, {"failures": 1}, {"errors": 1},
], ids=["all-skipped", "one-param-lost", "one-failed", "one-error"])
def test_g1_check_junit_rejects(tmp_path, kw):
    n = len(questions.QUESTIONS)
    args = {"tests": n, "failures": 0, "errors": 0, "skipped": 0}
    if "skipped" in kw:
        args["skipped"] = n
    elif "tests" in kw:
        args["tests"] = n - 1
    else:
        args.update(kw)
    r = _check_junit_cli(_junit(tmp_path, **args))
    assert r.returncode == 1
    assert f"'tests': {n}" in r.stdout and f"实际 {args}" in r.stdout     # 期望与实际都打出来


# ------------------------------------------------------------------ 4. A1 错题复跑（m13r）
import subprocess
from types import SimpleNamespace

ENV = {"git_sha": "abc1234", "agent": "react", "use_dictionary": True, "model": "deepseek-chat",
       "temperature": 0.0, "base_url_host": "api.deepseek.com", "python": "3.12.0", "pandas": "2.2.3"}


def _rerun_report(tmp_path, wrong, agent="react", name="r.json", main_kind=None, **extra):
    """合成主报告：题号取真实的 25 题（复跑要从 questions.py / answers.json 取题面），人工已判完。"""
    rows = []
    for q in questions.QUESTIONS:
        ok = q["id"] not in wrong
        rows.append({"id": q["id"], "group": q["group"], "executed": True, "match": ok,
                     "error_kind": (main_kind or {}).get(q["id"]),
                     "human_correct": ok, "failure_class": None if ok else 2})
    data = {**ENV, "agent": agent, "labeled_by": "S 终审通过", "cases": rows, **extra}
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _res(match=True, executed=True, error_kind=None):
    """analyze 的桩：result 里带上希望比较器给出的 match（auto_judge 一并打桩）。"""
    return SimpleNamespace(executed=executed, error_kind=error_kind, error=None if executed else "x",
                           answer="答", result={"want": match} if executed else None, code="result = 1",
                           attempts=1, usage=SimpleNamespace(total_tokens=1, reported=True), warnings=[],
                           unverified_numbers=[], charts=[], chart_calls=0, chart_errors=[],
                           chart_internal_errors=[], charts_discarded=0, steps=[])


@pytest.fixture
def stub(monkeypatch):
    """按题号排好的结果队列；calls 记录每次调用的题号。"""
    state = SimpleNamespace(queue={}, default=lambda: _res(True), calls=[], env=dict(ENV))
    qtext = {q["question"]: q["id"] for q in questions.QUESTIONS}

    def fake_analyze(path, question, **kw):
        qid = qtext[question]
        state.calls.append(qid)
        q = state.queue.get(qid)
        r = q.pop(0) if q else state.default()
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(run_gate, "_analyze", lambda: fake_analyze)
    monkeypatch.setattr(run_gate, "_current_env", lambda agent, use_dict: (None, {**state.env, "agent": agent,
                                                                                  "use_dictionary": use_dict}))
    monkeypatch.setattr(run_gate, "auto_judge",
                        lambda actual, q, ans: actual.get("want") if isinstance(actual, dict) else None)
    return state


def _rr(path, **kw):
    kw.setdefault("agent", "react")
    kw.setdefault("use_dictionary", True)
    return run_gate.rerun(path, "m13r", **kw)


def _load_json(path):
    return json.load(open(path, encoding="utf-8"))


def _sign(path, value=True, ids=None, failure_class=None, only_attempts=None):
    d = _load_json(path)
    for r in d["reruns"]:
        if r["valid"] and (ids is None or r["id"] in ids) and (only_attempts is None or r["attempt"] in only_attempts):
            r["human_correct"] = value
            if value is False and failure_class:
                r["failure_class"] = failure_class
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)


def _exit_code(excinfo):
    return excinfo.value.code


def test_rerun_kinds_whitelist_covers_error_kinds():
    from app.core.events import ERROR_KINDS
    valid, invalid = set(run_gate.RERUN_VALID_KINDS), set(run_gate.RERUN_INVALID_KINDS)
    assert valid | invalid == set(ERROR_KINDS) | {None}
    assert not valid & invalid


def test_m13r_agents_equal_m13():
    """m13r 复制 m13 的 agents：两份来源用断言钉住。"""
    m13, _ = run_gate.load_profile("m13")
    m13r, _ = run_gate.load_profile("m13r")
    assert m13r["agents"] == m13["agents"] and m13r["rerun"] == {"times": 3, "max_makeup": 1}


def test_rerun_selection(tmp_path, stub):
    """只复跑名单外错题；allowed_fail 里的错题（s02）、意外答对（m10）都不复跑；--only 补进人工判对的题。"""
    p = _rerun_report(tmp_path, {"s02", "s04", "m01"})
    v = _rr(p)
    assert sorted(set(stub.calls)) == ["m01", "s04"] and len(stub.calls) == 6
    assert v["single_rerun_candidates"] == ["s04"] and v["multi_rerun_candidates"] == ["m01"]
    assert "m10" not in stub.calls
    stub.calls.clear()
    _rr(p, only=["m05"], reason="比较器漏判")
    assert stub.calls == ["m05"] * 3                    # 已复跑的 s04 / m01 不重跑


def test_rerun_refuses_undeclared_repeat_and_only_replaces(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04"})
    _rr(p)
    old = [r for r in _load_json(p)["reruns"] if r["id"] == "s04"]
    with pytest.raises(SystemExit) as e:
        _rr(p)
    assert _exit_code(e) == 3
    with pytest.raises(SystemExit) as e:
        _rr(p, only=["s04"])                            # 没有 --reason
    assert _exit_code(e) == 3
    stub.default = lambda: _res(False)
    _rr(p, only=["s04"], reason="限额用完后充值重跑")
    d = _load_json(p)
    assert [r["match"] for r in d["reruns"] if r["id"] == "s04"] == [False] * 3
    h = d["rerun_history"]
    assert len(h) == 1 and h[0]["id"] == "s04" and h[0]["reason"] == "限额用完后充值重跑"
    assert h[0]["replaced_attempts"] == old and h[0]["git_sha"] == ENV["git_sha"]


def test_rerun_interrupted_keeps_complete_rows_and_resumes(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04"})
    stub.queue["s04"] = [_res(True), KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        _rr(p)
    d = _load_json(p)                                   # 原子落盘：完整 1 行，可读
    assert [r["attempt"] for r in d["reruns"]] == [1]
    assert not os.path.exists(p + ".tmp")
    v = run_gate.verdict(p, "m13r")
    assert v["single_rerun_invalid"][0]["valid"] == 1 and v["exit_code"] == 2
    _rr(p, only=["s04"], reason="进程中断后续跑")
    d = _load_json(p)
    assert [r["attempt"] for r in d["reruns"]] == [1, 2, 3] and len(d["rerun_history"][0]["replaced_attempts"]) == 1


def test_rerun_attempt_counts(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04", "s05", "s06"})
    stub.queue["s05"] = [_res(error_kind="llm", executed=False), _res(), _res(), _res()]
    stub.queue["s06"] = [_res(error_kind="cancelled", executed=False), _res(),
                         _res(error_kind="dataset", executed=False), _res()]
    v = _rr(p)
    assert stub.calls.count("s04") == 3                 # 全有效：不补跑
    assert stub.calls.count("s05") == 4                 # 1 次无效：补 1 次
    assert stub.calls.count("s06") == 4                 # 补后仍不足 3 次有效：停在 4 次
    inv = v["single_rerun_invalid"]
    assert [x["id"] for x in inv] == ["s06"] and inv[0]["valid"] == 2 and inv[0]["total"] == 4
    assert v["exit_code"] == 2


_real_auto_judge = run_gate.auto_judge


def test_rerun_match_tristate(tmp_path, stub, monkeypatch):
    """executed=False：有效、记为答错；executed=True 但比较器崩了（match=None）：无效，补跑。"""
    p = _rerun_report(tmp_path, {"s04", "s05"})
    stub.queue["s04"] = [_res(executed=False, error_kind="execution"), _res(), _res()]
    _rr(p)
    rows = [r for r in _load_json(p)["reruns"] if r["id"] == "s04"]
    assert len(rows) == 3 and rows[0]["valid"] is True and rows[0]["match"] is None

    import app.eval.runner as runner

    def boom(*a, **k):
        raise RuntimeError("比较器崩了")
    monkeypatch.setattr(runner, "score_detail", boom)
    monkeypatch.setattr(run_gate, "auto_judge", _real_auto_judge)
    stub.queue["s05"] = [_res(), _res(), _res(), _res()]
    _rr(p, only=["s05"], reason="测比较器崩溃")
    rows = [r for r in _load_json(p)["reruns"] if r["id"] == "s05"]
    assert len(rows) == 4 and all(r["executed"] and r["match"] is None and not r["valid"] for r in rows)



def test_rerun_verdict_requires_signatures(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04", "s05"})
    stub.queue["s05"] = [_res(), _res(False), _res()]
    v = _rr(p)                                          # --rerun 直接写 verdict
    assert _load_json(p)["verdict"]["exit_code"] == 2
    pend = v["single_pending_review"]
    assert [x["id"] for x in pend] == ["s05", "s04"] and pend[0]["priority"] and not pend[1]["priority"]
    assert v["single_regressions"] == [] and v["single_flaky"] == [] and v["exit_code"] == 2

    _sign(p, True, ids={"s04"})
    _sign(p, True, ids={"s05"}, only_attempts={1})
    v = run_gate.verdict(p, "m13r")                     # 只签了一部分：s05 仍待签
    assert [x["id"] for x in v["single_flaky"]] == ["s04"] and v["single_pending_review"][0]["unsigned"] == [2, 3]
    assert v["exit_code"] == 2

    _sign(p, True, ids={"s05"})                         # match=false 那行人工签 true（B66/B68）→ 波动
    v = run_gate.verdict(p, "m13r")
    assert {x["id"] for x in v["single_flaky"]} == {"s04", "s05"} and v["exit_code"] == 0
    assert v["regression_verdict"].startswith("已复跑的 2 题里没有回归")
    f = {x["id"]: x for x in v["single_flaky"]}
    assert f["s04"]["flaky_cause"] == "model" and f["s04"]["observed_pass_rate"] == "3/4"


def test_rerun_signed_false_is_regression(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04"})
    _rr(p)
    _sign(p, True)
    _sign(p, False, only_attempts={2})
    with pytest.raises(SystemExit) as e:                # 判错的复跑行缺 failure_class
        run_gate.verdict(p, "m13r")
    assert _exit_code(e) == 3
    _sign(p, False, only_attempts={2}, failure_class=3)
    v = run_gate.verdict(p, "m13r")
    assert v["single_regressions"] == ["s04"] and v["exit_code"] == 1
    assert v["regression_verdict"].startswith("有回归")


def test_rerun_invalid_rows_need_no_signature_and_flaky_cause_env(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04"}, main_kind={"s04": "llm"})
    stub.queue["s04"] = [_res(), _res(executed=False, error_kind="llm"), _res(), _res()]
    _rr(p)
    _sign(p, True)                                      # 只签有效行
    d = _load_json(p)
    assert sum(r["human_correct"] is None for r in d["reruns"]) == 1
    v = run_gate.verdict(p, "m13r")
    assert v["single_flaky"] == [{"id": "s04", "observed_pass_rate": "3/4", "flaky_cause": "env"}]
    assert v["exit_code"] == 0


def test_m13r_without_reruns_is_pending(tmp_path):
    v = run_gate.verdict(_rerun_report(tmp_path, {"s04"}), "m13r")
    assert v["regression_verdict"].startswith("待复跑：python scripts/gate/run_gate.py --rerun")
    assert "--profile m13r" in v["regression_verdict"] and v["exit_code"] == 2
    assert v["rerun_false_negative"] == {"p=0.5": "12.5%", "p=0.7": "34.3%"}
    v = run_gate.verdict(_rerun_report(tmp_path, {"s02"}, name="ok.json"), "m13r")   # 只有名单内错题
    assert v["exit_code"] == 0 and v["single_regressions"] == []


@pytest.mark.parametrize("key,value", [("git_sha", "def5678"), ("agent", "workflow"), ("use_dictionary", False),
                                       ("model", "other"), ("temperature", 0.7), ("base_url_host", "x.com"),
                                       ("python", "3.11.9"), ("pandas", "2.1.0")])
def test_rerun_env_mismatch_refused(tmp_path, stub, key, value):
    p = _rerun_report(tmp_path, {"s04"}, **({} if key == "agent" else {key: value}))
    kw = {"agent": "workflow"} if key == "agent" else {}
    if key == "use_dictionary":
        kw = {"use_dictionary": True}
    with pytest.raises(SystemExit) as e:
        _rr(p, **kw)
    assert _exit_code(e) == 3 and stub.calls == []


def test_rerun_dirty_sha(tmp_path, stub, capsys):
    p = _rerun_report(tmp_path, {"s04"})
    stub.env["git_sha"] = ENV["git_sha"] + "?"
    _rr(p)
    assert _load_json(p)["rerun_meta"]["sha_verified"] is False and "警告" in capsys.readouterr().err
    p2 = _rerun_report(tmp_path, {"s04"}, name="r2.json")
    with pytest.raises(SystemExit) as e:
        _rr(p2, require_sha=True)
    assert _exit_code(e) == 3


def test_rerun_requires_labeled_main_report(tmp_path, stub):
    p = _rerun_report(tmp_path, {"s04"})
    d = _load_json(p)
    d["cases"][0]["human_correct"] = None
    json.dump(d, open(p, "w", encoding="utf-8"))
    with pytest.raises(SystemExit) as e:
        _rr(p)
    assert _exit_code(e) == 3 and stub.calls == []


def _cli(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, os.path.join(GATE, "run_gate.py"), *args], cwd=ROOT, env=env,
                          capture_output=True).returncode


def test_cli_exit_codes(tmp_path):
    """0 / 1 / 2 / 3 各一；m13 有回归仍是 0（有意不改既有闸门的 CI 行为）。"""
    reg = _rerun_report(tmp_path, {"s04"}, name="reg.json")
    assert _cli("--verdict", reg, "--profile", "m13") == 0
    assert _cli("--verdict", reg, "--profile", "m13r") == 2                 # 待复跑
    d = _load_json(reg)
    d["reruns"] = [{"id": "s04", "group": "single", "attempt": i, "valid": True, "executed": True, "match": True,
                    "error_kind": None, "human_correct": True, "failure_class": None} for i in (1, 2, 3)]
    flaky = tmp_path / "flaky.json"
    flaky.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert _cli("--verdict", str(flaky), "--profile", "m13r") == 0
    d["reruns"][1].update(human_correct=False, failure_class=3)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert _cli("--verdict", str(bad), "--profile", "m13r") == 1
    d["cases"][0]["human_correct"] = None
    todo = tmp_path / "todo.json"
    todo.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert _cli("--verdict", str(todo), "--profile", "m13") == 3            # 前提失败：原来是 1
    assert _cli("--verdict", reg, "--profile", "nope") == 3
    assert _cli("--verdict", reg) == 3


@pytest.mark.parametrize("name", ["gate_20261014_162428_react.json", "gate_20261014_163133_workflow.json"])
def test_m13_baseline_verdict_unchanged(tmp_path, name):
    """A1 不动 m13：两份参照基线重跑 verdict，除门槛文件哈希（thresholds.json 加了 m13r）外逐字节一致。"""
    src = json.load(open(os.path.join(ROOT, "docs", "eval", name), encoding="utf-8"))
    p = tmp_path / name
    p.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    v = run_gate.verdict(str(p), "m13")
    old = dict(src["verdict"])
    v, old = {k: x for k, x in v.items() if k != "thresholds_sha256"}, {k: x for k, x in old.items()
                                                                         if k != "thresholds_sha256"}
    assert json.dumps(v, ensure_ascii=False, sort_keys=False) == json.dumps(old, ensure_ascii=False, sort_keys=False)
