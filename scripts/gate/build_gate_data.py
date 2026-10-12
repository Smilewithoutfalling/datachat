"""阶段 3.5 外部验证闸门：下载外部数据并构造"脏表"（只改呈现，不改数据值）。

用法（在仓库根目录，约 90 MB 下载，生成物在 data/gate/，不入库）：
    python scripts/gate/build_gate_data.py

产出：
- data/gate/raw/Online Retail.xlsx            UCI Online Retail（CC BY 4.0），原始文件，verify_gate.py 用它算标准答案
- data/gate/retail/零售明细.csv               单表组主表：中文列名、GB18030 编码、Excel 风格日期字符串、
                                             缺失客户编号写成"未登记"（数值列混入文本）
- data/gate/retail_report/零售报表.csv        单表组"报表导出"变体：在上面基础上再加两行合并表头 + 末尾合计行
- data/gate/olist/*.csv                       多表组：Olist 巴西电商（olist/work-at-olist-data @ 固定 commit），
                                             8 张表原样（不含 61 MB 的 geolocation 表）

为什么"只改呈现"：数据值、行、关系、分布全部来自外部，标准答案由 verify_gate.py 在原始文件上独立计算，
脏化只考察 datachat 的读入/理解能力，不会把答案泄漏进题目。
本脚本不 import datachat 的任何代码。
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import urllib.request
import zipfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "gate")

UCI_URL = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
UCI_XLSX_SHA256 = "43465a06f2cc"   # sha256 前 12 位（2026-10-12 下载）

OLIST_COMMIT = "d9e49802f3e92d09ee94ab9ccc5e457f207a8959"
OLIST_BASE = f"https://raw.githubusercontent.com/olist/work-at-olist-data/{OLIST_COMMIT}/datasets/"
OLIST_FILES = {   # 文件名 -> sha256 前 12 位（2026-10-12 下载时）
    "olist_customers_dataset.csv": "c26c17f59f30",
    "olist_order_items_dataset.csv": "4f6abdbbc940",
    "olist_order_payments_dataset.csv": "61674868ed7b",
    "olist_order_reviews_dataset.csv": "012b61c7593e",
    "olist_orders_dataset.csv": "8df58ef3d2d7",
    "olist_products_dataset.csv": "3e6569628a17",
    "olist_sellers_dataset.csv": "31eb9bd50d68",
    "product_category_name_translation.csv": "a81f0d1f27b2",
}
# 表名 = 文件名去扩展名；datachat 里用 dfs['orders'] 这类短名更自然，这里改成短名
OLIST_SHORT = {
    "olist_customers_dataset.csv": "customers.csv",
    "olist_order_items_dataset.csv": "order_items.csv",
    "olist_order_payments_dataset.csv": "order_payments.csv",
    "olist_order_reviews_dataset.csv": "order_reviews.csv",
    "olist_orders_dataset.csv": "orders.csv",
    "olist_products_dataset.csv": "products.csv",
    "olist_sellers_dataset.csv": "sellers.csv",
    "product_category_name_translation.csv": "category_translation.csv",
}

RETAIL_COLUMNS = {
    "InvoiceNo": "发票号", "StockCode": "商品编码", "Description": "商品描述", "Quantity": "数量",
    "InvoiceDate": "开票时间", "UnitPrice": "单价（英镑）", "CustomerID": "客户编号", "Country": "国家",
}
ENCODING = "gb18030"


def sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def rel(path: str) -> str:
    """相对仓库根目录的路径；Windows 上跨盘符（如临时目录在 C:、仓库在 D:）时原样返回。"""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def raw_retail_path() -> str:
    return os.path.join(OUT, "raw", "Online Retail.xlsx")


def ensure_uci() -> str:
    path = raw_retail_path()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print("下载 UCI Online Retail …")
        z = zipfile.ZipFile(io.BytesIO(fetch(UCI_URL)))
        with open(path, "wb") as f:
            f.write(z.read("Online Retail.xlsx"))
    h = sha12(open(path, "rb").read())
    if UCI_XLSX_SHA256 and h != UCI_XLSX_SHA256:
        sys.exit(f"Online Retail.xlsx 指纹不符：{h} != {UCI_XLSX_SHA256}")
    print(f"  Online Retail.xlsx sha256[:12] = {h}")
    return path


def excel_style(ts: pd.Series) -> pd.Series:
    """2010-12-01 08:26:00 → '2010/12/1 8:26'（国内 Excel 另存 CSV 的常见样子）。"""
    return (ts.dt.year.astype(str) + "/" + ts.dt.month.astype(str) + "/" + ts.dt.day.astype(str) + " "
            + ts.dt.hour.astype(str) + ":" + ts.dt.minute.map("{:02d}".format))


def dirty_retail(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["InvoiceDate"] = excel_style(df["InvoiceDate"])
    cid = df["CustomerID"].map(lambda v: "未登记" if pd.isna(v) else str(int(v)))
    df["CustomerID"] = cid
    df["InvoiceNo"] = df["InvoiceNo"].astype(str)
    df["StockCode"] = df["StockCode"].astype(str)
    return df.rename(columns=RETAIL_COLUMNS)


def write_csv(df: pd.DataFrame, path: str, header_rows: list[list[str]] | None = None, footer=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = df.to_csv(index=False, lineterminator="\r\n")
    head = "".join(",".join(r) + "\r\n" for r in (header_rows or []))
    tail = (",".join(footer) + "\r\n") if footer else ""
    with open(path, "wb") as f:
        f.write((head + body + tail).encode(ENCODING))
    print(f"  {rel(path)}  {len(df)} 行  sha256[:12]={sha12(open(path, 'rb').read())}")


def build_retail():
    raw = pd.read_excel(ensure_uci())
    df = dirty_retail(raw)
    write_csv(df, os.path.join(OUT, "retail", "零售明细.csv"))
    # 报表导出变体：两行表头（第一行是合并单元格导出后的分组名，空格位置留空），末尾一行合计
    # 列顺序：发票号 商品编码 商品描述 数量 开票时间 单价 客户编号 国家
    groups = ["订单信息", "商品信息", "", "", "订单信息", "商品信息", "客户信息", ""]
    total = ["合计", "", "", str(int(raw["Quantity"].sum())), "", "", "", ""]
    write_csv(df, os.path.join(OUT, "retail_report", "零售报表.csv"), header_rows=[groups], footer=total)


def build_olist():
    d = os.path.join(OUT, "olist")
    os.makedirs(d, exist_ok=True)
    for name, want in OLIST_FILES.items():
        target = os.path.join(d, OLIST_SHORT[name])
        if not os.path.exists(target):
            print(f"下载 {name} …")
            data = fetch(OLIST_BASE + name)
            if sha12(data) != want:
                sys.exit(f"{name} 指纹不符：{sha12(data)} != {want}")
            open(target, "wb").write(data)
        print(f"  {rel(target)}  sha256[:12]={sha12(open(target, 'rb').read())}")


if __name__ == "__main__":
    build_retail()
    build_olist()
