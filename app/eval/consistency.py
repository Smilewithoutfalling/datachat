"""证据一致性（EV-B4）：答案里的数字、图里的数字、代码里的时间过滤，必须是同一套。

为什么 runner 已经判了对错还要这一层：对错判的是 result 与 gold 相等，**answer 是另一条
通道** —— 模型完全可能 result 算对了、结论里却写了一个编出来的数（闸门 m06 的真事：
result 里 84 单，结论写"1,061 单"）。`unverified_numbers`（B64）早就测这个，但它只展示、
且证据里混了 question —— 问题里出现过的数不算证据。本模块是评测侧的正式断言：

断言 1 **答案 ↔ 结果**（ANSWER_RESULT_MISMATCH）
    answer 里的每个"有分量"的数字，必须能在 result_text 或 str(result) 里找到。
    注意与 service 的 `unverified_numbers` 有意不同：**证据不含 question** ——
    题面里的数字（如"2024年"）抄进答案不算核实。
    数字抽取、归一（千分位 / % / 万 / 亿 / 比例↔百分数 / 年份豁免）、容差全部复用
    `app/core/grounding.py`，不写第二份。规格陷阱三条的对应：
    - "增长 12%" 的 12 是算出来的 → grounding 的 _candidates 本来就允许 12 ↔ 0.12 互换，
      结果里只要存在 12 或 0.12 就放行；
    - 年份 2011 既是数字又是时间 → `_significant` 跳过 1900–2100 的整数（不带小数），
      断言 1 永远不会拿年份找茬；
    - 只看代码不看答案措辞 → 断言 3 只读 res.code。

断言 2 **图 ↔ 结果**（CHART_RESULT_MISMATCH）
    读 `res.chart_check_codes`（EV-B3 chart_check 的产出，app/core/chart_check.py，
    二值列表）。列表非空即说明该次执行的图与 result 三条判定路（值/系列和/总和）全断，
    记一条失败。B3 未覆盖的形态（散点、matplotlib PNG）不产生 code，保持 not applicable
    语义——没检查不装作检查过。

断言 3 **时间词 ↔ 代码**（TIME_FILTER_MISMATCH）
    问题里出现 本月/上月/今年/去年/本季度/上季度/Q[1-4]/\\d{4}年 时，最终代码里必须有
    时间过滤的形态证据（`>=`/`<=`/`between`/`resample`/`dt.year|month|quarter`/日期字面量/
    4 位年份）。只看代码 —— 答案写"今年销售额 120 万"而代码没过滤，就是没过滤。

升级门槛（规格原文）：三条**只作 warnings 展示**，连续 130 题实测误报率 <10% 后才允许
接进判分。在门槛达成前，evidence.failures 不改 correct —— 这个决定写在本文件，
report 侧的 `false_positive_note` 与这里保持同一句话。
"""
from __future__ import annotations

import re

from app.core.grounding import unverified_numbers

# 规格原文的时间词清单，不扩。Q[1-4] 也要认全角问句里常见的 "Q1"。
TIME_WORDS = re.compile(r"本月|上月|今年|去年|本季度|上季度|[Qq][1-4]|\d{4}年")

# 代码里"做过时间过滤"的形态证据。宁可漏报：多认一种形态只少一条警告，少认一种会冤枉人。
_TIME_CODE_EVIDENCE = re.compile(
    r">=|<=|between|resample|dt\.year|dt\.month|dt\.quarter|\.dt\.(year|month|quarter)"
    r"|pd\.Timestamp|to_datetime\(|PeriodIndex|period_range"
    r"|(?:19|20)\d{2}"          # 4 位年份字面量（含 str.startswith('2024') 这类写法）
    r"|query\("
)

# chart_check（EV-B3，app/core/chart_check.py）会写的两个 code
_CHART_CHECK_CODES = ("CHART_BAR_VALUE", "CHART_PIE_SUM")


def check_consistency(res, case) -> dict:
    """三条断言，返回 {"applicable": bool, "failures": [code], "detail": {...}}。

    applicable=False 表示这条题没有可审的证据通道（没执行 / 拒答类 / 没答案），
    failures 为空不代表"检查通过"，代表"不适用"——两层信息分开，报告才不会把
    N.A. 读成满分。detail 只在 failures 非空时才有内容。
    """
    out = {"applicable": False, "failures": [], "detail": {}}
    # 拒答类（expect_refusal / 三种 expect_kind）的 answer 是解释文本，数字没有"证据"可言
    if not getattr(res, "executed", False) or getattr(case, "expect_refusal", False) \
            or getattr(case, "expect_kind", ""):
        return out
    out["applicable"] = True

    # 断言 1：答案 ↔ 结果。证据 = result_text + str(result)，**不含 question**
    # result 可能是 Series/DataFrame，**不许写 `result or ""`** —— 真值判断对 pandas 是歧义的
    answer = getattr(res, "answer", "") or ""
    evidence = [getattr(res, "result_text", "") or "", str(getattr(res, "result", ""))]
    if answer and any(evidence):
        missing = unverified_numbers(answer, evidence)
        if missing:
            out["failures"].append("ANSWER_RESULT_MISMATCH")
            out["detail"]["answer_nums_missing"] = missing

    # 断言 2：图 ↔ 结果。B3 未落地 → not applicable（见模块 docstring）
    codes = getattr(res, "chart_check_codes", None)
    if codes:
        bad = [c for c in codes if c in _CHART_CHECK_CODES]
        if bad:
            out["failures"].append("CHART_RESULT_MISMATCH")
            out["detail"]["chart_check_codes"] = bad

    # 断言 3：时间词 ↔ 代码
    code = getattr(res, "code", "") or ""
    words = sorted(set(TIME_WORDS.findall(getattr(res, "question", "") or "")))
    if words and code and not _TIME_CODE_EVIDENCE.search(code):
        out["failures"].append("TIME_FILTER_MISMATCH")
        out["detail"]["time_words"] = words
    return out
