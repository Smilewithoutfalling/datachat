"""从模型写的 pandas 代码里抽「引用了哪些列」「有哪些过滤条件」「用了哪些名字和 import」，并判「修复改没改口径」
（纯 AST，确定性，不调模型）。

阶段 7.5 第 3 步 S3-2（docs/roadmap/phase75-step3.md §3）从 `app/assess/code_refs.py` + `contracts.scope_of /
reviewer_scope` 搬来：产品链路（`app/graph.py` 的口径闸）和评估层（`app/assess/contracts.py` 的 reviewer.scope）
共用这一份判定。`app/assess/code_refs.py` 只剩 re-export。搬家前后对同一批输入的输出逐字节一致，由
`tests/test_code_scope_golden.py` 对照 `tests/fixtures/code_scope/golden.json`（搬家前用旧路径冻结）钉住。

抽取不追求完美，只求：认出来的一定是列引用（宁可漏，不误报）。规则：

- 数据根：单表的 `df`，多表的 `dfs['表名']`；以及由它们**保持列不变**地派生出来的变量
  （`d = df[mask]`、`d = df.copy()`、`d = df.query(...)`、`d = df.sort_values(...)` 等）；
- 列引用：根上的 `x['列']` / `x[['列', ...]]` / `x.loc[行, '列']`、`x.列`（不是 DataFrame 自身属性时）、
  根上的列参数方法（groupby / sort_values / drop_duplicates / dropna(subset) / set_index / pivot_table /
  merge(on, left_on) / nlargest / nsmallest），以及 `根.groupby(...)[...]` 与 `.agg({...})` 的键；
- 新造的列名（`x['新列'] = …`、`assign(新列=…)`、命名聚合、`rename(columns={...})` 的新名字……）记为 created，
  引用它不算「不存在的列」。

本模块在 A 组（app/tools/），不 import app/assess 的任何东西。
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


def _condition_items(tree, name_is_col: bool = False) -> set:
    """过滤条件，每条一个 (规范化字符串, 列, 运算符键, 比较值)。字符串与搬家前 `_conditions` 逐字一致；
    后三项给字面量豁免用（同列、同运算符、只换比较值）。没有比较值的条件（isna 这类、query 解析失败）列为 None，
    不参与豁免。运算符键带上列在哪一侧（`r:` 前缀 = 列在右侧），两侧不同不算「同运算符」。"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and len(n.ops) == 1:
            left, right, op = n.left, n.comparators[0], _CMP_OPS.get(type(n.ops[0]), type(n.ops[0]).__name__)
            lc = (left.id if name_is_col and isinstance(left, ast.Name) else _col_of(left))
            rc = (right.id if name_is_col and isinstance(right, ast.Name) else _col_of(right))
            if lc is not None:
                v = ast.unparse(right)
                out.add((f"{lc} {op} {v}", lc, op, v))
            elif rc is not None:
                v = ast.unparse(left)
                out.add((f"{v} {op} {rc}", rc, "r:" + op, v))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            m = n.func.attr
            recv = n.func.value
            if m in ("isin", "between"):
                c = recv.id if name_is_col and isinstance(recv, ast.Name) else _col_of(recv)
                if c is not None:
                    v = ', '.join(ast.unparse(a) for a in n.args)
                    out.add((f"{c} {m} {v}", c, m, v))
            elif m in _STR_FILTERS and isinstance(recv, ast.Attribute) and recv.attr == "str":
                c = _col_of(recv.value)
                if c is not None:
                    v = ', '.join(ast.unparse(a) for a in n.args)
                    out.add((f"{c} str.{m} {v}", c, f"str.{m}", v))
            elif m in _NULL_FILTERS and not n.args:
                c = _col_of(recv)
                if c is not None:
                    out.add((f"{c} {m}", c, m, None))
            elif m == "query" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                try:
                    sub = ast.parse(n.args[0].value.replace("`", ""), mode="eval")
                except SyntaxError:
                    out.add((f"query {n.args[0].value!r}", None, "query", None))
                else:
                    out |= _condition_items(sub, name_is_col=True)
    return out


def _conditions(tree, name_is_col: bool = False) -> set:
    return {t[0] for t in _condition_items(tree, name_is_col)}


def filter_conditions(code: str) -> set | None:
    """代码里的过滤 / 比较条件集合（「列 运算 值」的规范化字符串）；代码解析不了返回 None。"""
    tree = parse(code)
    return None if tree is None else _conditions(tree)


def filter_items(code: str) -> set | None:
    """同 filter_conditions，但每条带 (字符串, 列, 运算符键, 比较值)；解析不了返回 None。"""
    tree = parse(code)
    return None if tree is None else _condition_items(tree)


# ------------------------------------------------------------------ 口径（第 3 步 S3-2）
def table_columns(columns: dict, table) -> set:
    """表名对应的列集合；表名不在 columns 里（多表时引用了不存在的表）按全部列算。"""
    if table in columns:
        return set(columns[table])
    return {c for cols in columns.values() for c in cols}


def missing_columns(refs: CodeRefs, columns: dict) -> list:
    """代码引用了、但表里没有（也不是代码自己新造）的列，按出现顺序去重；多表写成「表.列」。"""
    out = []
    for table, col in refs.columns:
        if col in refs.created or col in table_columns(columns, table):
            continue
        label = f"{table}.{col}" if table else col
        if label not in out:
            out.append(label)
    return out


def columns_of(data) -> dict:
    """数据集的列名表：单表 {"": [列]}，多表 {表名: [列]}；列名一律转 str（与快照 run 行的 columns 同口径）。"""
    from app.tools.dataset import is_multi
    if is_multi(data):
        return {str(k): [str(c) for c in v.columns] for k, v in data.items()}
    return {"": [str(c) for c in data.columns]}


def analyze_for(code: str, columns: dict, multi: bool, result_var: str = "result") -> CodeRefs | None:
    return analyze_code(code, multi=multi, tables=[t for t in columns if t], result_var=result_var)


def scope_of(code: str, columns: dict, multi: bool, result_var: str = "result"):
    """(schema 内被引用的列集合, 引用了但 schema 里没有的列集合, 过滤条件集合)；解析不了返回 None。"""
    refs = analyze_for(code, columns, multi, result_var)
    conds = filter_conditions(code)
    if refs is None or conds is None:
        return None
    cols = {c for t, c in refs.columns if c in table_columns(columns, t)}
    return cols, set(missing_columns(refs, columns)), conds


# 判定结果的四种状态。CHANGED = 改了口径；UNPARSED_AFTER = 修复后的代码解析不了
# （评估层记 fail；产品口径闸不拦，交给 executor，见 app/graph.py）。
SCOPE_OK, SCOPE_CHANGED, SCOPE_NOT_CHECKED, SCOPE_UNPARSED_AFTER = "ok", "changed", "not_checked", "unparsed_after"


@dataclass
class ScopeCheck:
    status: str
    parts: list = field(default_factory=list)       # 改了什么（「列：+a -b」「过滤条件：+[…] -[…]」），CHANGED 时非空
    details: dict = field(default_factory=dict)
    note: str = ""                                  # 放行 / 不查的一句说明（不含前缀）

    @property
    def changed(self) -> bool:
        return self.status == SCOPE_CHANGED

    def summary(self) -> str:
        return "；".join(self.parts)


def _literal_swap(f0: set, f1: set, items0: set, items1: set) -> list | None:
    """字面量豁免（phase75-step3.md §3 / §7 第 2 条）：增删的过滤条件能一一配成「同列、同运算符、只换比较值」时，
    返回 [(旧, 新)]；有任何一条配不上（新增 / 删掉一条条件、换了列、换了运算符、条件没有比较值）返回 None。"""
    removed, added = f0 - f1, f1 - f0
    if not removed or len(removed) != len(added):
        return None
    key0 = {t[0]: (t[1], t[2]) for t in items0 if t[0] in removed and t[1] is not None and t[3] is not None}
    key1 = {t[0]: (t[1], t[2]) for t in items1 if t[0] in added and t[1] is not None and t[3] is not None}
    if len(key0) != len(removed) or len(key1) != len(added):
        return None
    if len(set(key0.values())) != len(key0) or len(set(key1.values())) != len(key1):
        return None                                  # 同一列同一运算符出现两次：配对有歧义，不豁免
    by_key = {k: s for s, k in key1.items()}
    pairs = []
    for s0, k in sorted(key0.items()):
        if k not in by_key:
            return None
        pairs.append((s0, by_key[k]))
    return pairs


def compare_scope(before_code: str, after_code: str, columns: dict, multi: bool, *, result_var: str = "result",
                  not_code: bool = False, truncated: bool = False, empty_before: bool = False) -> ScopeCheck:
    """修复前后比口径。列集合只算 schema 里真有的列。规定：

    - 修复前引用了 k 个不存在的列（KeyError 那类），修复后最多可以新增 k 个 schema 里的列 —— 把拼错的列名改对
      （'regin' → 'region'）不是换口径；
    - **字面量豁免**（empty_before=True，即修复前结果为空）：同一列、同一运算符的过滤条件只换了比较值，不算换口径
      （'华东' → '华东区'：把写错的取值改对，不是换问题）；
    - 除此之外，增删任何一个真实列、增删改任何一个过滤条件都是 CHANGED。

    修复前不是完整代码（not_code / truncated）或解析不了 → NOT_CHECKED；修复后解析不了 → UNPARSED_AFTER。"""
    if not_code or truncated:
        return ScopeCheck(SCOPE_NOT_CHECKED, note="修复前不是完整代码，无从比较")
    before = scope_of(before_code or "", columns, multi, result_var)
    if before is None:
        return ScopeCheck(SCOPE_NOT_CHECKED, note="修复前的代码无法解析，无从比较")
    after = scope_of(after_code or "", columns, multi, result_var)
    if after is None:
        return ScopeCheck(SCOPE_UNPARSED_AFTER, note="修复后的代码无法解析")
    (c0, miss0, f0), (c1, _miss1, f1) = before, after
    added, removed = c1 - c0, c0 - c1
    parts, details = [], {}
    if removed or len(added) > len(miss0):
        details["columns_added"], details["columns_removed"] = sorted(added), sorted(removed)
        parts.append("列：" + " ".join([f"+{c}" for c in sorted(added)] + [f"-{c}" for c in sorted(removed)]))
    swapped = None
    if f0 != f1 and empty_before:
        swapped = _literal_swap(f0, f1, filter_items(before_code or ""), filter_items(after_code or ""))
    if f0 != f1 and swapped is None:
        details["filters_added"], details["filters_removed"] = sorted(f1 - f0), sorted(f0 - f1)
        parts.append("过滤条件：" + " ".join([f"+[{c}]" for c in sorted(f1 - f0)] + [f"-[{c}]" for c in sorted(f0 - f1)]))
    if parts:
        return ScopeCheck(SCOPE_CHANGED, parts=parts, details=details)
    notes, ok_details = [], {}
    if added:
        notes.append("把不存在的列改成了：" + "、".join(sorted(added)))
        ok_details.update({"fixed_missing": sorted(miss0), "columns_added": sorted(added)})
    if swapped:
        notes.append("空结果下替换了过滤条件的取值：" + "、".join(f"[{a}] → [{b}]" for a, b in swapped))
        ok_details["literal_swaps"] = [list(p) for p in swapped]
    return ScopeCheck(SCOPE_OK, details=ok_details, note="；".join(notes))
