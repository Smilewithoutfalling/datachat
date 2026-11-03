"""E2 过程验证（离线，不调模型）：代码写得对不对路，而不是答案对不对。

**定位：给人工判定提供结构异常标记，不参与自动判对。** 写进报告的 `process_risks` 字段。

## 为什么只有两条规则

规格原文（docs/roadmap/phase7-accuracy.md §2 E2）写了两件事，实测下来一件已经被做过、
另一件一条都没命中：

1. 「`result = <字面量数字>` 这类硬编码答案单独标记」—— **`provenance.result_origin` 已经在做**，
   而且是 2026-11-02 用 481 份真实代码验过的：40 条字面量、**37 条判对**，属于常规提交方式不是作弊。
   再做一遍只是重复，且按那条思路判错会大面积误伤（本模块原型测出 1 次命中、1 次误报）。
2. 「读取的列必须在 schema 里」—— **8 道人工判错的题里一条都没命中**。逐题看过：错因是
   口径歧义、缺失哨兵、取消单未冲减、样本不完整，没有一道是"读了不存在的列"。见 [112]。

所以规则是从 13 份闸门报告的 205 个 case 上反推的，不是凭规格想象的。

## 两条规则各自抓什么

`unnamed_column` —— 代码里出现 `Unnamed: N` 这样的列名，并且**不是**在 rename/drop 里。
含义是「表头读取失败后不重读，直接按位置硬猜」。闸门里有两次大的翻车都是这个：
`s06` 把 `Unnamed: 3`（数量）当成单价算，`s04` 把 `Unnamed: 7` 当国家列、还漏了末行合计。
实测 4 次命中、**全部是判错的 case**、0 误报。

`placeholder_result` —— `result` 被赋成 ≤5 字符的字符串，且不含任何拒答措辞（典型 `result='ok'`）。
实测 1 次命中（`m09` 该拒答却交 `'ok'`），判错、0 误报。**样本只有 1 个，别当可靠的规则用。**
"""
from __future__ import annotations

import ast
import re

__all__ = ["check_code", "details", "summarize", "RULES"]

# 报表被 `header=0` 读坏之后 pandas 给的名字；出现它就说明表头没读对。
_UNNAMED = re.compile(r"^Unnamed: \d+$")

# 拒答是正常答复，不是占位符。词表取自 63 题留出集与闸门里真实出现过的措辞。
_REFUSAL_WORDS = ("没有", "无法", "不含", "不包含", "缺少", "缺乏", "不存在", "不提供", "仅有", "只有")

# 只在 rename / drop 里提到 Unnamed 列名是**正确处理**（认出列名坏了并丢弃/改名），不算风险。
_EXEMPT_CALLS = ("rename", "drop")

RULES = {
    "unnamed_column": "引用了 Unnamed: N 列名（表头没读对，按位置硬猜列）",
    "placeholder_result": "result 是占位符文本（非拒答措辞）",
}


def _str_constants(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node


def _exempt_unnamed(tree: ast.AST) -> set[str]:
    """`rename(columns={'Unnamed: 3': '数量'})` / `drop(columns=['Unnamed: 3'])` 里的名字。

    这两种写法说明模型**认出了**列名是坏的并主动处理，不该标风险。
    只认字面量 key / 元素，`rename(columns=mapping)` 这种变量形式不猜。
    """
    exempt: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _EXEMPT_CALLS:
            continue
        for kw in node.keywords:
            if kw.arg != "columns":
                continue
            if isinstance(kw.value, ast.Dict):
                for k in kw.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        exempt.add(k.value.strip())
            elif isinstance(kw.value, (ast.List, ast.Tuple)):
                for e in kw.value.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        exempt.add(e.value.strip())
    return exempt


def _last_result_value(tree: ast.AST):
    last = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "result" for t in node.targets
        ):
            if last is None or node.lineno > last.lineno:
                last = node
    return last.value if last is not None else None


def check_code(code: str | None) -> list[str]:
    """返回结构异常标记（规则名列表）。空列表 = 未发现。

    只报能确定的。判不了的一律不猜：代码有语法错、`result` 来自变量、列名完全动态，都不产生标记。
    """
    return [d["rule"] for d in details(code)]


def details(code: str | None) -> list[dict]:
    """同 `check_code`，但每条带定位：`{"rule", "line", "text"}`。

    回放脚本靠它打印命中的那一行——只有规则名的话，人还得自己去 200 行代码里找。
    """
    if not code or not code.strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.splitlines()

    def _text(node) -> str:
        return lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""

    out: list[dict] = []

    exempt = _exempt_unnamed(tree)
    hits = [
        n for n in _str_constants(tree)
        if _UNNAMED.match(n.value.strip()) and n.value.strip() not in exempt
    ]
    if hits:
        first = min(hits, key=lambda n: n.lineno)
        out.append({
            "rule": "unnamed_column",
            "line": first.lineno,
            "text": _text(first),
            "columns": sorted({n.value.strip() for n in hits}),
        })

    value = _last_result_value(tree)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        text = value.value.strip()
        if len(text) <= 5 and not any(w in text for w in _REFUSAL_WORDS):
            out.append({
                "rule": "placeholder_result",
                "line": value.lineno,
                "text": _text(value),
                "value": text,
            })

    return out


def summarize(rows) -> dict:
    """聚合一批报告行。`rows` 是报告里 `cases` 的那种 dict 列表。

    返回 `{"hits": {规则: 次数}, "n": 有代码的题数, "cases": [题号…]}`。
    只统计，不评价 —— 命中不等于判错，见模块 docstring。
    """
    hits: dict[str, int] = {}
    marked: list[str] = []
    n = 0
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        n += 1
        risks = r.get("process_risks")
        if risks is None:            # 老报告没这字段，现场重算
            risks = check_code(code)
        if risks:
            marked.append(str(r.get("id")))
            for k in risks:
                hits[k] = hits.get(k, 0) + 1
    return {"n": n, "hits": hits, "cases": marked}
