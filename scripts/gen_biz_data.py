"""生成多表业务数据集 data/eval/biz/（固定种子，重复运行逐字节相同）。

    python scripts/gen_biz_data.py            # 写到 data/eval/biz/
    python scripts/gen_biz_data.py --check    # 只校验现有文件与重新生成的是否一致

五张表（表名 = 文件名，代码里用 dfs['表名']）：
- orders.csv       订单主表 2024-01-01 ~ 2024-06-30，只有编号 / 日期 / 客户 / 渠道 / 状态
- order_items.csv  订单明细，一单 1~3 行，金额全在这里（orders 刻意不含金额，逼出 join）
- products.csv     商品维度，40 个 SKU + 2 行重复
- customers.csv    客户维度，200 人
- refunds.csv      退款记录，既挂已退款订单也挂少量已完成订单（售后补偿）

刻意保留的脏数据（每一条都在题面或字典里点明，"脏"要制造执行难度，不能制造口径歧义）：
- orders 整行重复（录入重复）            → 按 order_id 去重
- orders.status 前后带空格               → strip 后再筛
- orders.order_date 少量带 00:00:00      → to_datetime 归一
- order_items.unit_price 混千分位/¥      → 清洗成数值
- order_items.sku 混小写                 → 统一大写后 join
- products.category / product_name 带尾空格、2 行整行重复 → strip + 去重
- customers.customer_id 带前导空格       → strip 后 join
- customers.city 有空值、orders 有 8 个客户的客户表缺失 → 归「未知」
- customers.member_level 混大小写        → 首字母大写
- refunds.refund_amount 混千分位/¥、整行重复 → 清洗 + 去重

数据是虚构的，不对应任何真实公司或个人。
"""
import argparse
import io
import os
import sys

import numpy as np
import pandas as pd

SEED = 20261030
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "eval", "biz")

CATS = {"数码": (299, 3999), "服饰": (59, 599), "家居": (89, 899), "食品": (9, 129), "美妆": (49, 699)}
CAT_NAMES = list(CATS)
N_CUSTOMERS = 200
N_ORDERS = 800
N_SKUS = 40


def _money(v: float, style: str) -> str:
    """把金额写成某一种"脏"格式。plain 也会被 pandas 读成 float，混进别的格式后整列变 object。"""
    if style == "comma":
        return f"{v:,.2f}"
    if style == "yuan":
        return f"¥{v:.1f}"
    if style == "both":
        return f"¥{v:,.2f}"
    return f"{v:.2f}"


def _pick_styles(rng, n, plain_p=0.55, comma_p=0.2, yuan_p=0.13):
    """按比例给出每行的金额格式，剩下的走 both。"""
    u = rng.random(n)
    return np.where(u < plain_p, "plain",
                    np.where(u < plain_p + comma_p, "comma",
                             np.where(u < plain_p + comma_p + yuan_p, "yuan", "both")))


def make_products(rng):
    rows = []
    for i in range(1, N_SKUS + 1):
        cat = CAT_NAMES[(i - 1) % len(CAT_NAMES)]
        lo, hi = CATS[cat]
        price = round(float(rng.uniform(lo, hi)), 2)
        cost = round(price * float(rng.uniform(0.35, 0.7)), 2)
        name = f"{cat}商品{i:02d}"
        # 三成商品名带尾空格（导出时的老毛病）
        if rng.random() < 0.3:
            name = name + " "
        rows.append({"sku": f"K-{1000 + i}", "product_name": name, "category": cat, "list_price": price, "cost": cost})
    df = pd.DataFrame(rows)
    # 两行整行重复（同一个 SKU 录了两遍，内容一致，去重不会丢信息）
    dup = df.iloc[[3, 17]].copy()
    df = pd.concat([df, dup], ignore_index=True)
    # 品类带尾空格
    mask = rng.random(len(df)) < 0.15
    df.loc[mask, "category"] = df.loc[mask, "category"] + " "
    return df


def make_customers(rng):
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉"]
    city_p = [0.18, 0.2, 0.12, 0.14, 0.13, 0.12, 0.11]
    levels = ["Gold", "Silver", "Basic"]
    rows = []
    for i in range(1, N_CUSTOMERS + 1):
        cid = f"C{i:04d}"
        # 前导空格：导出工具补的位，不 strip 就 join 不上
        if rng.random() < 0.12:
            cid = " " + cid
        city = "" if rng.random() < 0.08 else str(rng.choice(cities, p=city_p))
        level = str(rng.choice(levels, p=[0.2, 0.35, 0.45]))
        if rng.random() < 0.2:
            level = level.lower()
        rows.append({"customer_id": cid, "city": city, "member_level": level,
                     "register_channel": str(rng.choice(["APP", "小程序", "网页"], p=[0.5, 0.35, 0.15]))})
    return pd.DataFrame(rows)


def make_orders(rng):
    days = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    # 促销月下单更多
    weight = np.array([{1: 0.9, 2: 0.7, 3: 1.2, 4: 1.0, 5: 1.0, 6: 1.4}[d.month] for d in days])
    dates = np.sort(rng.choice(days, size=N_ORDERS, p=weight / weight.sum()))

    # 8 个客户刻意不在 customers 表里（历史导入残留），考「缺失归未知」
    exotic = [f"C{9000 + i}" for i in range(8)]
    cids = [f"C{i:04d}" for i in range(1, N_CUSTOMERS + 1)]
    # 少数老客买得多，但用对数正态而不是 Pareto：Pareto(1.6) 会抽出单个客户占三成订单的
    # 极端值，那样"复购客户数""客单价"这类题就被一个人的故事主导，不是业务分布。
    user_w = np.exp(rng.normal(0.0, 0.7, size=len(cids)))
    picked = rng.choice(cids, size=N_ORDERS, p=user_w / user_w.sum())
    for pos in rng.choice(N_ORDERS, size=8, replace=False):
        picked[pos] = str(rng.choice(exotic))

    status = rng.choice(["已完成", "已退款", "已取消"], size=N_ORDERS, p=[0.82, 0.12, 0.06])
    channel = rng.choice(["APP", "小程序", "网页"], size=N_ORDERS, p=[0.5, 0.35, 0.15])

    rows = []
    for i in range(N_ORDERS):
        d = pd.Timestamp(dates[i])
        ds = f"{d:%Y-%m-%d} 00:00:00" if rng.random() < 0.10 else f"{d:%Y-%m-%d}"
        st = str(status[i])
        # 前后空格：真实导出里常见，不 strip 就筛不出「已完成」
        r = rng.random()
        if r < 0.10:
            st = " " + st
        elif r < 0.18:
            st = st + "  "
        rows.append({"order_id": f"O{i + 1:06d}", "order_date": ds, "customer_id": str(picked[i]),
                     "channel": str(channel[i]), "status": st})
    df = pd.DataFrame(rows)
    # 12 行整行重复
    dup = df.iloc[rng.choice(len(df), size=12, replace=False)].copy()
    return pd.concat([df, dup], ignore_index=True)


def make_items(rng, orders, products):
    skus = products["sku"].tolist()
    cat_of = dict(zip(products["sku"], products["category"]))
    price_of = dict(zip(products["sku"], products["list_price"]))
    # 一单 1~3 行
    n_items = rng.choice([1, 2, 3], size=len(orders), p=[0.45, 0.38, 0.17])
    rows = []
    for oid, k in zip(orders["order_id"], n_items):
        picked = rng.choice(skus, size=int(k), replace=False)
        for sku in picked:
            base = float(price_of[sku])
            deal = round(base * float(rng.uniform(0.80, 1.0)), 2)
            row_sku = str(sku)
            # 两成 SKU 写成小写（ERP 导出的历史格式）
            if rng.random() < 0.20:
                row_sku = row_sku.lower()
            rows.append({"order_id": oid, "sku": row_sku,
                         "qty": int(rng.integers(1, 6)), "unit_price": deal,
                         "_cat": cat_of[sku]})
    df = pd.DataFrame(rows)
    styles = _pick_styles(rng, len(df))
    df["unit_price"] = [_money(v, s) for v, s in zip(df["unit_price"], styles)]
    df = df.drop(columns=["_cat"])
    return df


def make_refunds(rng, orders, items):
    """退款表：已退款订单占多数，另有少量已完成订单的售后补偿。

    金额是"该订单退款总额"，不超过该订单的明细合计，保证「净额」不会出现负数——
    负数会让「扣减口径对不对」和「算不算负数」两件事混在一起。
    """
    order_total = (items.assign(v=items["qty"] * items["unit_price"].astype(str)
                                .str.replace("¥", "", regex=False).str.replace(",", "", regex=False)
                                .astype(float))
                   .groupby("order_id")["v"].sum())
    refunded = orders[orders["status"].str.strip() == "已退款"]["order_id"].tolist()
    done = orders[orders["status"].str.strip() == "已完成"]["order_id"].tolist()
    picked = [str(x) for x in rng.choice(refunded, size=min(60, len(refunded)), replace=False)]
    picked += [str(x) for x in rng.choice(done, size=30, replace=False)]

    reasons = ["质量问题", "尺寸不符", "物流延误", "七天无理由", "拍错"]
    rows = []
    for i, oid in enumerate(picked):
        total = float(order_total.get(oid, 0.0))
        full = oid in refunded and rng.random() < 0.6
        amt = round(total, 2) if full else round(total * float(rng.uniform(0.2, 0.8)), 2)
        rows.append({"refund_id": f"R{i + 1:05d}", "order_id": oid,
                     "refund_date": f"2024-{int(rng.integers(1, 8)):02d}-{int(rng.integers(1, 29)):02d}",
                     "refund_amount": amt, "reason": str(rng.choice(reasons))})
    df = pd.DataFrame(rows)
    styles = _pick_styles(rng, len(df), plain_p=0.5, comma_p=0.2, yuan_p=0.2)
    df["refund_amount"] = [_money(v, s) for v, s in zip(df["refund_amount"], styles)]
    # 5 行整行重复
    dup = df.iloc[rng.choice(len(df), size=5, replace=False)].copy()
    return pd.concat([df, dup], ignore_index=True)


DICTS = {
    "orders": [
        ("order_id", "订单号，唯一标识一笔订单；表中有少量整行重复的录入错误，同一订单号出现两次"),
        ("order_date", "下单日期，范围 2024-01-01 至 2024-06-30；少量带 00:00:00 的时间部分"),
        ("customer_id", "下单客户编号，对应 customers 表；有 8 个编号在客户表里查不到（历史导入残留）"),
        ("channel", "下单渠道，取值有 APP、小程序、网页"),
        ("status", "订单状态，取值有已完成、已退款、已取消；部分值前后带空格，需 strip 后再比较"),
    ],
    "order_items": [
        ("order_id", "订单号，对应 orders 表；一单可能有 1 至 3 行"),
        ("sku", "商品编码，对应 products 表；部分写成小写，join 前需统一大写"),
        ("qty", "购买件数"),
        ("unit_price", "成交单价（元）；部分带千分位逗号或人民币符号，需清洗成数值"),
    ],
    "products": [
        ("sku", "商品编码，大写形式 K-1001；表中有 2 行整行重复"),
        ("product_name", "商品名称，部分带尾部空格"),
        ("category", "商品品类，取值有数码、服饰、家居、食品、美妆；部分带尾部空格"),
        ("list_price", "商品标价（元）"),
        ("cost", "商品成本（元）"),
    ],
    "customers": [
        ("customer_id", "客户编号，对应 orders 表；部分带前导空格，join 前需 strip"),
        ("city", "所在城市；部分为空表示未填写"),
        ("member_level", "会员等级，取值有 Gold、Silver、Basic；部分写成小写"),
        ("register_channel", "注册渠道，取值有 APP、小程序、网页"),
    ],
    "refunds": [
        ("refund_id", "退款单号"),
        ("order_id", "对应订单号；既有已退款订单的退款，也有少量已完成订单的售后补偿退款"),
        ("refund_date", "退款日期"),
        ("refund_amount", "退款金额（元），不超过该订单的明细合计；部分带千分位或人民币符号"),
        ("reason", "退款原因，取值有质量问题、尺寸不符、物流延误、七天无理由、拍错"),
    ],
}


def build():
    rng = np.random.default_rng(SEED)
    products = make_products(rng)
    customers = make_customers(rng)
    orders = make_orders(rng)
    items = make_items(rng, orders, products)
    refunds = make_refunds(rng, orders, items)
    return {"orders": orders, "order_items": items, "products": products,
            "customers": customers, "refunds": refunds}


def _csv_bytes(df) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def _dict_bytes(rows) -> bytes:
    buf = io.StringIO()
    pd.DataFrame(rows, columns=["field", "description"]).to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    tables = build()
    payload = {}
    for name, df in tables.items():
        payload[f"{name}.csv"] = _csv_bytes(df)
        payload[f"{name}.dict.csv"] = _dict_bytes(DICTS[name])

    os.makedirs(OUT_DIR, exist_ok=True)
    bad = []
    for fname, data in payload.items():
        path = os.path.join(OUT_DIR, fname)
        if args.check:
            old = open(path, "rb").read() if os.path.exists(path) else b""
            if old != data:
                bad.append(fname)
        else:
            with open(path, "wb") as f:
                f.write(data)

    if args.check:
        if bad:
            print("与重新生成的不一致：" + "、".join(bad))
            return 1
        print(f"一致：{len(payload)} 个文件")
        return 0

    for name, df in tables.items():
        print(f"{name:12s} {len(df):5d} 行 × {len(df.columns)} 列")
    print(f"已写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
