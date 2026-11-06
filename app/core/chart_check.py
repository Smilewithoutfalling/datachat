"""图 ↔ 结果一致性（EV-B3，chart_check）。

为什么需要：图表数据层（xAxis.data / series[].data）由 build_option 从 df 直接生成
（charts.py:4-5，模型写不进数字），所以图错的唯一途径是**画图用的 df 和算 result 用的
不是同一套过滤/聚合**——result 算对了，图却是另一个口径的。这是 m06 类事故的图形版。

产出：`AnalysisResult.chart_check_codes`，二值列表（无图问题为空）：
- `CHART_BAR_VALUE`：柱/线图的数值既不在 result 证据里、各系列和总和也对不上；
- `CHART_PIE_SUM`：饼图扇区值同样三条路都断。

判定口径（宁可漏报，不要误报；与 grounding 同一哲学）。一张图判"通过"只需命中一条路：
1. **值匹配**：任一数值能证据里找到（含 比例↔百分数 双向容差，0.2493 ↔ 24.93）；
2. **和匹配**：各系列之和 / 全部值之和能找到——覆盖"图是明细拆解、result 是合计"
   的正当组合（明细每项都不等于合计，但加起来等于）；
3. 图是散点 / 无结构化 option（matplotlib PNG 路线）/ 没有数值 → 不判，不装作检查过。

证据与断言 1 同源：result_text + str(result)，**不含 question**——问题里出现过的数
不能给图作证。误报控制：三条路全断才记 code；本检查只作 warnings/评测展示，接进判分
前要过 consistency.py 写明的 <10% 误报率门槛。
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _evidence_numbers(res) -> list[float]:
    """证据里的全部数值（result_text + str(result)，不含 question）。"""
    texts = [getattr(res, "result_text", "") or "", str(getattr(res, "result", ""))]
    out = []
    for t in texts:
        if t:
            out.extend(float(m.group(0)) for m in _NUM_RE.finditer(t))
    return out


def _match(v: float, ev: list[float]) -> bool:
    """图里的一个数值是否能在证据数里找到（比例↔百分数双向，相对容差 1e-6）。"""
    if not ev:
        return False
    for c in (v, v * 100, v / 100):
        for e in ev:
            if abs(abs(e) - abs(c)) <= 1e-6 * max(1.0, abs(c)):
                return True
    return False


def _option_values(option: dict) -> tuple[str, list[float]]:
    """(series 类型, 数值列表)。散点返回 (kind, [])——逐点原始数据没有聚合语义，不判。"""
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return "", []
    kind = series[0].get("type", "") if isinstance(series[0], dict) else ""
    vals: list[float] = []
    if kind == "pie":
        for d in series[0].get("data") or []:
            if isinstance(d, dict) and isinstance(d.get("value"), (int, float)) \
                    and not isinstance(d.get("value"), bool):
                vals.append(float(d["value"]))
    elif kind in ("bar", "line"):
        for s in series:
            if isinstance(s, dict):
                for d in s.get("data") or []:
                    if isinstance(d, (int, float)) and not isinstance(d, bool):
                        vals.append(float(d))
    else:
        return kind, []                      # scatter 及未知图型：不判
    return kind, vals


def chart_check(res) -> list:
    """一次成功执行的图 ↔ 结果检查，返回去重后的 code 列表（无问题为空）。"""
    codes: list[str] = []
    if not getattr(res, "executed", False):
        return codes
    ev = _evidence_numbers(res)
    for item in getattr(res, "charts", None) or []:
        option = item.get("option") if isinstance(item, dict) else None
        if not isinstance(option, dict):
            continue                          # matplotlib PNG：无结构化数据，不判
        kind, vals = _option_values(option)
        if not vals:
            continue                          # 没有可判的数值，不装作检查过
        sums = [sum(vals)] + [sum(s["data"]) for s in option.get("series", [])
                              if isinstance(s, dict) and s.get("type") in ("bar", "line")
                              and all(isinstance(d, (int, float)) and not isinstance(d, bool)
                                      for d in (s.get("data") or []))]
        if any(_match(v, ev) for v in vals) or any(_match(s, ev) for s in sums):
            continue
        codes.append("CHART_PIE_SUM" if kind == "pie" else "CHART_BAR_VALUE")
    return list(dict.fromkeys(codes))
