"""从模型写的 pandas 代码里抽「引用了哪些列」「有哪些过滤条件」「用了哪些名字和 import」（纯 AST，确定性）。

不追求完美，只求：认出来的一定是列引用（宁可漏，不误报）。规则：

- 数据根：单表的 `df`，多表的 `dfs['表名']`；以及由它们**保持列不变**地派生出来的变量
  （`d = df[mask]`、`d = df.copy()`、`d = df.query(...)`、`d = df.sort_values(...)` 等）；
- 列引用：根上的 `x['列']` / `x[['列', ...]]` / `x.loc[行, '列']`、`x.列`（不是 DataFrame 自身属性时）、
  根上的列参数方法（groupby / sort_values / drop_duplicates / dropna(subset) / set_index / pivot_table /
  merge(on, left_on) / nlargest / nsmallest），以及 `根.groupby(...)[...]` 与 `.agg({...})` 的键；
- 新造的列名（`x['新列'] = …`、`assign(新列=…)`、命名聚合、`rename(columns={...})` 的新名字……）记为 created，
  引用它不算「不存在的列」。
"""
from __future__ import annotations

import ast
import builtins as _builtins
from dataclasses import dataclass, field
from functools import lru_cache

# 不改列集合的方法：结果仍是同一张表的行子集 / 重排 / 副本
_ROW_PRESERVING = {
    "copy", "query", "dropna", "fillna", "sort_values", "sort_index", "head", "tail", "drop_duplicates",
    "astype", "assign", "nlargest", "nsmallest", "sample", "where", "mask", "infer_objects", "convert_dtypes",
}
_ROW_ACCESSORS = {"loc", "iloc"}
# 方法名 → (位置参数下标列表, 关键字名列表)：这些位置上的字符串是列名
_COLUMN_ARGS = {
    "groupby": ([0], ["by"]),
    "sort_values": ([0], ["by"]),
    "drop_duplicates": ([0], ["subset"]),
    "dropna": ([], ["subset"]),
    "set_index": ([0], ["keys"]),
    "pivot_table": ([], ["index", "columns", "values"]),
    "pivot": ([], ["index", "columns", "values"]),
    "merge": ([], ["on", "left_on"]),
    "nlargest": ([1], ["columns"]),
    "nsmallest": ([1], ["columns"]),
}
_CMP_OPS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            ast.In: "in", ast.NotIn: "not in", ast.Is: "is", ast.IsNot: "is not"}
_STR_FILTERS = {"contains", "startswith", "endswith", "match", "fullmatch"}
_NULL_FILTERS = {"isna", "isnull", "notna", "notnull"}


@lru_cache(maxsize=1)
def frame_attrs() -> frozenset:
    import pandas as pd
    return frozenset(dir(pd.DataFrame))


@lru_cache(maxsize=1)
def library_names() -> frozenset:
    """pandas / numpy / Python 里会出现在计划或代码里的名字（方法名、函数名）：不当列名看。"""
    import numpy as np
    import pandas as pd
    from pandas.core.groupby import DataFrameGroupBy, SeriesGroupBy
    names = set(dir(pd.DataFrame)) | set(dir(pd.Series)) | set(dir(pd)) | set(dir(np))
    names |= set(dir(DataFrameGroupBy)) | set(dir(SeriesGroupBy)) | set(dir(_builtins))
    names |= set(dir(pd.Series.str)) | set(dir(pd.Series.dt)) | set(dir(pd.Timestamp))
    return frozenset(names)


def parse(code: str):
    try:
        return ast.parse(code or "")
    except (SyntaxError, ValueError):
        return None


def _str_list(node) -> list[str] | None:
    """'a' → ['a']；['a', 'b'] / ('a', 'b') → ['a', 'b']；其他 → None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


@dataclass
class CodeRefs:
    columns: list = field(default_factory=list)      # [(表名, 列名)]，单表表名为 ""
    created: set = field(default_factory=set)        # 代码里新造的列名
    bad_tables: list = field(default_factory=list)   # dfs['不存在的表']
    imports: list = field(default_factory=list)      # [(顶层模块名, 是否相对导入)]
    free_names: set = field(default_factory=set)     # 读了、但代码里从没绑定过的名字
    assigns_result: bool = False


class _Analyzer:
    def __init__(self, multi: bool, tables: set, result_var: str = "result"):
        self.multi = multi
        self.tables = tables
        self.result_var = result_var
        self.alias: dict = {}
        self.refs = CodeRefs()

    # -------------------------------------------------------------- 根
    def frame_root(self, e):
        """表达式是不是（与原表列集合相同的）数据表：是 → 表名（单表 ""），否 → None。"""
        if isinstance(e, ast.Name):
            if not self.multi and e.id == "df":
                return ""
            return self.alias.get(e.id)
        if isinstance(e, ast.Subscript):
            if self.multi and isinstance(e.value, ast.Name) and e.value.id == "dfs":
                s = e.slice
                if isinstance(s, ast.Constant) and isinstance(s.value, str):
                    return s.value
                return None
            if isinstance(e.value, ast.Attribute) and e.value.attr in _ROW_ACCESSORS:
                if isinstance(e.slice, ast.Tuple):
                    return None                  # .loc[行, 列]：取的是列子集或单列，不再当整表
                return self.frame_root(e.value.value)
            s = e.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                return None                      # x['列'] 是 Series
            if _str_list(s) is not None:
                return self.frame_root(e.value)  # 列子集：列名仍是原表的
            return self.frame_root(e.value)      # 布尔掩码等：行子集
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr in _ROW_PRESERVING:
            return self.frame_root(e.func.value)
        return None

    def group_root(self, e):
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "groupby"):
            return self.frame_root(e.func.value)
        return None

    def _add(self, table, names):
        for n in names or []:
            self.refs.columns.append((table, n))

    # -------------------------------------------------------------- 遍历
    def run(self, tree):
        assigns = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Assign)), key=lambda n: (n.lineno, n.col_offset))
        for a in assigns:                           # 两遍：别名可能在用到之前的语句里才建立（源码顺序）
            for t in a.targets:
                if isinstance(t, ast.Name):
                    r = self.frame_root(a.value)
                    if r is not None:
                        self.alias[t.id] = r
        bound = set()
        loaded = set()
        for n in ast.walk(tree):
            self._visit(n, bound, loaded)
        self.refs.free_names = loaded - bound
        return self.refs

    def _visit(self, n, bound, loaded):
        refs = self.refs
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ast.Load):
                loaded.add(n.id)
            else:
                bound.add(n.id)
                if n.id == self.result_var:
                    refs.assigns_result = True
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                refs.imports.append((a.name.split(".")[0], False))
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            refs.imports.append(((n.module or "").split(".")[0], bool(n.level)))
            for a in n.names:
                bound.add(a.asname or a.name)
        elif isinstance(n, ast.Subscript):
            self._subscript(n)
        elif isinstance(n, ast.Attribute):
            if isinstance(n.ctx, ast.Load) and not n.attr.startswith("_") and n.attr not in frame_attrs():
                r = self.frame_root(n.value)
                if r is not None:
                    self._add(r, [n.attr])
        elif isinstance(n, ast.Call):
            self._call(n)
        elif isinstance(n, ast.Assign):
            for t in n.targets:                    # x.columns = ['a', 'b'] → 新列名
                if isinstance(t, ast.Attribute) and t.attr == "columns":
                    refs.created.update(_str_list(n.value) or [])

    def _subscript(self, n):
        refs = self.refs
        names = _str_list(n.slice)
        if isinstance(n.ctx, (ast.Store, ast.Del)):
            if names:
                refs.created.update(names)
            return
        if self.multi and isinstance(n.value, ast.Name) and n.value.id == "dfs":
            if names and len(names) == 1 and names[0] not in self.tables:
                refs.bad_tables.append(names[0])
            return
        base = n.value
        if isinstance(base, ast.Attribute) and base.attr in _ROW_ACCESSORS and isinstance(n.slice, ast.Tuple):
            r = self.frame_root(base.value)
            if r is not None and len(n.slice.elts) == 2 and base.attr == "loc":
                self._add(r, _str_list(n.slice.elts[1]))
            return
        if names is None:
            return
        r = self.frame_root(base)
        if r is None:
            r = self.group_root(base)
        if r is not None:
            self._add(r, names)

    def _call(self, n):
        refs = self.refs
        if not isinstance(n.func, ast.Attribute):
            return
        m = n.func.attr
        recv = n.func.value
        if m == "assign":
            refs.created.update(k.arg for k in n.keywords if k.arg)
        if m in ("agg", "aggregate"):
            refs.created.update(k.arg for k in n.keywords if k.arg)
            r = self.frame_root(recv)
            if r is None:
                r = self.group_root(recv)
            if r is not None:
                for k in n.keywords:               # 命名聚合：新列=('原列', 'sum')
                    if isinstance(k.value, ast.Tuple) and k.value.elts:
                        self._add(r, _str_list(k.value.elts[0]))
                if n.args and isinstance(n.args[0], ast.Dict):
                    self._add(r, [k.value for k in n.args[0].keys
                                  if isinstance(k, ast.Constant) and isinstance(k.value, str)])
        if m == "rename":
            for k in n.keywords:
                if k.arg == "columns" and isinstance(k.value, ast.Dict):
                    refs.created.update(v.value for v in k.value.values
                                        if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if m in ("reset_index", "to_frame"):
            for k in n.keywords:
                if k.arg == "name":
                    refs.created.update(_str_list(k.value) or [])
            if m == "to_frame" and n.args:
                refs.created.update(_str_list(n.args[0]) or [])
        if m in _COLUMN_ARGS:
            r = self.frame_root(recv)
            if r is None:
                return
            pos, kws = _COLUMN_ARGS[m]
            for i in pos:
                if i < len(n.args):
                    self._add(r, _str_list(n.args[i]))
            for k in n.keywords:
                if k.arg in kws:
                    self._add(r, _str_list(k.value))


def analyze_code(code: str, *, multi: bool, tables=(), result_var: str = "result") -> CodeRefs | None:
    tree = parse(code)
    if tree is None:
        return None
    return _Analyzer(multi, set(tables), result_var).run(tree)


# ------------------------------------------------------------------ 过滤条件
def _col_of(e):
    """条件一侧的列：沿 .str.xxx() / .dt.xxx / .astype() 这类链往里找第一个 x['列'] / x.列。"""
    while True:
        if isinstance(e, ast.Subscript):
            names = _str_list(e.slice)
            if names and len(names) == 1:
                return names[0]
            if isinstance(e.slice, ast.Tuple) and len(e.slice.elts) == 2:
                names = _str_list(e.slice.elts[1])
                if names and len(names) == 1:
                    return names[0]
            e = e.value
        elif isinstance(e, ast.Call):
            e = e.func
        elif isinstance(e, ast.Attribute):
            if isinstance(e.value, ast.Name) and e.attr not in frame_attrs() and not e.attr.startswith("_"):
                return e.attr
            e = e.value
        else:
            return None


def _conditions(tree, name_is_col: bool = False) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and len(n.ops) == 1:
            left, right, op = n.left, n.comparators[0], _CMP_OPS.get(type(n.ops[0]), type(n.ops[0]).__name__)
            lc = (left.id if name_is_col and isinstance(left, ast.Name) else _col_of(left))
            rc = (right.id if name_is_col and isinstance(right, ast.Name) else _col_of(right))
            if lc is not None:
                out.add(f"{lc} {op} {ast.unparse(right)}")
            elif rc is not None:
                out.add(f"{ast.unparse(left)} {op} {rc}")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            m = n.func.attr
            recv = n.func.value
            if m in ("isin", "between"):
                c = recv.id if name_is_col and isinstance(recv, ast.Name) else _col_of(recv)
                if c is not None:
                    out.add(f"{c} {m} {', '.join(ast.unparse(a) for a in n.args)}")
            elif m in _STR_FILTERS and isinstance(recv, ast.Attribute) and recv.attr == "str":
                c = _col_of(recv.value)
                if c is not None:
                    out.add(f"{c} str.{m} {', '.join(ast.unparse(a) for a in n.args)}")
            elif m in _NULL_FILTERS and not n.args:
                c = _col_of(recv)
                if c is not None:
                    out.add(f"{c} {m}")
            elif m == "query" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                try:
                    sub = ast.parse(n.args[0].value.replace("`", ""), mode="eval")
                except SyntaxError:
                    out.add(f"query {n.args[0].value!r}")
                else:
                    out |= _conditions(sub, name_is_col=True)
    return out


def filter_conditions(code: str) -> set | None:
    """代码里的过滤 / 比较条件集合（「列 运算 值」的规范化字符串）；代码解析不了返回 None。"""
    tree = parse(code)
    return None if tree is None else _conditions(tree)
