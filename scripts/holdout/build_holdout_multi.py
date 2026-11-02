"""留出集（H1）多表数据构建：Inside Airbnb → 四张中文表。

**只改呈现，不改数值** —— 与 `scripts/gate/build_gate_data.py` 同一条原则。标准答案由
`verify_holdout.py` 在**原始数据**上算一遍、在脏化表上再算一遍，两边不等就拒绝写答案。

数据与题面都不进 git（`scripts/holdout/README.md` 规则 1）。输出目录由 `--out` 指定。

用法：
    python scripts/holdout/build_holdout_multi.py --out D:/datachat_holdout/data
    python scripts/holdout/build_holdout_multi.py --out D:/datachat_holdout/data --check

## 数据源与许可（2026-11-02 核对）

Inside Airbnb（https://insideairbnb.com/get-the-data/），Albany, New York, 2026-09-14 快照。

页面原文（`get-the-data` 页面 HTML，两个许可段都在）：
- 当前季度数据：``This data is licensed under a Creative Commons Attribution 4.0
  International License``，链接 ``creativecommons.org/licenses/by/4.0/``
- 归档数据：``To the extent possible under law, Murray Cox has waived all copyright and
  related or neighboring rights to Inside Airbnb Data``（CC0）

`docs/roadmap/phase7-accuracy.md` §1 第 5 条要求「只用 CC BY / CC0 / 公有领域」——
这两个许可都在允许范围内，且**不是** Olist 那种 NC。

## 为什么选这个而不是 Chinook / Pagila

两个示例库（MIT / PostgreSQL License）表更多、关系更深，但它们是**软件许可**、数据是合成的。
H1 存在的意义是「非自造的、真实的脏数据」，真实脏值（价格带 `$`、6.6% 价格缺失、
`available` 是 `t`/`f`、90 列里 15 列全空）不是我能造出来的。许可上 CC BY 4.0 也比 MIT
更贴合 §1 的字面要求。

## 四张表与外键

| 输出 | 来源 | 行数 | 角色 |
|---|---|---|---|
| `房源.csv` | `data/listings.csv.gz` | 500 | 维度 + 事实混合（价格、房型在这里） |
| `可订日历.csv` | `data/calendar.csv.gz` | 182,500 | 事实表，`房源编号` → 房源 |
| `评论.csv` | `data/reviews.csv.gz` | 30,251 | 事实表，`房源编号` → 房源 |
| `社区.csv` | `visualisations/neighbourhoods.csv` | 15 | 维度表，`社区` → 房源 |

外键实测（2026-11-02）：calendar 覆盖 500/500 房源、reviews 覆盖 449/500，
**孤儿 0 条**；`社区.csv` 的 15 个值 = `房源.社区` 的 15 个值，完全一致。

## 两个必须写下来的限制

1. **`calendar.csv` 没有 `price` 列。** Inside Airbnb 的 2026 版把它删了，只剩
   `listing_id / date / available / minimum_nights / maximum_nights`。所以
   「某天的价格」这类题出不了，价格只能取 `listings.price`（每房源的标价）。
   这不是我们裁剪掉的，是源数据就没有。
2. **`listings.csv` 有 90 列，其中 15 列 100% 全空**（`host_since`、`host_response_rate`、
   `neighborhood_overview` 等，Inside Airbnb 对 Albany 做了隐私裁剪）。裁列是必需的：
   90 列的 schema 摘要会比题面长一个数量级。**裁剪只删列，不删行、不改值。**
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys

import pandas as pd

# 下载源（题库缓存里必须有这几个文件；脚本不联网，避免 CI 里静默拉数据）
CACHE = "_cache/insideairbnb"
FILES = {
    "listings": "listings.csv.gz",
    "calendar": "calendar.csv.gz",
    "reviews": "reviews.csv.gz",
    "neighbourhoods": "neighbourhoods.csv",
}

# 保留列 → 中文列名。顺序即输出列序。
# 选择标准：① 原始表里这列有值（不是 100% 空）② 能支撑至少一道题。
LISTINGS_COLS = {
    "id": "房源编号",
    "host_id": "房东编号",
    "neighbourhood_cleansed": "社区",
    "latitude": "纬度",
    "longitude": "经度",
    "property_type": "房源类型",
    "room_type": "房型",
    "accommodates": "可住人数",
    "bedrooms": "卧室数",
    "beds": "床位数",
    "bathrooms_text": "卫浴",
    "price": "每晚价格",
    "minimum_nights": "最少夜数",
    "maximum_nights": "最多夜数",
    "availability_365": "全年可订天数",
    "number_of_reviews": "评论数",
    "number_of_reviews_ltm": "近一年评论数",
    "review_scores_rating": "评分",
    "reviews_per_month": "每月评论数",
    "calculated_host_listings_count": "房东房源数",
    "last_scraped": "抓取日期",
}
# 刻意不保留 `instant_bookable`：它在 Albany 这份快照里 100% 为空（不是我们裁掉的）。

CALENDAR_COLS = {
    "listing_id": "房源编号",
    "date": "日期",
    "available": "可订",
    "minimum_nights": "最少夜数",
    "maximum_nights": "最多夜数",
}

REVIEWS_COLS = {
    "listing_id": "房源编号",
    "id": "评论编号",
    "date": "评论日期",
    "reviewer_id": "评论者编号",
    "comments": "评论内容",
}

NEIGHBOURHOODS_COLS = {
    "neighbourhood_group": "社区分组",
    "neighbourhood": "社区",
}

# 缺失写这个。和闸门一致（`build_gate_data.py` 用同一串）。
SENTINEL = "未登记"


def sha12(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def load(name: str, cache: str) -> pd.DataFrame:
    path = os.path.join(cache, FILES[name])
    if not os.path.exists(path):
        sys.exit(f"缺 {path}。先把 Inside Airbnb 的四个文件下到 {cache}/（见模块 docstring）。")
    if FILES[name].endswith(".gz"):
        with gzip.open(path, "rb") as f:
            df = pd.read_csv(f, low_memory=False)
    else:
        df = pd.read_csv(path, low_memory=False)
    # Inside Airbnb 的 neighbourhoods.csv 末尾有一个空行，会解析成一条全 NaN 记录。
    # 这不是"丢了一行数据"，是把 CSV 的行尾噪声去掉。
    n0 = len(df)
    df = df.dropna(how="all")
    if len(df) != n0:
        print(f"  {name}: 丢掉 {n0 - len(df)} 条全空行")
    return df


def pick(df: pd.DataFrame, mapping: dict, name: str) -> pd.DataFrame:
    """按 mapping 选列 + 改名。缺列直接报错 —— 源数据换版本时要人看见，不要静默少一列。"""
    missing = [c for c in mapping if c not in df.columns]
    if missing:
        sys.exit(f"{name} 缺列 {missing}；源数据版本可能变了，先核对再改映射。")
    out = df[list(mapping)].copy()
    out.columns = [mapping[c] for c in mapping]
    return out


def fill_sentinel(df: pd.DataFrame) -> pd.DataFrame:
    """空值写"未登记"。只对**文本列**做 —— 数值列写字符串会让整列退化成 object，
    模型连 `mean()` 都调不了，那已经不是"脏"而是"坏"。数值列的缺失保持 NaN（写出来是空串），
    这也是真实系统导出的样子。"""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].fillna(SENTINEL)
    return out


def write_gbk(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="gb18030", lineterminator="\r\n")


def build(out: str) -> dict:
    cache = os.path.join(out, CACHE)
    tables = {}

    L = pick(load("listings", cache), LISTINGS_COLS, "listings")
    C = pick(load("calendar", cache), CALENDAR_COLS, "calendar")
    R = pick(load("reviews", cache), REVIEWS_COLS, "reviews")
    N = pick(load("neighbourhoods", cache), NEIGHBOURHOODS_COLS, "neighbourhoods")

    for name, df in (("房源", L), ("可订日历", C), ("评论", R), ("社区", N)):
        d = fill_sentinel(df)
        p = os.path.join(out, "民宿", f"{name}.csv")
        write_gbk(d, p)
        tables[name] = {
            "rows": int(len(d)),
            "cols": int(d.shape[1]),
            "sha12": sha12(p),
            "path": f"民宿/{name}.csv",
        }
        print(f"  {name:6} {len(d):7,d} 行 × {d.shape[1]:2d} 列  {tables[name]['sha12']}")

    # 指纹记在数据目录里，答案脚本用它核对「跑的是不是同一份数据」
    meta = {
        "source": "Inside Airbnb — Albany, New York, 2026-09-14",
        "license": "CC BY 4.0（当前季度数据）；归档数据为 CC0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "built_at": "2026-11-02",
        "tables": tables,
    }
    with open(os.path.join(out, "民宿", "_meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return meta


def check(out: str) -> list[str]:
    """校验：行数、外键、被裁掉的列确实没值。返回问题列表（空 = 通过）。"""
    bad = []
    d = os.path.join(out, "民宿")
    L = pd.read_csv(os.path.join(d, "房源.csv"), encoding="gb18030", low_memory=False)
    C = pd.read_csv(os.path.join(d, "可订日历.csv"), encoding="gb18030", low_memory=False)
    R = pd.read_csv(os.path.join(d, "评论.csv"), encoding="gb18030", low_memory=False)
    N = pd.read_csv(os.path.join(d, "社区.csv"), encoding="gb18030")

    if len(L) != 500:
        bad.append(f"房源行数 {len(L)} ≠ 500")
    if len(C) != 182500:
        bad.append(f"可订日历行数 {len(C)} ≠ 182500")
    if len(R) != 30251:
        bad.append(f"评论行数 {len(R)} ≠ 30251")

    li = set(L["房源编号"])
    orphan_c = len(set(C["房源编号"]) - li)
    orphan_r = len(set(R["房源编号"]) - li)
    if orphan_c:
        bad.append(f"可订日历有 {orphan_c} 个孤儿房源")
    if orphan_r:
        bad.append(f"评论有 {orphan_r} 个孤儿房源")

    a, b = set(L["社区"].dropna()), set(N["社区"].dropna())
    if a != b:
        bad.append(f"社区不一致：仅房源有 {a - b}，仅社区表有 {b - a}")

    # 价格必须仍带 $（这是真实的，不该被我们的管线洗掉）
    p = L["每晚价格"].astype(str)
    if not p.str.startswith("$").any():
        bad.append("每晚价格已不带 $ —— 脏化管线把它洗掉了")

    # 全空列不该被保留进来
    for c in L.columns:
        if L[c].isna().all():
            bad.append(f"房源.{c} 是全空列，不该保留")
    return bad


def main() -> None:
    args = sys.argv[1:]
    if "--out" not in args:
        sys.exit("用法: build_holdout_multi.py --out <数据目录> [--check]")
    out = args[args.index("--out") + 1]
    os.makedirs(os.path.join(out, CACHE), exist_ok=True)

    if "--check" in args:
        bad = check(out)
        for b in bad:
            print("  ✗", b)
        print("通过" if not bad else f"{len(bad)} 条问题")
        sys.exit(1 if bad else 0)

    print("构建多表数据：")
    meta = build(out)
    print(f"\n四张表已写出到 {os.path.join(out, '民宿')}")
    print(f"许可：{meta['license']}")


if __name__ == "__main__":
    main()
