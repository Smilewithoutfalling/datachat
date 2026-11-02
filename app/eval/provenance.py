"""答案来源归因（缺口 11 / 12）：`result` 这个值是怎么来的，或者为什么没来。

**只陈述事实，不进判分。** 两个字段各自的由来：

缺口 11 —— `ord_004` 有一跑 `executed=True`、代码也 print 出了正确数字，但**没赋 `result`**，
判分器只能判错，报告里看不出是"算错"还是"没交卷"。二者对模型的指导意义完全不同。

缺口 12 —— `biz_020` run1 写了 `result = '数码商品11'`（gold 26）。2026-11-02 用真实数据
复现证明：那是照上一行 `print` 自己算错的结果抄的（漏了 `sku` 大小写统一），**不是编造** ——
缺口 12 已关闭。但"值从哪来"仍值得记，缺口 11 的归因也依赖这套字段。

⚠️ **`literal_*` 不等于错。** 481 份真实代码里 40 条字面量，**37 条判对**
（`literal_scalar` 100%）：`result = 2537.39`、`result = 850854.16` 都是模型算完再写死。
这是**常规提交方式**，不是作弊。所以这里只标"值是不是算出来的"，不许自动判错。

值域：
- `"computed"`          —— 右侧含调用 / 下标 / 运算 / 数据变量引用，值来自运行时
- `"literal_text"`      —— 右侧是字符串（含无占位符的 f-string）
- `"literal_scalar"`    —— 右侧是数字 / 布尔 / `None`
- `"literal_container"` —— 右侧是纯字面量的 list / tuple / set / dict
- `"mutated"`           —— 没有直接赋值，只 `result.append(...)` 或 `result[k] = ...`
- `"unparsed"`          —— 代码有语法错，判不了（不猜）
- `None`                —— 代码里没碰过 `result`（配合 `result_missing="no_assign"` 读）

`result_missing` 只在 `executed=True and result is None` 时有值：
- `"no_assign"`   —— 没有对 `result` 的任何写入
- `"assign_none"` —— 写了，运行时值是 `None`
- `"empty"`       —— 写了空容器 `[]` / `{}`
- `"cond_assign"` —— 写入全在 if/for/while/try/with 体内，这次没走到
- `"in_function"` —— 写入全在函数体内（`run_trusted` 取的是全局命名空间，拿不到局部变量）
- `"unparsed"`    —— 代码有语法错
"""
import ast

__all__ = ["result_origin", "result_missing", "describe"]

_BRANCHY = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.IfExp)
_BRANCHY = _BRANCHY + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_MUTATORS = ("append", "extend", "update", "add", "insert", "setdefault")
_TRACE_DEPTH = 3          # `a = ...; b = a; result = b` 这类改写追三层够用


class _Write:
    """一次对 `result`（或普通变量）的写入。kind: assign / ann / mutate。"""

    __slots__ = ("kind", "value", "line", "in_branch", "in_func")

    def __init__(self, kind, value, line, in_branch, in_func):
        self.kind, self.value, self.line = kind, value, line
        self.in_branch, self.in_func = in_branch, in_func


def _parse(code: str):
    try:
        return ast.parse(code or ""), None
    except SyntaxError as e:                      # 模型给的代码语法错，归因为"判不了"，不猜
        return None, str(e)


def _parent_map(tree) -> dict:
    """父节点表。建一次传下去——按写入逐次重建是 O(写入数 × 全树)，跑一批题白烧 CPU。"""
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _ctx(parent: dict, target):
    """(是否在条件分支内, 是否在函数体内)。函数体优先：函数内的赋值本来就取不到。"""
    branch = func = False
    cur = parent.get(target)
    while cur is not None:
        if isinstance(cur, _FUNC):
            func = True
        elif isinstance(cur, _BRANCHY):
            branch = True
        cur = parent.get(cur)
    return branch, func


def _classify(node):
    """单个 ast 节点对目标变量的写入类型；不是写入就返回 (None, None)。"""
    if isinstance(node, ast.Assign):
        if any(isinstance(t, ast.Name) for t in node.targets):
            return "assign", node.value
        if any(isinstance(t, ast.Subscript) for t in node.targets):
            return "mutate", node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return "ann", node.value
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        return "mutate", node.value
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        if isinstance(f, ast.Attribute) and f.attr in _MUTATORS and isinstance(f.value, ast.Name):
            return "mutate", node.value
    return None, None


def _writes(tree, name: str, parent: dict | None = None):
    """按行号收集对 `name` 的全部写入。同名遮蔽（两处 result）取最后一行，行号就是顺序。"""
    parent = parent if parent is not None else _parent_map(tree)
    out = []
    for node in ast.walk(tree):
        kind, value = _classify(node)
        if kind is None:
            continue
        # 确认被写的是不是 name 本人：Assign 的 target / Subscript 的父名字 / Attribute 的父名字
        hit = False
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                base = t.value if isinstance(t, ast.Subscript) else t
                if isinstance(base, ast.Name) and base.id == name:
                    hit = True
        elif isinstance(node, ast.Expr):
            f = node.value.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == name:
                hit = True
        if not hit:
            continue
        branch, func = _ctx(parent, node)
        out.append(_Write(kind, value, getattr(node, "lineno", 0), branch, func))
    out.sort(key=lambda w: w.line)
    return out


def _name_writes(tree, parent: dict):
    """{变量名: [_Write...]}，给单层名字追溯用。"""
    table = {}
    for node in ast.walk(tree):
        kind, value = _classify(node)
        if kind is None:
            continue
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target] if isinstance(node.target, ast.Name) else []
        else:
            continue
        if not targets:
            continue
        branch, func = _ctx(parent, node)
        w = _Write(kind, value, getattr(node, "lineno", 0), branch, func)
        for t in targets:
            table.setdefault(t.id, []).append(w)
    for v in table.values():
        v.sort(key=lambda w: w.line)
    return table


def _is_literal(node) -> bool:
    """整棵子树是否只由字面量构成（`-1`、`[1, 2]`、`{'a': 1}` 都算）。"""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_literal(node.operand)
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(v, ast.Constant) for v in node.values)   # f-string 里有 {} 就不算
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return (all(k is None or _is_literal(k) for k in node.keys)
                and all(_is_literal(v) for v in node.values))
    return False


def _literal_kind(node) -> str:
    """字面量再分一层：文本 / 标量 / 容器。清单要能排序和过滤才有用。"""
    if isinstance(node, ast.JoinedStr):
        return "literal_text"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "literal_text"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return "literal_container"
    return "literal_scalar"


def _trace(node, table, depth, seen):
    """顺着 `Name` 往回追值。追不到返回 None——调用方按 computed 处理。

    "判不了"一律往"值来自运行时"靠，宁可漏报，不许把算出来的答案标成编的。
    """
    if _is_literal(node):
        return node
    if not isinstance(node, ast.Name):
        return None
    if node.id in seen or depth <= 0:
        return None
    seen.add(node.id)
    ws = table.get(node.id) or []
    if not ws:
        return None
    last = ws[-1]
    if last.kind == "mutate" or last.value is None:
        return None
    return _trace(last.value, table, depth - 1, seen)


def result_origin(code: str):
    """`result` 的值来自计算还是字面量。返回上述值域之一，或 None / "unparsed"。"""
    tree, _ = _parse(code)
    if tree is None:
        return "unparsed"
    parent = _parent_map(tree)
    ws = _writes(tree, "result", parent)
    if not ws:
        return None
    last = ws[-1]
    if last.kind == "mutate":
        return "mutated"
    if last.value is None:                        # `result: dict` 只声明不赋值
        return "computed"
    resolved = _trace(last.value, _name_writes(tree, parent), _TRACE_DEPTH, set())
    return "computed" if resolved is None else _literal_kind(resolved)


def _is_empty_container(node) -> bool:
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    return False


def result_missing(code: str, executed: bool, result) -> str | None:
    """`executed=True` 但 `result is None` 时，说明为什么没交卷。其他情况返回 None。"""
    if not executed or result is not None:
        return None
    tree, _ = _parse(code)
    if tree is None:
        return "unparsed"
    ws = _writes(tree, "result")
    if not ws:
        return "no_assign"
    last = ws[-1]
    if last.kind != "mutate" and last.value is not None:
        if _is_empty_container(last.value):
            return "empty"
        if isinstance(last.value, ast.Constant) and last.value.value is None:
            return "assign_none"
    if all(w.in_func for w in ws):
        return "in_function"
    if all(w.in_branch for w in ws):
        return "cond_assign"
    return "assign_none"


def describe(code: str, executed: bool, result) -> dict:
    """runner 需要的两个字段一次算完。代码为空时不编造值。"""
    if not code:
        missing = "no_assign" if (executed and result is None) else None
        return {"result_origin": None, "result_missing": missing}
    return {"result_origin": result_origin(code),
            "result_missing": result_missing(code, executed, result)}
