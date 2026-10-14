"""图表冒烟两条（M13，DEVLOG [22]/[23]/[27]），与准确率分开报：

- 出图率：分母 = 调了 chart() 或 plt 的题；未通过 = 其中没有产出任何图的题。门槛：每轮至多 1 题。
- chart_option 链路：分母 = 调了 chart() 的题；通过 = 至少产出一张合格 option。
  ChartError（模型选错列、参数冲突）计为未通过；非 ChartError（我们的 bug）单列报警、必须清零，不算模型的错。
- 另外 eval 用例里 3 道 has_chart 题必须全部出图（在 run_eval 的报告里看）。

"调了 plt"按代码静态判断（plt. / .plot( / .plot.xxx( / ax.xxx( 之类），扫描本次分析所有尝试过的代码。
"""
from __future__ import annotations

import re

_PLT = re.compile(r"\bplt\.|\.plot(\.\w+)?\(|\b(ax|axes|fig)\w*(\[[^\]]*\])?\.\w+\(|\.hist\(")


def _codes(res) -> list[str]:
    codes = [s.code for s in getattr(res, "steps", []) if getattr(s, "code", None)]
    if res.code:
        codes.append(res.code)
    return codes


def chart_row(res) -> dict:
    """单题的图表统计（写进闸门 / 评测报告的每一行）。"""
    used_plt = any(_PLT.search(c) for c in _codes(res))
    charts = res.charts or []
    n_opt = sum(1 for c in charts if isinstance(c, dict) and c.get("option"))
    n_png = sum(1 for c in charts if (isinstance(c, dict) and c.get("png")) or isinstance(c, str))
    return {
        "chart_calls": res.chart_calls, "used_plt": used_plt,
        "drew": bool(res.chart_calls or used_plt), "options": n_opt, "pngs": n_png,
        "chart_errors": list(res.chart_errors), "chart_internal_errors": list(res.chart_internal_errors),
        "charts_discarded": res.charts_discarded,
    }


def summarize(rows: list[dict], ids: list[str] | None = None) -> dict:
    """rows：[{"id":…, "chart": chart_row(...)}]（没有 chart 字段的旧报告行跳过）。"""
    ids = ids or [str(i) for i in range(len(rows))]
    drew, no_chart, called, opt_ok, opt_fail, internal = [], [], [], [], [], []
    for rid, r in zip(ids, rows):
        c = r.get("chart") if isinstance(r, dict) else None
        if not c:
            continue
        if c["drew"]:
            drew.append(rid)
            if not (c["options"] or c["pngs"]):
                no_chart.append(rid)
        if c["chart_calls"]:
            called.append(rid)
            (opt_ok if c["options"] else opt_fail).append(rid)
        if c["chart_internal_errors"]:
            internal.append(rid)
    return {
        # pass 为 None = 分母为 0，"无样本"：不算通过也不算失败（[27]）
        "出图率": {"drew": len(drew), "no_chart": no_chart, "pass": (len(no_chart) <= 1) if drew else None,
                 "rule": "调了 chart() 或 plt 的题里，每轮至多 1 题无图"},
        "chart_option": {"called": len(called), "ok": len(opt_ok), "fail": opt_fail,
                         "pass": (not opt_fail and not internal) if called else (False if internal else None),
                         "rule": "调了 chart() 的题全部产出合格 option；内部错误必须为 0"},
        "internal_errors": internal,
    }
