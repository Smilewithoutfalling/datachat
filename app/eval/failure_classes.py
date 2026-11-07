"""失败归因的**唯一常量表**（EV-D2）。

为什么要有这张表：闸门报告里的 `failure_class` 是人工填的（1–6 或自由文本），
`run_eval` 报告的 `evidence.failures` 是机器码（`ANSWER_RESULT_MISMATCH` 之类）。
两边格式不同、语义重叠，没有映射就只能靠人记"这个码该去改哪个模块"。
本文件把它们收成一张表：**每个码指向一个具体模块和第一个该动的方向**。

三条纪律：
1. **码只增不改**：已有码的语义漂移会让历史报告的 triage 结果前后不一致。
2. **未映射必须打印**（见 `scripts/eval/triage.py`）：静默丢弃等于假装归因完成。
3. **infra 不算模型错**：LLM/网络/取消类错误在报告里已有 `error` 字段区分，
   不进本表，triage 单独归到 `infra` 桶。

文档侧 `docs/eval/failure-map.md` 的表格必须与本文件的码集合逐字相等，
`tests/test_failure_map.py` 钉住这条 —— 只改一边会红。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureClass:
    code: str                 # 稳定标识（历史报告引用它，别改名）
    label: str                # 人话标签
    gate_id: int | None       # 闸门 FAILURE_CLASSES 的编号（scripts/gate/questions.py）
    module: str               # 首个修复落点
    fix: str                  # 首个修复方向
    keywords: tuple[str, ...]  # 自由文本 → 本码的匹配关键词（大小写不敏感）
    history: tuple[str, ...] = ()


# ---------------------------------------------------------------- 闸门六类（人工）

GATE_CLASSES: tuple[FailureClass, ...] = (
    FailureClass(
        code="F01_PARSE", label="编码/解析", gate_id=1,
        module="app/tools/csv_io.py",
        fix="先看解码链：编码猜测顺序、分隔符嗅探、千分位/货币符号清洗；报错样例进 csv_io 的单测夹具",
        keywords=("编码", "解析", "乱码", "分隔符", "编码错", "parse", "encoding", "gbk", "utf"),
        history=("s07 千分位未清洗导致 sum 静默为字符串拼接",),
    ),
    FailureClass(
        code="F02_SCHEMA", label="schema 理解", gate_id=2,
        module="app/tools/schema.py",
        fix="看模型是否把列语义搞错：采样行不够、类型名误导、尾部统计行被当明细；改 schema 渲染而不是改提示词",
        keywords=("schema", "列名", "字段", "理解", "表头", "类型"),
        history=("m03 把 leave_date 为空当成'在职'以外的口径",),
    ),
    FailureClass(
        code="F03_CALIBER", label="口径歧义", gate_id=3,
        module="app/tools/dictionary.py",
        fix="口径没写清或没被检索到：补数据字典条目（dictionary.csv），或让检索命中率进报告",
        keywords=("口径", "歧义", "定义", "含不含", "算不算", "净额", "caliber"),
        history=("s03 净额口径未说明是否含取消单",),
    ),
    FailureClass(
        code="F04_COMPUTE", label="计算错", gate_id=4,
        module="app/tools/sandbox.py",
        fix="代码算错了：先看是聚合层级（groupby 键）、去重、还是排序取前 N；能进扰动题就进扰动题",
        keywords=("计算", "算错", "聚合", "去重", "排序", "算术", "compute"),
        history=("m04 跨表排序按订单数取 Top5 时用了客户表行数",),
    ),
    FailureClass(
        code="F05_CONTRACT", label="result 契约违反", gate_id=5,
        module="app/core/result.py",
        fix="result 形态不合约（None / 未赋值 / 结构不是表或标量）：看执行器收尾与 format_result 的兜底",
        keywords=("契约", "result", "未赋值", "输出格式", "contract"),
        history=("s02 只打印没赋值 result",),
    ),
    FailureClass(
        code="F06_REFUSAL", label="拒答失当", gate_id=6,
        module="app/core/service.py",
        fix="该拒不拒 / 不该拒却拒：看负向题集（neg_*）与 expect_kind 的判定路径",
        keywords=("拒答", "澄清", "反问", "impossible", "clarify", "refusal"),
        history=("m09 缺年龄段列却硬算",),
    ),
)

# ---------------------------------------------------------------- 自动证据码（机器）

AUTO_CLASSES: tuple[FailureClass, ...] = (
    FailureClass(
        code="A01_ANSWER_RESULT_MISMATCH", label="答案数字与 result 不一致", gate_id=None,
        module="app/core/service.py",
        fix="总结层把 result 里的数字写错或换算错：看 summarize 段的证据注入与换算规则（0.2493↔24.93）",
        keywords=("answer_result_mismatch", "答案", "结果不一致"),
        history=("B4 断言 1 上线后首批命中：答案写 288407、result 是 274673",),
    ),
    FailureClass(
        code="A02_CHART_RESULT_MISMATCH", label="图表与 result 不一致", gate_id=None,
        module="app/core/chart_check.py",
        fix="图与结果用了两套数据：先看图表是从哪个 df 生成的（是否漏了同一过滤/聚合）",
        keywords=("chart_result_mismatch", "图表", "图不一致"),
        history=("B3 落地后首轮：拆解图 vs 合计 result 的误报靠'和匹配'救回",),
    ),
    FailureClass(
        code="A03_TIME_FILTER_MISMATCH", label="时间词与代码不一致", gate_id=None,
        module="app/core/service.py",
        fix="问题里的时间词没落到代码过滤上：看执行器对 today 的注入与相对时间解析",
        keywords=("time_filter_mismatch", "时间", "日期过滤"),
        history=("mul_031 追问'上个月'时沿用第一轮区间",),
    ),
    FailureClass(
        code="A04_TOTAL_ROW_COUNTED", label="尾部统计行被当明细", gate_id=None,
        module="app/tools/schema.py",
        fix="schema 已标注尾部统计行（F03 注解）；若仍复现，看注解是否被截断或被提示词挤掉",
        keywords=("total_row", "合计行", "统计行", "汇总行"),
        history=("扰动全量 20 题 total_row 5 败：emp_001 报 204 在职（真值 203）、agg_003 报 61 条（真值 60）",),
    ),
)

ALL_CLASSES: tuple[FailureClass, ...] = GATE_CLASSES + AUTO_CLASSES

BY_CODE: dict[str, FailureClass] = {c.code: c for c in ALL_CLASSES}
BY_GATE_ID: dict[int, FailureClass] = {c.gate_id: c for c in GATE_CLASSES if c.gate_id}


def codes() -> set[str]:
    """全部稳定码（文档表格必须与它相等）。"""
    return set(BY_CODE)


# 扰动变体 → 归因码。扰动报告（`scripts/perturb_full.py`）不写 evidence，
# 但 `variant_kind` 本身就是确定性的归因信号：这是哪种鲁棒性被打破。
# 九种变体里只有 total_row 落在 schema 层，其余都是解析/类型层。
PERTURB_CODES: dict[str, str] = {
    "total_row": "A04_TOTAL_ROW_COUNTED",
    "merged_header": "F01_PARSE",
    "two_row_header": "F01_PARSE",
    "thousand_sep": "F01_PARSE",
    "percent_str": "F01_PARSE",
    "date_compact": "F01_PARSE",
    "dup_columns": "F01_PARSE",
    "empty_col": "F01_PARSE",
    "footer_note": "F01_PARSE",
}


def code_for_variant(kind: str | None) -> str | None:
    """扰动变体名 → 码；未知变体返回 None（调用方打印，不许静默）。"""
    if not kind:
        return None
    return PERTURB_CODES.get(str(kind).strip().lower())



def match(text: str | int | None) -> FailureClass | None:
    """把报告里的一条 `failure_class` 归到一个码。

    - 闸门人工填的是 1–6 的整数 → 直接按 gate_id 命中；
    - 自由文本（"② 缺失哨兵"、"schema 理解错"）→ 关键词匹配，多个命中取**最长关键词**那条
      （更具体者优先，例如"计算错"不会抢走"合计行被计入"）。
    - 认不出 → None。**调用方必须把 None 打印出来**，不许静默丢。
    """
    if text is None or text == "":
        return None
    if isinstance(text, int):
        return BY_GATE_ID.get(text)
    s = str(text).strip()
    if s.isdigit():
        return BY_GATE_ID.get(int(s))
    low = s.lower()
    best: tuple[int, FailureClass] | None = None
    for c in ALL_CLASSES:
        for kw in c.keywords:
            if kw.lower() in low and (best is None or len(kw) > best[0]):
                best = (len(kw), c)
    return best[1] if best else None


def reference_of(code: str) -> str:
    """一行回给人看的定位串：模块 + 首个修复方向。"""
    c = BY_CODE.get(code)
    if not c:
        return f"{code}: 未登记（先补 app/eval/failure_classes.py 与 docs/eval/failure-map.md）"
    return f"{c.label} → {c.module}：{c.fix}"
