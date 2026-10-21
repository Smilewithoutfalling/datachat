"""闸门数据指纹（G1）。本文件进 gate-oracle 的 cache key：改任何一个值，两个 OS 的缓存都会失效。

两组常量失效原因不同，分开放：
- 源文件（上游给的东西）：变了说明上游换了文件 → 查上游，别重登。
- 产物（我们的脏化代码 + pandas/openpyxl 生成）：变了说明生成逻辑或依赖变了 → 在同一个 PR 里重登并在 DEVLOG 写原因。
"""

# ---- 源文件：sha256 前 12 位（2026-10-12 下载）
UCI_XLSX_SHA256 = "43465a06f2cc"   # data/gate/raw/Online Retail.xlsx

OLIST_FILES = {   # 上游文件名 -> sha256 前 12 位
    "olist_customers_dataset.csv": "c26c17f59f30",
    "olist_order_items_dataset.csv": "4f6abdbbc940",
    "olist_order_payments_dataset.csv": "61674868ed7b",
    "olist_order_reviews_dataset.csv": "012b61c7593e",
    "olist_orders_dataset.csv": "8df58ef3d2d7",
    "olist_products_dataset.csv": "3e6569628a17",
    "olist_sellers_dataset.csv": "31eb9bd50d68",
    "product_category_name_translation.csv": "a81f0d1f27b2",
}

# ---- 产物：相对 data/gate 的路径 -> sha256 前 12 位（pandas 3.0.6 / openpyxl 3.1.5，engine=openpyxl）
PRODUCT_SHA12 = {
    "retail/零售明细.csv": "dbb0119d94e1",
    "retail_report/零售报表.csv": "ab8c674de110",
}
