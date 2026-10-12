"""阶段 3.5 闸门：独立核算标准答案（闸门的命门，docs/roadmap/gate-phase35.md §2 方案 A）。

- 不 import datachat 的任何代码；在**原始**外部文件上计算（UCI 的 xlsx 原件、Olist 原表），
  不读 build_gate_data.py 生成的脏表，所以脏化过程即使有 bug 也不会污染标准答案。
- 每题：gold（首选口径）+ alts（另一种合理口径，各附一句说明）。口径说明写在 note 里，人工判定时对照。
- 输出 docs/gate/answers.json（入库、冻结），带题面哈希与数据指纹。

用法：python scripts/gate/verify_gate.py      （先跑 build_gate_data.py 下载数据）
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from questions import QUESTIONS  # noqa: E402

RAW_XLSX = os.path.join(ROOT, "data", "gate", "raw", "Online Retail.xlsx")
OLIST = os.path.join(ROOT, "data", "gate", "olist")
OUT = os.path.join(ROOT, "docs", "gate", "answers.json")


def sha12_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]


def scalar(v, d=2):
    return {"kind": "scalar", "value": round(float(v), d) if d is not None else int(v)}


def labels(xs, ordered):
    return {"kind": "list", "value": [str(x) for x in xs], "ordered": ordered}


def label(x):
    return {"kind": "label", "value": str(x)}


def series(s: pd.Series, d=2):
    s = s.round(d) if d is not None else s
    return {"kind": "series", "index": [str(i) for i in s.index], "values": [float(v) for v in s.values]}


def alt(ans, why):
    return {**ans, "why": why}


# ------------------------------------------------------------------ 单表：UCI Online Retail
def retail_answers():
    r = pd.read_excel(RAW_XLSX)
    r["amt"] = r["Quantity"] * r["UnitPrice"]
    cancel = r["InvoiceNo"].astype(str).str.startswith("C")
    y2011 = r["InvoiceDate"].dt.year == 2011
    uk = r["Country"] == "United Kingdom"
    keep = ~cancel
    a = {}

    a["s01"] = dict(gold=scalar(r.loc[y2011, "amt"].sum()),
                    alts=[alt(scalar(r.loc[y2011 & keep, "amt"].sum()), "去掉取消单（发票号以 C 开头）")],
                    note="净额：所有行数量×单价求和（取消单为负数，自然冲减）")
    a["s02"] = dict(gold=scalar(r["CustomerID"].nunique(), None), alts=[],
                    note="去重客户编号，不含缺失（脏表里缺失写成'未登记'，不能算一个客户）")
    a["s03"] = dict(gold=scalar(r.groupby("InvoiceNo")["amt"].sum().mean()),
                    alts=[alt(scalar(r[keep].groupby("InvoiceNo")["amt"].sum().mean()), "只算未取消的发票")],
                    note="每张发票金额求和后取平均，含取消发票（金额为负）")
    nonuk = ~uk
    a["s04"] = dict(gold=scalar(r.loc[nonuk, "Quantity"].sum(), None),
                    alts=[alt(scalar(r.loc[nonuk & keep, "Quantity"].sum(), None), "去掉取消单")],
                    note="净数量；报表变体末尾有'合计'行（国家为空），按'国家≠英国'过滤会把合计行算进去")
    a["s05"] = dict(gold=scalar(r.loc[cancel, "InvoiceNo"].nunique(), None), alts=[],
                    note="发票号以 C 开头的去重发票数（数据集说明的定义）；数量为负但非 C 开头的是库存调整，不是取消")
    a["s06"] = dict(gold=scalar(int((r["UnitPrice"] > 100).sum()), None), alts=[],
                    note="单价 > 100 的行数（含邮费/手工调整等特殊行）；报表变体有两行表头")
    dec = r[(r["InvoiceDate"].dt.year == 2011) & (r["InvoiceDate"].dt.month == 12)]
    dec_keep = dec[~dec["InvoiceNo"].astype(str).str.startswith("C")]
    a["s07"] = dict(gold=labels(sorted(dec["Country"].unique()), False),
                    alts=[alt(labels(sorted(dec_keep["Country"].unique()), False), "不算只有取消单的国家")],
                    note="2011-12 出现过的国家（集合，不要求顺序）")
    top5 = r.groupby("Country")["amt"].sum().nlargest(5).index
    a["s08"] = dict(gold=labels(top5, True), alts=[],
                    note="按净销售额排前 5；去掉取消单时前 5 及顺序相同")
    by_desc = r.groupby("Description")["Quantity"].sum()
    by_code = r.groupby("StockCode")["Quantity"].sum()
    top_code = by_code.idxmax()
    code_descs = sorted(r.loc[r["StockCode"] == top_code, "Description"].dropna().unique())
    a["s09"] = dict(gold=label(by_desc.idxmax()),
                    alts=[alt(label(top_code), "按商品编码汇总（同一编码有多个描述）")] +
                         [alt(label(d), "按商品编码汇总后报该编码的描述") for d in code_descs],
                    note="净数量（取消单冲减）。陷阱：'PAPER CRAFT , LITTLE BIRDIE' 有 80995 件的单子被整单取消，"
                         "只看正数量会错选它")
    month = r["InvoiceDate"].dt.to_period("M")
    a["s10"] = dict(gold=label(r.groupby(month)["amt"].sum().idxmax()), alts=[],
                    note="按月净销售额最高的月份；去掉取消单结果相同")
    q = r.loc[y2011, "InvoiceDate"].dt.quarter
    qk = r.loc[y2011 & keep, "InvoiceDate"].dt.quarter
    a["s11"] = dict(gold=series(r.loc[y2011].groupby(q)["amt"].sum()),
                    alts=[alt(series(r.loc[y2011 & keep].groupby(qk)["amt"].sum()), "去掉取消单")],
                    note="2011 年 Q1–Q4 净销售额")
    a["s12"] = dict(gold=scalar(r["CustomerID"].isna().mean() * 100), alts=[], percent_equiv=True,
                    note="缺失客户编号行数 / 总行数 × 100")
    a["s13"] = dict(gold=scalar(r.loc[uk, "amt"].sum() / r["amt"].sum() * 100),
                    alts=[alt(scalar(r.loc[uk & keep, "amt"].sum() / r.loc[keep, "amt"].sum() * 100),
                              "去掉取消单")], percent_equiv=True,
                    note="英国净销售额 / 全部净销售额 × 100")
    a["s14"] = dict(gold={"kind": "refusal"}, alts=[], note="没有成本/进价字段")
    a["s15"] = dict(gold={"kind": "refusal"}, alts=[], note="没有性别字段")
    return a, {"Online Retail.xlsx": sha12_file(RAW_XLSX)}


# ------------------------------------------------------------------ 多表：Olist
def olist_answers():
    rd = lambda n: pd.read_csv(os.path.join(OLIST, n))  # noqa: E731
    o, c, i, p = rd("orders.csv"), rd("customers.csv"), rd("order_items.csv"), rd("order_payments.csv")
    rv, pr, s, t = rd("order_reviews.csv"), rd("products.csv"), rd("sellers.csv"), rd("category_translation.csv")
    a = {}
    oc = o.merge(c, on="customer_id")
    a["m01"] = dict(gold=series(oc.groupby("customer_state")["order_id"].nunique(), None), alts=[],
                    note="orders ⋈ customers（customer_id），按 customer_state 数订单")
    opc = p.merge(o, on="order_id").merge(c, on="customer_id")
    oic = i.merge(o, on="order_id").merge(c, on="customer_id")
    sp_items = oic[oic["customer_state"] == "SP"]
    a["m02"] = dict(gold=scalar(opc.loc[opc["customer_state"] == "SP", "payment_value"].sum()),
                    alts=[alt(scalar((sp_items["price"] + sp_items["freight_value"]).sum()),
                              "用 order_items 的商品价+运费代替实付")],
                    note="payments ⋈ orders ⋈ customers，SP 州 payment_value 合计（所有订单状态）")
    a["m03"] = dict(gold=series(i.merge(s, on="seller_id").groupby("seller_state")["price"].mean()), alts=[],
                    note="order_items ⋈ sellers（seller_id），按 seller_state 求 price 均值（每个订单行算一次）")
    one = rv.loc[rv["review_score"] == 1, "order_id"].drop_duplicates()
    x = o[o["order_id"].isin(one)]
    dur = pd.to_datetime(x["order_delivered_customer_date"]) - pd.to_datetime(x["order_purchase_timestamp"])
    a["m04"] = dict(gold=scalar(dur.dt.total_seconds().div(86400).mean()),
                    alts=[alt(scalar(dur.dt.days.mean()), "按整天数（.dt.days）算")],
                    note="reviews(score=1) ⋈ orders，送达时间 - 下单时间，未送达的不计；按订单去重")
    hb = pr.loc[pr["product_category_name"].isin(
        t.loc[t["product_category_name_english"] == "health_beauty", "product_category_name"]), "product_id"]
    y = i[i["product_id"].isin(hb)].merge(o, on="order_id").merge(c, on="customer_id")
    a["m05"] = dict(gold=scalar(y["customer_unique_id"].nunique(), None),
                    alts=[alt(scalar(y["customer_id"].nunique(), None), "按 customer_id 数（Olist 每个订单一个 customer_id）")],
                    note="items ⋈ products ⋈ translation ⋈ orders ⋈ customers，去重 customer_unique_id")
    ts = pd.to_datetime(o["order_purchase_timestamp"])
    cx = o[(ts.dt.year == 2018) & (ts.dt.month == 8) & (o["order_status"] == "canceled")]
    a["m06"] = dict(gold=scalar(p.loc[p["order_id"].isin(cx["order_id"]), "payment_value"].sum()), alts=[],
                    note=f"2018-08 下单、status=canceled 的 {len(cx)} 个订单，payments.payment_value 合计")
    ip = i.merge(pr, on="product_id").merge(t, on="product_category_name", how="left")
    a["m07"] = dict(gold=labels(ip.groupby("product_category_name_english")["price"].sum().nlargest(3).index, True),
                    alts=[], note="按 price 合计排前 3；加上运费时前 3 及顺序相同")
    a["m08"] = dict(gold=labels(oc.groupby("customer_city")["order_id"].nunique().nlargest(5).index, True),
                    alts=[], note="orders ⋈ customers，按 customer_city 数订单排前 5")
    a["m09"] = dict(gold={"kind": "refusal"}, alts=[], note="没有年龄字段")
    a["m10"] = dict(gold={"kind": "refusal"}, alts=[], note="没有成本字段")
    fps = {n: sha12_file(os.path.join(OLIST, n)) for n in sorted(os.listdir(OLIST)) if n.endswith(".csv")}
    return a, fps


def questions_sha256() -> str:
    data = open(os.path.join(HERE, "questions.py"), "rb").read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:12]


def main():
    ra, rf = retail_answers()
    oa, of = olist_answers()
    answers = {**ra, **oa}
    missing = [q["id"] for q in QUESTIONS if q["id"] not in answers]
    if missing:
        sys.exit(f"缺标准答案：{missing}")
    out = {
        "questions_sha256": questions_sha256(),
        "verify_script_sha256": hashlib.sha256(
            open(os.path.abspath(__file__), "rb").read().replace(b"\r\n", b"\n")).hexdigest()[:12],
        "pandas": pd.__version__,
        "sources": {"uci_online_retail": rf, "olist": of},
        "answers": {q["id"]: {"question": q["question"], **answers[q["id"]]} for q in QUESTIONS},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"写出 {os.path.relpath(OUT, ROOT)}：{len(out['answers'])} 题，questions_sha256={out['questions_sha256']}")


if __name__ == "__main__":
    main()
