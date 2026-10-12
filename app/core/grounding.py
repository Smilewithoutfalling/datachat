"""结论里的数字能不能在证据里找到（阶段 3.6，B64）。

闸门 m06：金额对，但结论里"1,061 单 / 953 单有支付"是编的（真值 84 单）。这里只做**检测**：
把结论里的数字逐个到证据（工具返回的 result、print 输出、问题本身）里找，找不到的列为"未核实"，
写进 AnalysisResult.unverified_numbers，供界面提示和评测抽审；不改写结论。

匹配口径（宁可漏报，不要误报）：
- 只检查"有分量"的数字：带小数、带 %/万/亿，或绝对值 ≥ 100 的整数；年份（1900–2100 的整数且后跟"年"或无小数）跳过。
- 按结论里写出的精度比较：82.2 万 ≈ 822,023.63；24.93% ≈ 24.93 或 0.2493；8,998,790.91 = 8998790.914。
- 由几个证据数字算出来的数（差、和、比）找不到时也会列为未核实——它们确实没有出现在证据里，是否可信由人判断。
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_.])([-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)(?:\s*(%|％|万|亿))?(?![A-Za-z0-9_])"
)
_UNIT = {"万": 1e4, "亿": 1e8}


def _tokens(text: str):
    """[(原文, 数值, 小数位, 单位)]"""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        raw, unit = m.group(1), m.group(2) or ""
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        out.append((m.group(0).strip(), v, dec, unit, text[m.end():m.end() + 1]))
    return out


def _significant(v: float, dec: int, unit: str, after: str) -> bool:
    if unit:
        return True
    if dec == 0 and 1900 <= v <= 2100:
        return False                       # 年份
    if dec == 0 and after == "年":
        return False
    return dec > 0 or abs(v) >= 100


def _candidates(v: float, dec: int, unit: str):
    """结论里的一个数可能对应证据里的哪些值（值, 容差）。"""
    tol = 0.5 * 10 ** (-dec) + 1e-9
    if unit in _UNIT:
        f = _UNIT[unit]
        return [(v * f, tol * f), (v, tol)]
    if unit in ("%", "％"):
        return [(v, tol), (v / 100, tol / 100)]
    return [(v, tol), (v * 100, tol * 100), (v / 100, tol / 100)]   # 比例 ↔ 百分数


def unverified_numbers(answer: str, evidence: list[str]) -> list[str]:
    """结论里找不到证据的数字（原文写法，去重保序）。evidence 为空时不判（返回 []）。"""
    texts = [t for t in evidence if t]
    if not answer or not texts:
        return []
    ev = [v for t in texts for _, v, _, _, _ in _tokens(t)]
    if not ev:
        return []
    bad, seen = [], set()
    for raw, v, dec, unit, after in _tokens(answer):
        if not _significant(v, dec, unit, after) or raw in seen:
            continue
        seen.add(raw)
        if not any(abs(abs(e) - abs(c)) <= t for c, t in _candidates(v, dec, unit) for e in ev):
            bad.append(raw)
    return bad
