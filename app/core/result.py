"""analyze() 的结构化结果（B07/B16）。

result 字段保留代码执行得到的**原始对象**（DataFrame/Series/标量），不再转成截断字符串；
给模型看的文本另由 format_result 生成，并明确标注是否截断。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional

import pandas as pd

from app.core.llm import TokenUsage


@dataclass
class Step:
    """执行轨迹中的一步。
    name：工作流版为节点名（planner/codegen/executor/reviewer/summarizer）；
          ReAct 版为 tool_call / observation / answer。"""
    name: str
    content: str = ""
    code: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


@dataclass
class AnalysisResult:
    agent: str                                  # "workflow" | "react"
    dataset: str                                # 数据文件路径
    question: str                               # 用户原始问题（不含字典注入，B04）
    trace_id: str = ""                          # 本次分析的追踪 id（阶段 4；事件、日志、runs.jsonl 共用）
    answer: str = ""                            # 自然语言结论
    result: Any = None                          # 最终代码执行的结构化结果（未截断）
    result_text: str = ""                       # 结果的文本预览（给模型/界面用）
    code: str = ""                              # 最终执行成功（或最后一次尝试）的代码
    chart_path: Optional[str] = None            # 最后生成的 PNG 图表（matplotlib）
    charts: list = field(default_factory=list)  # 本次的全部图表：[{"png": 路径或 None, "option": spec 或 None}]（[26]）
    chart_calls: int = 0                        # chart() 被调用的次数（chart_option 链路的分母口径，[23]）
    chart_errors: list = field(default_factory=list)  # ChartError：模型参数问题，计为未通过
    chart_errors_shown: list = field(default_factory=list)  # 图被展示的执行（error 为空）自己的 ChartError；警告只看它（[43]）
    chart_internal_errors: list = field(default_factory=list)  # 非 ChartError：我们的 bug，单列报警，必须清零
    charts_discarded: int = 0                   # exec 失败时丢弃的结构化图张数（[23]）
    plan: str = ""                              # 工作流版的分析计划
    field_notes: list = field(default_factory=list)  # 数据字典命中的 (field, description)
    attempts: int = 0                           # 修复/重试次数（工作流：reviewer 次数；ReAct：报错的执行次数）
    initial_error: Optional[str] = None         # 第一次执行的报错（无则 None），用于修复率统计
    executed: bool = False                      # 是否有代码执行成功并拿到结果
    error: Optional[str] = None                 # 最终错误（成功为 None）
    error_kind: Optional[str] = None            # dataset | llm | execution | agent | cancelled
    llm_kind: Optional[str] = None              # error_kind=llm 时的子类（events.LLM_KINDS 或 http_NNN），其余为 None（V2a 错误卡分出口）
    warnings: list = field(default_factory=list)  # 不算失败但要让用户知道的情况（如 ReAct 步数用完后强制收尾）
    unverified_numbers: list = field(default_factory=list)  # 结论里在证据中找不到的数字（B64，只检测不改写）
    steps: list = field(default_factory=list)   # list[Step]
    timings: dict = field(default_factory=dict) # {"total": 秒, "planner": 秒, ...}
    usage: TokenUsage = field(default_factory=TokenUsage)
    # 阶段 6.6 记忆（memory-system-spec.md §14.3，字段名与类型写死，改名先改规格）：只进结果，不进 prompt
    memory_mode: str = "off"                    # 本轮实际生效的记忆模式（off | state）
    history_tokens: int = 0                     # 送进模型的历史估算 token（off 下按回灌的消息估，作为基线）
    memory_trimmed: list = field(default_factory=list)  # 本轮被预算裁剪的块名：history / state
    rewrite: Optional[dict] = None              # M7 指代 / 时间改写的记录；批 1 未做，恒为 None
    result_digest: str = ""                     # 结果的类型与形状（不含值），下一轮的历史快照用（M3）

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_record(self) -> dict:
        """可 JSON 序列化的字典（result 只保留文本预览），用于 runs.jsonl 与以后的 API。"""
        d = {}
        for f in fields(self):
            if f.name == "result":
                continue                     # 原始对象不进 JSON，用 result_text
            v = getattr(self, f.name)
            if f.name == "usage":
                v = asdict(v)
            elif f.name == "steps":
                v = [asdict(s) for s in v]
            elif f.name == "field_notes":
                v = [list(x) for x in v]
            d[f.name] = v
        d["ok"] = self.ok
        return d


def chart_items(png: Optional[str], options: list) -> list:
    """一次成功执行产出的图表条目：chart() 的结构化图在前（前端优先），matplotlib 的 PNG 在后（退路）。"""
    items = [{"png": None, "option": o} for o in options or []]
    if png:
        items.append({"png": png, "option": None})
    return items


def chart_note(png: Optional[str], options: list) -> str:
    """给 summarizer 的图表提示：PNG 路径，以及 chart() 出的图的标题（没有标题时写图型）。"""
    parts = []
    names = []
    for o in options or []:
        try:
            names.append(o["option"]["title"]["text"])
        except (KeyError, TypeError):
            names.append(str(o.get("kind", "图表")) if isinstance(o, dict) else "图表")
    if names:
        parts.append(f"已生成 {len(names)} 张图表：" + "、".join(names))
    if png:
        parts.append(f"已生成图表 {png}")
    return "（" + "；".join(parts) + "）" if parts else ""


def last_png(charts: list) -> Optional[str]:
    for c in reversed(charts or []):
        if isinstance(c, dict) and c.get("png"):
            return c["png"]
    return None


CHART_NONE_WARNING = "图没画出来：模型给的画图参数和结果数据对不上。结论不受影响，可以重新生成。"
CHART_PARTIAL_WARNING = "另有 {n} 张图没画出来：画图参数和结果数据对不上。"


def chart_warnings(res: "AnalysisResult", truncation: list) -> list:
    """图表相关、不算失败但必须让用户看到的情况（[23]/[24]：不允许静默截断、静默丢弃）。"""
    out = list(dict.fromkeys(truncation))
    has_option = any(isinstance(c, dict) and c.get("option") for c in res.charts)
    if res.charts_discarded:
        tail = "，展示的是成功那次执行的图" if res.executed and res.charts else ""
        out.append(f"有代码执行失败，失败那次用 chart() 画的 {res.charts_discarded} 张图已丢弃，不展示{tail}")
    # 只报展示出来的那（几）次执行自己的 chart_error：失败执行的图已由上一条"已丢弃"覆盖，它的旧错误不再成立；
    # 同一次成功执行里一张成功一张失败，失败那张必须报（[23]/[24] 不静默丢弃；result.py:117 旧条件 not has_option 会吞掉它）。
    # P1-17（阶段 5 收尾 D）：给用户的两条是固定文案，不带 ChartError 原文——原文是写给模型看的（列名、参数名，
    # 让模型自己改），照旧经 chart_errors 回到模型；界面上从此看不到原文（前端没有任何地方读 chart_errors）。
    shown = res.chart_errors_shown
    if shown and not has_option:
        out.append(CHART_NONE_WARNING)
    elif shown:
        out.append(CHART_PARTIAL_WARNING.format(n=len(shown)))
    if res.chart_internal_errors:
        out.append("图表生成遇到内部错误，已记录")
    return out


def format_result(result: Any, max_chars: int = 3000, max_rows: int = 60) -> str:
    """把结果转成给模型看的文本。表格过大时显示头尾 + 形状，并写明已截断，
    让 summarizer 知道自己看到的是部分数据，而不是悄悄切掉（B07）。"""
    if result is None:
        return "（result 为空：代码没有给 result 赋值）"
    if isinstance(result, (pd.DataFrame, pd.Series)):
        n = len(result)
        kind = "表格" if isinstance(result, pd.DataFrame) else "序列"
        shape = f"{n} 行 × {result.shape[1]} 列" if isinstance(result, pd.DataFrame) else f"{n} 项"
        with pd.option_context("display.max_columns", 50, "display.width", 200):
            if n <= max_rows:
                body = result.to_string()
                note = ""
            else:
                head, tail = max_rows - 10, 10
                body = (result.head(head).to_string() + "\n...\n"
                        + result.tail(tail).to_string(header=isinstance(result, pd.DataFrame)))
                note = f"（共 {n} 行，此处仅显示前 {head} 行和后 {tail} 行）"
        text = f"[{kind}，{shape}]{note}\n{body}"
    else:
        text = str(result)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（文本已截断，原长 {len(text)} 字符）"
    return text


# ---- 拒答契约（阶段 3）：数据回答不了时 result = "无法回答：<原因>" ----
REFUSAL_PREFIX = "无法回答"


def is_refusal(v) -> bool:
    """结果契约（阶段 3）：数据回答不了时 result = "无法回答：<原因>"。只有前缀、没有原因的不算。"""
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s.startswith(REFUSAL_PREFIX):
        return False
    reason = s[len(REFUSAL_PREFIX):].strip(" ：:，,。.；;-—\n\t")
    return len(reason) >= 2


def refusal_from_answer(answer):
    """规则 19：ReAct 没调用工具、直接在结论里拒答时，取结论首行（须以"无法回答"开头）作为 result。"""
    if not isinstance(answer, str):
        return None
    first = answer.strip().splitlines()[0].strip() if answer.strip() else ""
    first = first.strip("*").strip()
    if first.startswith("我无法回答"):        # B49：结论写成"我无法回答：…"
        first = first[1:]
    return first if is_refusal(first) else None
