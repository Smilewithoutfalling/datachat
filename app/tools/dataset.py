"""数据集：单表或多表（阶段 3.5，M10 的最小实现）。

dataset 的三种形式：
- 一个 CSV 路径                → 单表，代码里用变量 df；
- 一个目录                     → 目录下每个 *.csv（不含 *.dict.csv）是一张表，表名 = 文件名去扩展名；
- 一个 CSV 路径的 list / tuple → 同上，多表。
多表时代码里用 dict 变量 dfs（表名 → DataFrame），没有 df。

刻意不做的事（留给阶段 4/7）：不声明表间关联（join key 由模型从列名和样例自己判断，
这正是外部验证闸门要测的"schema 理解"）；不做 DuckDB；不支持 Excel。
"""
from __future__ import annotations

import os

import pandas as pd

from app.tools.csv_io import read_csv_with_encoding
from app.tools.schema import clip, describe_df, MAX_NAME_CHARS

SINGLE_ACCESS = "数据已加载到变量 df（pandas DataFrame），不要重新读取文件。"
REVIEW_SINGLE_ACCESS = "用变量 df，不要重新读文件；"   # reviewer 的原措辞，单表时 prompt 与阶段 3 逐字一致


def is_dict_file(path: str) -> bool:
    return os.path.basename(path).lower().endswith(".dict.csv")


def table_paths(dataset) -> list[tuple[str, str]] | None:
    """多表数据集返回 [(表名, 路径), ...]（按表名排序）；单个 CSV 返回 None。"""
    if isinstance(dataset, (list, tuple)):
        paths = [os.fspath(p) for p in dataset]
    else:
        dataset = os.fspath(dataset)
        if not os.path.isdir(dataset):
            return None
        paths = [os.path.join(dataset, f) for f in os.listdir(dataset)
                 if f.lower().endswith(".csv") and not is_dict_file(f)]
        if not paths:
            raise FileNotFoundError(f"目录里没有 CSV 文件：{dataset}")
    out = {}
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        if name in out:
            raise ValueError(f"表名重复：{name}（{out[name]} 与 {p}）")
        out[name] = p
    return sorted(out.items())


def dataset_label(dataset) -> str:
    if isinstance(dataset, (list, tuple)):
        return ";".join(os.fspath(p) for p in dataset)
    return os.fspath(dataset)


def load_data(dataset, encoding: str | None = None):
    """返回 (data, 说明文本)。data 是 DataFrame（单表）或 {表名: DataFrame}（多表）。"""
    tables = table_paths(dataset)
    if tables is None:
        df, enc = read_csv_with_encoding(os.fspath(dataset), encoding)
        return df, f"{len(df)} 行 × {len(df.columns)} 列，编码 {enc}"
    data, parts = {}, []
    for name, path in tables:
        df, enc = read_csv_with_encoding(path, encoding)
        data[name] = df
        parts.append(f"{name} {len(df)}×{len(df.columns)}（{enc}）")
    return data, f"{len(data)} 张表：" + "，".join(parts)


def is_multi(data) -> bool:
    return isinstance(data, dict)


def copy_data(data):
    return {k: v.copy() for k, v in data.items()} if is_multi(data) else data.copy()


def access_rule(data) -> str:
    """告诉模型代码里怎么拿到数据（放进 prompt 的约定行）。"""
    if not is_multi(data):
        return SINGLE_ACCESS
    names = "、".join(f"dfs['{clip(k, MAX_NAME_CHARS)}']" for k in data)
    return ("数据集包含多张表，已加载到 dict 变量 dfs（表名 → pandas DataFrame）：" + names +
            "；没有变量 df。表之间怎么关联要根据列名和样例自己判断。不要重新读取文件。")


def review_access_rule(data) -> str:
    return REVIEW_SINGLE_ACCESS if not is_multi(data) else access_rule(data)


def describe_data(data, n: int = 3) -> str:
    """单表 = describe_df；多表 = 每张表一段（各自包进数据分隔块）。"""
    if not is_multi(data):
        return describe_df(data, n=n)
    blocks = [f"数据集共 {len(data)} 张表（代码中用 dfs['表名'] 访问）。"]
    for name, df in data.items():
        blocks.append(f"\n## 表 dfs['{clip(name, MAX_NAME_CHARS)}']\n{describe_df(df, n=n)}")
    return "\n".join(blocks)
