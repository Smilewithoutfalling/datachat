"""数据集：单表或多表（阶段 3.5，M10 的最小实现）。

dataset 的三种形式：
- 一个 CSV 路径                → 单表，代码里用变量 df；
- 一个 xlsx 路径               → 读出一张表时同单表 CSV（df）；读出多张时每个 sheet 一张表，表名 = 文件名.sheet名（dfs）；
- 一个目录                     → 目录下每个 *.csv（不含 *.dict.csv）和 *.xlsx 是表，表名 = 文件名去扩展名
                                 （多 sheet 的 xlsx 展开成 文件名.sheet名）；
- 一个 CSV / xlsx 路径的 list / tuple → 同上，多表。
多表时代码里用 dict 变量 dfs（表名 → DataFrame），没有 df。
xlsx 的读取规则（结构检测、告知、拒绝）在 app/tools/excel_io.py；.xls 不支持（理由见该文件）。

刻意不做的事（留给阶段 4/7）：不声明表间关联（join key 由模型从列名和样例自己判断，
这正是外部验证闸门要测的"schema 理解"）；不做 DuckDB。
"""
from __future__ import annotations

import os

import pandas as pd

from app.tools.csv_io import read_csv_with_encoding
from app.tools.schema import clip, describe_df, MAX_NAME_CHARS


class DatasetError(Exception):
    """数据集结构错误，文案是用户可读、不带路径的中文（T11：错误文案不带文件路径）。
    filename 只放文件名：多表数据集里某张表读坏时，用户要知道是哪一张。"""

    def __init__(self, message: str, *, filename: str | None = None):
        super().__init__(message)
        self.message = message
        self.filename = filename

    def __str__(self):   # OSError 子类（NoCSVError）的 str 不是 message，统一以 message 为准
        return self.message


class NoCSVError(DatasetError, FileNotFoundError):
    pass


class DuplicateTableError(DatasetError, ValueError):
    pass


class TableReadError(DatasetError):
    """多表里某张表读取失败：带文件名，原异常在 __cause__（user_error 用它选常量文案）。"""

SINGLE_ACCESS = "数据已加载到变量 df（pandas DataFrame），不要重新读取文件。"
REVIEW_SINGLE_ACCESS = "用变量 df，不要重新读文件；"   # reviewer 的原措辞，单表时 prompt 与阶段 3 逐字一致


def is_dict_file(path: str) -> bool:
    return os.path.basename(path).lower().endswith(".dict.csv")


def is_excel_file(path) -> bool:
    from app.tools.excel_io import is_excel
    return is_excel(path)


def _is_table_file(f: str) -> bool:
    low = f.lower()
    return (low.endswith(".csv") and not is_dict_file(f)) or is_excel_file(low)


def table_paths(dataset) -> list[tuple[str, str]] | None:
    """多表数据集返回 [(表名, 路径), ...]（按表名排序）；单个 CSV 返回 None。"""
    if isinstance(dataset, (list, tuple)):
        paths = [os.fspath(p) for p in dataset]
    else:
        dataset = os.fspath(dataset)
        if not os.path.isdir(dataset):
            return None
        paths = [os.path.join(dataset, f) for f in os.listdir(dataset) if _is_table_file(f)]
        if not paths:
            raise NoCSVError("目录里没有 CSV 文件")
    out = {}
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        if name in out:
            raise DuplicateTableError(
                f"表名重复：{name}（{os.path.basename(out[name])} 与 {os.path.basename(p)}）")
        out[name] = p
    return sorted(out.items())


def dataset_label(dataset) -> str:
    if isinstance(dataset, (list, tuple)):
        return ";".join(os.fspath(p) for p in dataset)
    return os.fspath(dataset)


def excel_tables(name: str, path: str):
    """读一个 xlsx，返回 [(表名, SheetTable), ...]。表名规则见 excel_io.table_names。"""
    from app.tools.excel_io import read_xlsx, table_names
    book = read_xlsx(path)
    return list(zip(table_names(name, [t.sheet for t in book.tables]), book.tables))


def load_warnings(df) -> list[str]:
    """一张表的读取提示（只有 xlsx 有；CSV 返回空列表）。"""
    from app.tools.excel_io import WARNINGS_ATTR
    return list(df.attrs.get(WARNINGS_ATTR) or [])


def _warn_suffix(dfs) -> str:
    n = sum(len(load_warnings(d)) for d in dfs)
    return f"；读取提示 {n} 条" if n else ""


def load_data(dataset, encoding: str | None = None):
    """返回 (data, 说明文本)。data 是 DataFrame（单表）或 {表名: DataFrame}（多表）。
    encoding 只对 CSV 生效；xlsx 不涉及文本编码。"""
    tables = table_paths(dataset)
    if tables is None:
        path = os.fspath(dataset)
        if not is_excel_file(path):
            df, enc = read_csv_with_encoding(path, encoding)
            return df, f"{len(df)} 行 × {len(df.columns)} 列，编码 {enc}"
        stem = os.path.splitext(os.path.basename(path))[0]
        named = excel_tables(stem, path)
        if len(named) == 1:
            t = named[0][1]
            return t.df, (f"{len(t.df)} 行 × {len(t.df.columns)} 列，xlsx 工作表「{t.sheet}」"
                          + _warn_suffix([t.df]))
        data = {n: t.df for n, t in named}
        return data, (f"{len(data)} 张表：" + "，".join(f"{n} {len(d)}×{len(d.columns)}（xlsx）" for n, d in data.items())
                      + _warn_suffix(data.values()))
    data, parts = {}, []
    for name, path in tables:
        if is_excel_file(path):
            try:
                named = excel_tables(name, path)
            except Exception as e:  # T11：同 CSV，只带文件名
                raise TableReadError(str(e), filename=os.path.basename(path)) from e
            for tname, t in named:
                if tname in data:
                    raise DuplicateTableError(f"表名重复：{tname}（{os.path.basename(path)} 里的工作表与另一张表同名）")
                data[tname] = t.df
                parts.append(f"{tname} {len(t.df)}×{len(t.df.columns)}（xlsx）")
            continue
        if name in data:
            raise DuplicateTableError(f"表名重复：{name}（{os.path.basename(path)} 与 xlsx 里的工作表同名）")
        try:
            df, enc = read_csv_with_encoding(path, encoding)
        except Exception as e:  # T11：多表里定位到是哪张表，只带文件名
            raise TableReadError(str(e), filename=os.path.basename(path)) from e
        data[name] = df
        parts.append(f"{name} {len(df)}×{len(df.columns)}（{enc}）")
    return data, f"{len(data)} 张表：" + "，".join(parts) + _warn_suffix(data.values())


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


def is_multi_access(rule, single_rule: str) -> bool:
    """从 state 里的取数约定行反推单表 / 多表（第 3 步 S3-1：codegen / reviewer 渲染沙箱句子时要知道注入的是 df 还是 dfs）。
    没有约定行（老快照、测试里的最小 state）按单表处理，与两处模板的默认值一致。"""
    return bool(rule) and rule != single_rule


def describe_data(data, n: int = 3) -> str:
    """单表 = describe_df；多表 = 每张表一段（各自包进数据分隔块）。"""
    if not is_multi(data):
        return describe_df(data, n=n)
    blocks = [f"数据集共 {len(data)} 张表（代码中用 dfs['表名'] 访问）。"]
    for name, df in data.items():
        blocks.append(f"\n## 表 dfs['{clip(name, MAX_NAME_CHARS)}']\n{describe_df(df, n=n)}")
    return "\n".join(blocks)
