"""生成阶段 3 评测用的 3 张合成表（固定随机种子，重复运行产出逐字节相同的 CSV）。

    python scripts/gen_eval_data.py            # 写到 data/eval/
    python scripts/gen_eval_data.py --check    # 只校验现有文件与重新生成的是否一致（CI 用）

表：
- orders.csv     电商订单 2024-01 至 2024-06，含缺失值（城市、折扣）和整行重复（录入重复）
- employees.csv  员工花名册（截至 2024-09-30），含在职与离职员工
- inventory.csv  门店日频库存 2024-03-01 至 2024-05-31，5 家门店 × 4 个 SKU

每张表旁边有同名 .dict.csv 数据字典（field,description），供工作流版检索。
数据是虚构的，不对应任何真实公司或个人。
"""
import argparse
import io
import os
import sys

import numpy as np
import pandas as pd

SEED = 20261010
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "eval")


# ---------------------------------------------------------------- 电商订单
def make_orders(rng: np.random.Generator) -> pd.DataFrame:
    n = 1200
    days = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    # 月度有起伏：3 月、6 月促销更多
    weight = np.array([{1: 0.9, 2: 0.7, 3: 1.2, 4: 1.0, 5: 1.0, 6: 1.4}[d.month] for d in days])
    dates = rng.choice(days, size=n, p=weight / weight.sum())
    dates = np.sort(dates)

    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉"]
    city_p = [0.18, 0.2, 0.12, 0.14, 0.13, 0.12, 0.11]
    channels = ["APP", "小程序", "网页"]
    channel_p = [0.5, 0.35, 0.15]
    cats = {"服饰": (59, 399), "数码": (199, 2999), "食品": (19, 129), "家居": (39, 699), "美妆": (49, 599)}
    cat_names = list(cats)
    cat_p = [0.26, 0.14, 0.24, 0.18, 0.18]

    users = [f"U{i:04d}" for i in range(1, 361)]
    # 少数老客买得多
    user_w = rng.pareto(1.6, size=len(users)) + 1
    user_ids = rng.choice(users, size=n, p=user_w / user_w.sum())

    category = rng.choice(cat_names, size=n, p=cat_p)
    unit_price = np.array([round(float(rng.uniform(*cats[c])) / 1) for c in category], dtype=float)
    unit_price = np.round(unit_price, 0) - 0.1          # 定价习惯：xx9.9
    unit_price = np.where(unit_price < 9.9, 9.9, unit_price)
    qty = rng.choice([1, 1, 1, 2, 2, 3, 4, 5], size=n)
    discount = rng.choice([0.0, 0.05, 0.1, 0.15, 0.2, 0.3], size=n, p=[0.45, 0.15, 0.2, 0.1, 0.07, 0.03])
    status = rng.choice(["已完成", "已退款", "已取消"], size=n, p=[0.85, 0.08, 0.07])
    city = rng.choice(cities, size=n, p=city_p).astype(object)
    channel = rng.choice(channels, size=n, p=channel_p)

    df = pd.DataFrame({
        "order_id": [f"O{i:06d}" for i in range(1, n + 1)],
        "order_date": pd.to_datetime(dates).strftime("%Y-%m-%d"),
        "user_id": user_ids,
        "city": city,
        "channel": channel,
        "category": category,
        "qty": qty,
        "unit_price": unit_price,
        "discount": discount,
    })
    df["pay_amount"] = (df["qty"] * df["unit_price"] * (1 - df["discount"])).round(2)
    df["status"] = status

    # 脏数据：城市缺失约 3%；折扣为 0 的行里约 1/3 留空（字典说明：空 = 无折扣）
    miss_city = rng.random(n) < 0.03
    df.loc[miss_city, "city"] = np.nan
    zero = df.index[df["discount"] == 0.0]
    blank = rng.choice(zero, size=len(zero) // 3, replace=False)
    df["discount"] = df["discount"].astype(object)
    df.loc[blank, "discount"] = np.nan
    # 整行重复 18 条（同一 order_id 录入两次），插在原行后面
    dup_idx = np.sort(rng.choice(df.index, size=18, replace=False))
    parts, last = [], 0
    for i in dup_idx:
        parts.append(df.iloc[last:i + 1])
        parts.append(df.iloc[[i]])
        last = i + 1
    parts.append(df.iloc[last:])
    return pd.concat(parts, ignore_index=True)


ORDERS_DICT = [
    ("order_id", "订单号，唯一标识一笔订单；表中有少量整行重复的录入错误，同一订单号出现两次"),
    ("order_date", "下单日期，格式 YYYY-MM-DD，范围 2024-01-01 至 2024-06-30"),
    ("user_id", "下单用户编号"),
    ("city", "收货城市，取值有北京、上海、广州、深圳、杭州、成都、武汉；少量为空表示未填写"),
    ("channel", "下单渠道，取值有 APP、小程序、网页"),
    ("category", "商品品类，取值有服饰、数码、食品、家居、美妆"),
    ("qty", "购买件数"),
    ("unit_price", "商品单价，单位为元"),
    ("discount", "折扣率，0.1 表示打九折；为空表示无折扣（等同于 0）"),
    ("pay_amount", "实付金额，单位为元，= 件数 × 单价 ×（1 − 折扣率）"),
    ("status", "订单状态，取值有已完成、已退款、已取消；已退款和已取消的订单不计入有效销售额"),
]


# ---------------------------------------------------------------- 员工花名册
def make_employees(rng: np.random.Generator) -> pd.DataFrame:
    n = 240
    depts = ["研发", "销售", "市场", "财务", "人力", "运营"]
    dept_p = [0.35, 0.22, 0.12, 0.08, 0.08, 0.15]
    levels = ["P4", "P5", "P6", "P7", "P8"]
    level_p = [0.25, 0.32, 0.24, 0.13, 0.06]
    base = {"P4": 9000, "P5": 13000, "P6": 19000, "P7": 28000, "P8": 40000}
    dept_mult = {"研发": 1.15, "销售": 0.95, "市场": 1.0, "财务": 1.0, "人力": 0.9, "运营": 0.92}

    dept = rng.choice(depts, size=n, p=dept_p)
    level = rng.choice(levels, size=n, p=level_p)
    gender = np.where(rng.random(n) < np.array([0.3 if d == "研发" else 0.55 for d in dept]), "女", "男")
    city = rng.choice(["北京", "上海", "深圳"], size=n, p=[0.45, 0.35, 0.2])
    hire = pd.to_datetime("2015-01-01") + pd.to_timedelta(rng.integers(0, 3560, size=n), unit="D")
    lv_age = {"P4": 24, "P5": 27, "P6": 30, "P7": 34, "P8": 38}
    birth_year = np.array([2024 - lv_age[l] - int(rng.integers(0, 8)) for l in level])
    salary = np.array([round(base[l] * dept_mult[d] * rng.uniform(0.88, 1.15) / 100) * 100
                       for l, d in zip(level, dept)])

    leave = []
    for h in hire:
        if rng.random() < 0.17:
            lo = max(h + pd.Timedelta(days=60), pd.Timestamp("2022-01-01"))
            hi = pd.Timestamp("2024-09-30")
            leave.append(lo + pd.Timedelta(days=int(rng.integers(0, max(1, (hi - lo).days)))) if lo < hi else pd.NaT)
        else:
            leave.append(pd.NaT)
    leave = pd.to_datetime(pd.Series(leave))

    perf = rng.choice(["A", "B", "C", "D"], size=n, p=[0.15, 0.55, 0.25, 0.05]).astype(object)
    perf[hire >= pd.Timestamp("2024-01-01")] = np.nan            # 2024 年入职的没有 2023 年绩效

    df = pd.DataFrame({
        "emp_id": [f"E{i:04d}" for i in range(1, n + 1)],
        "dept": dept, "level": level, "gender": gender, "birth_year": birth_year, "city": city,
        "hire_date": hire.strftime("%Y-%m-%d"),
        "leave_date": leave.dt.strftime("%Y-%m-%d"),
        "monthly_salary": salary, "perf_2023": perf,
    })
    return df


EMP_DICT = [
    ("emp_id", "员工编号"),
    ("dept", "所属部门，取值有研发、销售、市场、财务、人力、运营"),
    ("level", "职级，P4 最低、P8 最高"),
    ("gender", "性别，男或女"),
    ("birth_year", "出生年份"),
    ("city", "工作城市，取值有北京、上海、深圳"),
    ("hire_date", "入职日期，格式 YYYY-MM-DD"),
    ("leave_date", "离职日期，格式 YYYY-MM-DD；为空表示仍在职（数据截至 2024-09-30）"),
    ("monthly_salary", "月薪（税前基本工资），单位为元"),
    ("perf_2023", "2023 年度绩效，A 最好、D 最差；2024 年入职的员工为空"),
]


# ---------------------------------------------------------------- 门店日频库存
def make_inventory(rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range("2024-03-01", "2024-05-31", freq="D")
    stores = {"S01": 1.3, "S02": 1.0, "S03": 0.8, "S04": 1.1, "S05": 0.6}
    skus = {"K100": 30, "K200": 18, "K300": 9, "K400": 4}      # 日均基础销量
    rows = []
    for s, sm in stores.items():
        for k, base in skus.items():
            stock = int(base * sm * 10)
            target = int(base * sm * 12)
            for d in days:
                dow = 1.35 if d.dayofweek >= 5 else 1.0          # 周末多卖
                promo = 1.5 if pd.Timestamp("2024-05-01") <= d <= pd.Timestamp("2024-05-05") else 1.0
                demand = int(rng.poisson(base * sm * dow * promo))
                received = 0
                if d.dayofweek == 0 or (k == "K100" and d.dayofweek == 3):   # 周一补货，K100 周四加补一次
                    received = max(0, target - stock)
                    if rng.random() < 0.08:                      # 偶尔缺货漏补
                        received = 0
                opening = stock
                sold = min(demand, opening + received)
                closing = opening + received - sold
                rows.append((d.strftime("%Y-%m-%d"), s, k, opening, received, sold, closing))
                stock = closing
    return pd.DataFrame(rows, columns=["date", "store", "sku", "opening_stock", "received", "sold", "closing_stock"])


INV_DICT = [
    ("date", "日期，格式 YYYY-MM-DD，范围 2024-03-01 至 2024-05-31"),
    ("store", "门店编号，取值有 S01、S02、S03、S04、S05"),
    ("sku", "商品编号，取值有 K100、K200、K300、K400"),
    ("opening_stock", "当日期初库存，单位为件"),
    ("received", "当日到货补货数量，单位为件"),
    ("sold", "当日销量，单位为件；库存不足时销量受限"),
    ("closing_stock", "当日期末库存，单位为件，= 期初 + 到货 − 销量；为 0 表示当日缺货（售罄）"),
]


TABLES = {
    "orders": (make_orders, ORDERS_DICT),
    "employees": (make_employees, EMP_DICT),
    "inventory": (make_inventory, INV_DICT),
}


def build() -> dict:
    """返回 {文件名: 文本内容}。每张表用独立的子种子，改一张表不影响另外两张。"""
    out = {}
    for i, (name, (fn, dct)) in enumerate(TABLES.items()):
        rng = np.random.default_rng([SEED, i])
        buf = io.StringIO()
        fn(rng).to_csv(buf, index=False, lineterminator="\n")
        out[f"{name}.csv"] = buf.getvalue()
        out[f"{name}.dict.csv"] = "field,description\n" + "".join(f"{f},\"{d}\"\n" for f, d in dct)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()
    files = build()
    if args.check:
        bad = [f for f, text in files.items()
               if not os.path.exists(os.path.join(OUT_DIR, f))
               or open(os.path.join(OUT_DIR, f), encoding="utf-8", newline="").read() != text]
        if bad:
            print("与生成脚本不一致：", ", ".join(bad))
            sys.exit(1)
        print("评测数据与生成脚本一致")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    for f, text in files.items():
        with open(os.path.join(OUT_DIR, f), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("写入", os.path.join("data", "eval", f))


if __name__ == "__main__":
    main()
